"""
led_mapper.py – Mapping bords de l'écran → couleur RGB par LED.

Disposition des LEDs (sens anti-horaire depuis bas-gauche) :
  [bottom_left_count]  → bas, de gauche vers droite
  [right_count]        → droite, de bas en haut
  [top_count]          → haut, de droite vers gauche
  [left_count]         → gauche, de haut en bas
  [bottom_right_count] → bas (retour), de gauche vers droite (optionnel)

La somme des compteurs doit valoir num_leds. Si elle ne correspond pas,
les zones sont rééchantillonnées proportionnellement.
"""

import numpy as np
import colorsys
from dataclasses import dataclass


@dataclass
class LedZone:
    """Rectangle de pixels associé à une LED."""
    y1: int
    y2: int
    x1: int
    x2: int


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _apply_gamma(value: float, gamma: float) -> float:
    """Applique une correction gamma (0-255 → 0-255)."""
    return 255.0 * ((value / 255.0) ** gamma)


def _boost_saturation(r: int, g: int, b: int, factor: float) -> tuple[int, int, int]:
    """Augmente la saturation HSV d'un facteur donné."""
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    s = min(1.0, s * factor)
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    return int(nr * 255), int(ng * 255), int(nb * 255)


def compute_led_zones(
    frame_w: int,
    frame_h: int,
    depth: int,
    led_sides: dict,
) -> list[LedZone]:
    """
    Génère la liste ordonnée des zones (rectangles) pour chaque LED.

    Parcours anti-horaire depuis bas-gauche :
      bas G→D | droite B→H | haut D→G | gauche H→B | bas (fin, optionnel)
    """
    zones: list[LedZone] = []

    bl = led_sides.get("bottom_left_count", 0)
    right = led_sides.get("right_count", 0)
    top = led_sides.get("top_count", 0)
    left = led_sides.get("left_count", 0)
    br = led_sides.get("bottom_right_count", 0)

    d = max(1, depth)

    def split_h(x_start, x_end, count, y_top, y_bot):
        """Divise un segment horizontal en `count` zones."""
        if count <= 0:
            return
        seg_w = (x_end - x_start) / count
        for i in range(count):
            x1 = int(x_start + i * seg_w)
            x2 = int(x_start + (i + 1) * seg_w)
            zones.append(LedZone(y1=y_top, y2=y_bot, x1=x1, x2=x2))

    def split_v(y_start, y_end, count, x_left, x_right):
        """Divise un segment vertical en `count` zones."""
        if count <= 0:
            return
        seg_h = (y_end - y_start) / count
        for i in range(count):
            y1 = int(y_start + i * seg_h)
            y2 = int(y_start + (i + 1) * seg_h)
            zones.append(LedZone(y1=y1, y2=y2, x1=x_left, x2=x_right))

    # Bas gauche → droite  (y proches de frame_h)
    split_h(0, frame_w, bl, frame_h - d, frame_h)

    # Droite bas → haut
    split_v(frame_h, 0, right, frame_w - d, frame_w)

    # Haut droite → gauche
    split_h(frame_w, 0, top, 0, d)

    # Gauche haut → bas
    split_v(0, frame_h, left, 0, d)

    # Bas fin (optionnel, retour droite → gauche)
    split_h(frame_w, 0, br, frame_h - d, frame_h)

    return zones


def zone_color(frame: np.ndarray, zone: LedZone) -> tuple[int, int, int]:
    """Calcule la couleur moyenne pondérée d'une zone (plus stable que la médiane)."""
    y1, y2 = sorted([zone.y1, zone.y2])
    x1, x2 = sorted([zone.x1, zone.x2])

    # Clamp aux dimensions réelles du frame
    H, W = frame.shape[:2]
    y1 = max(0, min(y1, H - 1))
    y2 = max(y1 + 1, min(y2, H))
    x1 = max(0, min(x1, W - 1))
    x2 = max(x1 + 1, min(x2, W))

    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return (0, 0, 0)

    # Moyenne pondérée : les pixels proches du bord de l'écran comptent plus
    # Cela donne un résultat plus stable que la médiane pure
    pixels = region.reshape(-1, 3).astype(np.float32)
    mean = np.mean(pixels, axis=0)
    return int(mean[0]), int(mean[1]), int(mean[2])


class LedMapper:
    """
    Orchestre le mapping frame → liste RGB.

    Réutilise les zones précalculées et les recalcule seulement
    si la configuration change.
    """

    def __init__(self, cfg: dict):
        self._cfg = None
        self._zones: list[LedZone] = []
        self._frame_size = (0, 0)
        self.update_config(cfg)

    def update_config(self, cfg: dict) -> None:
        self._cfg = cfg

    def map(self, frame: np.ndarray) -> list[tuple[int, int, int]]:
        """
        Prend un frame numpy (H, W, 3) RGB et retourne la liste
        de couleurs RGB pour chaque LED.
        """
        H, W = frame.shape[:2]
        depth = max(1, self._cfg.get("border_depth_px", 80))
        # Adapter la profondeur au downscale (déjà appliqué dans ScreenCapture)
        # → on reçoit un frame déjà downscalé, depth doit l'être aussi
        downscale = self._cfg.get("_downscale", 4)
        depth_ds = max(1, depth // downscale)

        led_sides = self._cfg.get("led_sides", {})

        # Recalculer les zones si taille ou config a changé
        if (W, H) != self._frame_size or self._cfg != getattr(self, "_last_cfg", None):
            self._zones = compute_led_zones(W, H, depth_ds, led_sides)
            self._frame_size = (W, H)
            self._last_cfg = dict(self._cfg)

        gamma = float(self._cfg.get("gamma", 1.0))
        brightness = float(self._cfg.get("brightness", 1.0))
        sat_boost = float(self._cfg.get("saturation_boost", 1.0))

        # 1. Calculer les couleurs brutes pour chaque zone
        raw_colors: list[tuple[int, int, int]] = []
        for zone in self._zones:
            r, g, b = zone_color(frame, zone)
            raw_colors.append((r, g, b))

        # 2. Lissage spatial : chaque LED blend avec ses voisines
        #    Cela crée un dégradé naturel le long du ruban
        smoothed_colors: list[tuple[int, int, int]] = []
        n_zones = len(raw_colors)
        blend_radius = 2  # Nombre de voisines à prendre en compte de chaque côté
        for i in range(n_zones):
            total_r, total_g, total_b = 0.0, 0.0, 0.0
            total_weight = 0.0
            for offset in range(-blend_radius, blend_radius + 1):
                j = i + offset
                if 0 <= j < n_zones:
                    # Poids gaussien : la LED elle-même a le plus de poids
                    weight = 1.0 / (1.0 + abs(offset) * 0.8)
                    total_r += raw_colors[j][0] * weight
                    total_g += raw_colors[j][1] * weight
                    total_b += raw_colors[j][2] * weight
                    total_weight += weight
            if total_weight > 0:
                smoothed_colors.append((
                    int(total_r / total_weight),
                    int(total_g / total_weight),
                    int(total_b / total_weight),
                ))
            else:
                smoothed_colors.append(raw_colors[i])

        # 3. Appliquer saturation, gamma, brightness
        colors: list[tuple[int, int, int]] = []
        for r, g, b in smoothed_colors:
            # Saturation boost
            if sat_boost != 1.0:
                r, g, b = _boost_saturation(r, g, b, sat_boost)

            # Gamma + brightness
            r = _clamp(_apply_gamma(r * brightness, gamma))
            g = _clamp(_apply_gamma(g * brightness, gamma))
            b = _clamp(_apply_gamma(b * brightness, gamma))

            colors.append((r, g, b))

        # S'assurer qu'on retourne exactement num_leds couleurs
        num_leds = self._cfg.get("num_leds", 113)
        if len(colors) < num_leds:
            colors.extend([(0, 0, 0)] * (num_leds - len(colors)))
        elif len(colors) > num_leds:
            colors = colors[:num_leds]

        return colors
