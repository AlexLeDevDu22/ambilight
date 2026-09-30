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


class LetterboxDetector:
    """Bandes noires de film (haut/bas) ou de vidéo 4:3 (gauche/droite).

    On ne recadre que si on est sûr que c'est une vidéo :
      • lignes/colonnes quasi parfaitement noires sur toute leur longueur
        (une interface sombre a du texte → pas prise pour une bande) ;
      • bandes symétriques et d'au moins 5 % de l'écran ;
      • image plus large que l'écran (film) ou plus étroite (4:3) ;
      • du contenu visible au milieu (une scène qui fond au noir ne compte pas) ;
      • situation stable ~1,5 s avant d'appliquer (0,6 s pour relâcher).
    """

    BLACK = 14      # luminance max (0-255) d'une ligne de bande noire
    APPLY_AFTER = 1.5
    RELEASE_AFTER = 0.6

    def __init__(self):
        self.crop = (0, 0, 0, 0)          # haut, bas, gauche, droite (pixels)
        self._cand = self.crop
        self._cand_since = 0.0

    @staticmethod
    def _run_length(mask: np.ndarray) -> int:
        """Nombre d'éléments True consécutifs au début."""
        idx = np.flatnonzero(~mask)
        return int(idx[0]) if idx.size else len(mask)

    def _detect(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        luma = frame[:, :, 0] * 0.3 + frame[:, :, 1] * 0.59 + frame[:, :, 2] * 0.11
        rows = luma.max(axis=1) < self.BLACK
        cols = luma.max(axis=0) < self.BLACK
        top, bottom = self._run_length(rows), self._run_length(rows[::-1])
        left, right = self._run_length(cols), self._run_length(cols[::-1])
        if top + bottom >= h - 4 or left + right >= w - 4:
            return None  # écran (presque) tout noir : on ne décide rien

        screen_ar = w / h
        # Letterbox (film plus large que l'écran)
        if not (top >= 0.05 * h and bottom >= 0.05 * h and abs(top - bottom) <= 0.03 * h + 1
                and w / (h - top - bottom) > screen_ar + 0.08):
            top = bottom = 0
        # Pillarbox (vidéo plus étroite que l'écran)
        if not (left >= 0.05 * w and right >= 0.05 * w and abs(left - right) <= 0.03 * w + 1
                and (w - left - right) / (h - top - bottom) < screen_ar - 0.1):
            left = right = 0
        center = luma[top:h - bottom, left:w - right]
        if center.size == 0 or center.mean() < 10:
            return None  # scène sombre : on garde l'état actuel
        return (top, bottom, left, right)

    def update(self, frame: np.ndarray, now: float) -> tuple[int, int, int, int]:
        cand = self._detect(frame)
        if cand is None:
            return self.crop
        close = all(abs(a - b) <= 2 for a, b in zip(cand, self._cand))
        if not close:
            self._cand, self._cand_since = cand, now
        elif cand != self.crop:
            grows = sum(cand) > sum(self.crop)
            wait = self.APPLY_AFTER if grows else self.RELEASE_AFTER
            if now - self._cand_since >= wait:
                self.crop = self._cand
        return self.crop

    def aspect(self, frame_shape) -> str:
        h, w = frame_shape[:2]
        t, b, l, r = self.crop
        if not any(self.crop):
            return ""
        return f"{(w - l - r) / max(1, h - t - b):.2f}:1"


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
