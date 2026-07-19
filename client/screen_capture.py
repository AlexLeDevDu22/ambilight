"""
screen_capture.py – Capture d'écran Mac via Quartz (CGWindowListCreateImage).

Utilise l'API native macOS pour capturer l'écran, y compris les apps
en plein écran (fullscreen / Spaces séparés), ce que mss ne peut pas faire.

Retourne un numpy.ndarray (H, W, 3) en RGB uint8, avec flou gaussien
intégré pour un rendu ambilight plus fluide.
"""

import numpy as np
import platform

# ─── Détection du backend disponible ────────────────────────────────────────
_USE_QUARTZ = False
_USE_MSS = False

if platform.system() == "Darwin":
    try:
        import Quartz
        import Quartz.CoreGraphics as CG
        _USE_QUARTZ = True
    except ImportError:
        pass

if not _USE_QUARTZ:
    try:
        import mss
        import mss.tools
        _USE_MSS = True
    except ImportError:
        pass



def _fast_blur(frame: np.ndarray, radius: int = 3) -> np.ndarray:
    """Flou rapide par sous-échantillonnage en blocs (box blur ultra-rapide)."""
    if radius <= 1:
        return frame
    h, w, c = frame.shape
    # Arrondir aux dimensions divisibles par radius
    bh = (h // radius) * radius
    bw = (w // radius) * radius
    cropped = frame[:bh, :bw, :]
    # Reshape en blocs et moyenne par bloc, puis repeat
    blocked = cropped.reshape(bh // radius, radius, bw // radius, radius, c)
    means = blocked.mean(axis=(1, 3)).astype(np.uint8)
    # Ré-expansion aux dimensions originales
    result = np.repeat(np.repeat(means, radius, axis=0), radius, axis=1)
    # Recadrer si nécessaire
    return result[:h, :w, :]


class ScreenCapture:
    """Capture l'écran désigné par screen_index (0 = écran principal).
    
    Utilise Quartz (CGWindowListCreateImage) sur macOS pour supporter
    le plein écran et les Spaces, avec fallback sur mss sinon.
    """

    def __init__(self, screen_index: int = 0, downscale: int = 4):
        """
        Args:
            screen_index: index de l'écran (0 = principal).
            downscale: facteur de réduction (4 = divise W et H par 4).
        """
        self.downscale = max(1, downscale)
        self.screen_index = screen_index
        self._blur_radius = 4  # Rayon du flou pour lisser les transitions

        if _USE_QUARTZ:
            self._backend = "quartz"
            self._init_quartz()
        elif _USE_MSS:
            self._backend = "mss"
            self._init_mss()
        else:
            raise RuntimeError("Aucun backend de capture disponible (Quartz ou mss requis)")

    def _init_quartz(self):
        """Initialise le backend Quartz."""
        # Récupérer les IDs des écrans
        max_displays = 16
        (err, display_ids, count) = CG.CGGetActiveDisplayList(max_displays, None, None)
        if err != 0 or count == 0:
            raise RuntimeError(f"Erreur CGGetActiveDisplayList: {err}")
        
        idx = min(self.screen_index, count - 1)
        self._display_id = display_ids[idx]
        
        # Dimensions natives de l'écran
        bounds = CG.CGDisplayBounds(self._display_id)
        self._native_w = int(bounds.size.width)
        self._native_h = int(bounds.size.height)
        self._bounds = bounds

    def _init_mss(self):
        """Initialise le backend mss (fallback)."""
        self._sct = mss.mss()
        monitor_index = self.screen_index + 1
        monitors = self._sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 1
        self.monitor = monitors[monitor_index]

    def capture(self) -> np.ndarray:
        """Capture l'écran et retourne un tableau numpy (H, W, 3) RGB uint8."""
        if self._backend == "quartz":
            frame = self._capture_quartz()
        else:
            frame = self._capture_mss()

        # Downscale
        if self.downscale > 1:
            frame = frame[:: self.downscale, :: self.downscale, :]

        # Flou gaussien pour lisser les transitions de couleur
        frame = _fast_blur(frame, self._blur_radius)

        return np.ascontiguousarray(frame)

    def _capture_quartz(self) -> np.ndarray:
        """Capture via Quartz CGWindowListCreateImage."""
        # CGWindowListCreateImage capture TOUT ce qui est affiché,
        # y compris les apps fullscreen dans un Space séparé.
        # kCGWindowImageNominalResolution = capture en résolution logique (pas Retina 2x)
        # → beaucoup plus rapide et suffisant pour l'ambilight
        image = CG.CGWindowListCreateImage(
            self._bounds,
            CG.kCGWindowListOptionOnScreenOnly,
            CG.kCGNullWindowID,
            CG.kCGWindowImageNominalResolution
        )

        if image is None:
            # Fallback : essayer avec CGRectInfinite
            image = CG.CGWindowListCreateImage(
                CG.CGRectInfinite,
                CG.kCGWindowListOptionOnScreenOnly,
                CG.kCGNullWindowID,
                CG.kCGWindowImageDefault
            )
        
        if image is None:
            return np.zeros((100, 100, 3), dtype=np.uint8)

        width = CG.CGImageGetWidth(image)
        height = CG.CGImageGetHeight(image)
        bytes_per_row = CG.CGImageGetBytesPerRow(image)
        
        # Récupérer les données pixels
        data_provider = CG.CGImageGetDataProvider(image)
        data = CG.CGDataProviderCopyData(data_provider)
        
        # Convertir en numpy array
        arr = np.frombuffer(data, dtype=np.uint8)
        
        # Le stride (bytes_per_row) peut être plus grand que width * 4
        # On doit reshaper en tenant compte du stride
        arr = arr.reshape((height, bytes_per_row // 1))
        # Extraire seulement les pixels utiles (4 bytes par pixel : BGRA)
        arr = arr[:, :width * 4].reshape((height, width, 4))
        
        # BGRA → RGB
        frame = arr[:, :, [2, 1, 0]].copy()
        
        return frame

    def _capture_mss(self) -> np.ndarray:
        """Capture via mss (fallback non-Mac)."""
        sct_img = self._sct.grab(self.monitor)
        frame = np.frombuffer(sct_img.raw, dtype=np.uint8)
        frame = frame.reshape((sct_img.height, sct_img.width, 4))
        frame = frame[:, :, [2, 1, 0]]
        return frame

    def resolution(self) -> tuple[int, int]:
        """Retourne (W, H) de l'écran après downscale."""
        if self._backend == "quartz":
            w = self._native_w // self.downscale
            h = self._native_h // self.downscale
        else:
            w = self.monitor["width"] // self.downscale
            h = self.monitor["height"] // self.downscale
        return w, h

    def close(self):
        if self._backend == "mss" and hasattr(self, "_sct"):
            self._sct.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
