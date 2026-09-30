"""
screen.py – Capture d'écran (Quartz) et mapping bords de l'écran → LEDs.

Le mapping est entièrement vectorisé : une image intégrale donne la moyenne
de chaque zone en O(1), sans boucle Python par LED.
"""

import numpy as np

try:
    import Quartz.CoreGraphics as CG
    QUARTZ_OK = True
except Exception:
    CG = None
    QUARTZ_OK = False

DOWNSCALE = 4


def screen_count() -> int:
    if not QUARTZ_OK:
        return 1
    try:
        err, _ids, count = CG.CGGetActiveDisplayList(16, None, None)
        return int(count) if err == 0 else 1
    except Exception:
        return 1


def open_capture(screen_index: int = 0, fps: int = 30):
    """ScreenCaptureKit si possible (léger), sinon CGWindowListCreateImage."""
    try:
        from .sck_capture import SCKCapture
        return SCKCapture(screen_index, fps)
    except Exception as e:
        print(f"[screen] ScreenCaptureKit indisponible ({e}), repli Quartz")
        return ScreenCapture(screen_index)


class ScreenCapture:
    scale = DOWNSCALE

    def __init__(self, screen_index: int = 0):
        if not QUARTZ_OK:
            raise RuntimeError("capture d'écran indisponible (pyobjc-framework-Quartz)")
        err, ids, count = CG.CGGetActiveDisplayList(16, None, None)
        if err != 0 or count == 0:
            raise RuntimeError("aucun écran détecté")
        self.screen_index = min(screen_index, count - 1)
        self._bounds = CG.CGDisplayBounds(ids[self.screen_index])
        self.native_w = int(self._bounds.size.width)

    def close(self):
        pass

    def capture(self) -> np.ndarray | None:
        """Image RGB uint8 réduite (~1/4), ou None si la capture échoue."""
        image = CG.CGWindowListCreateImage(
            self._bounds,
            CG.kCGWindowListOptionOnScreenOnly,
            CG.kCGNullWindowID,
            CG.kCGWindowImageNominalResolution,
        )
        if image is None:
            return None
        w = CG.CGImageGetWidth(image)
        h = CG.CGImageGetHeight(image)
        bpr = CG.CGImageGetBytesPerRow(image)
        data = CG.CGDataProviderCopyData(CG.CGImageGetDataProvider(image))
        arr = np.frombuffer(data, dtype=np.uint8).reshape((h, bpr))[:, : w * 4].reshape((h, w, 4))
        # Sous-échantillonnage d'abord (moins de mémoire), puis BGRA → RGB
        return arr[::DOWNSCALE, ::DOWNSCALE, 2::-1]


def led_layout(led_sides: dict) -> np.ndarray:
    """Position (x, y) normalisée [0,1] de chaque LED (y vers le bas).

    Ordre du ruban : bas G→D, droite B→H, haut D→G, gauche H→B, bas (retour).
    """
    pts = []

    def seg(count, x0, y0, x1, y1):
        for i in range(count):
            t = (i + 0.5) / count
            pts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))

    s = led_sides
    seg(s.get("bottom_left_count", 0), 0, 1, 1, 1)
    seg(s.get("right_count", 0), 1, 1, 1, 0)
    seg(s.get("top_count", 0), 1, 0, 0, 0)
    seg(s.get("left_count", 0), 0, 0, 0, 1)
    seg(s.get("bottom_right_count", 0), 1, 1, 0, 1)
    return np.array(pts, dtype=np.float32).reshape(-1, 2)


class ScreenMapper:
    """frame → couleurs LED (float 0-1), avec lissage spatial et temporel."""

    def __init__(self):
        self._key = None
        self._boxes = None
        self._prev: np.ndarray | None = None

    def _build(self, w: int, h: int, depth_px: int, led_sides: dict, native_w: int):
        d = max(1, int(depth_px * w / max(1, native_w)))
        d = min(d, h // 2, w // 2)
        pos = led_layout(led_sides)
        n = len(pos)
        counts = led_sides
        boxes = np.zeros((n, 4), dtype=np.int64)  # y1, y2, x1, x2
        # Taille de zone le long de chaque côté
        horiz = max(1, max(counts.get("bottom_left_count", 1), counts.get("top_count", 1)))
        vert = max(1, max(counts.get("right_count", 1), counts.get("left_count", 1)))
        half_w = max(1, int(w / horiz / 2) + 1)
        half_h = max(1, int(h / vert / 2) + 1)
        for i, (x, y) in enumerate(pos):
            cx, cy = x * w, y * h
            if y in (0.0, 1.0) and 0.0 < x < 1.0:  # bas / haut
                y1, y2 = (h - d, h) if y == 1.0 else (0, d)
                x1, x2 = cx - half_w, cx + half_w
            else:  # gauche / droite
                x1, x2 = (w - d, w) if x == 1.0 else (0, d)
                y1, y2 = cy - half_h, cy + half_h
            boxes[i] = (max(0, int(y1)), min(h, max(int(y1) + 1, int(y2))),
                        max(0, int(x1)), min(w, max(int(x1) + 1, int(x2))))
        self._boxes = boxes
        self._prev = None

    def map(self, frame: np.ndarray, hw: dict, smoothing: float, native_w: int = 1920) -> np.ndarray:
        h, w = frame.shape[:2]
        key = (w, h, native_w, hw["border_depth_px"], tuple(sorted(hw["led_sides"].items())))
        if key != self._key:
            self._build(w, h, hw["border_depth_px"], hw["led_sides"], native_w)
            self._key = key

        # Image intégrale → moyenne de chaque zone en une opération
        ii = np.zeros((h + 1, w + 1, 3), dtype=np.float64)
        ii[1:, 1:] = frame.astype(np.float64).cumsum(0).cumsum(1)
        y1, y2, x1, x2 = self._boxes.T
        sums = ii[y2, x2] - ii[y1, x2] - ii[y2, x1] + ii[y1, x1]
        area = ((y2 - y1) * (x2 - x1)).clip(min=1)[:, None]
        colors = (sums / area / 255.0).astype(np.float32)

        # Lissage spatial (voisins sur le ruban, circulaire)
        if len(colors) >= 5:
            k = np.array([0.35, 0.6, 1.0, 0.6, 0.35], dtype=np.float32)
            k /= k.sum()
            padded = np.concatenate([colors[-2:], colors, colors[:2]])
            colors = sum(padded[i:i + len(colors)] * k[i] for i in range(5))

        # Saturation (écart à la luminance)
        sat = hw["saturation"]
        if sat != 1.0:
            luma = (colors @ np.array([0.299, 0.587, 0.114], dtype=np.float32))[:, None]
            colors = np.clip(luma + (colors - luma) * sat, 0, 1)

        # Lissage temporel adaptatif : petits écarts lissés fort (anti
        # scintillement), gros changements de scène quasi instantanés.
        if self._prev is None or self._prev.shape != colors.shape:
            self._prev = colors
        else:
            diff = np.linalg.norm(colors - self._prev, axis=1, keepdims=True) / 1.732
            base = 1.0 - smoothing * 0.95
            alpha = np.clip(base * (0.2 + 0.8 * diff ** 0.5) + (1 - smoothing) * 0.05, 0.02, 1.0)
            self._prev = self._prev + (colors - self._prev) * alpha
        return self._prev
