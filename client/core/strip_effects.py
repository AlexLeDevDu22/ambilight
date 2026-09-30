"""
strip_effects.py – Effets générés pour le ruban LED (son + ambiance).

Tous les effets travaillent en numpy sur la géométrie réelle du ruban
(position de chaque LED autour de l'écran) et renvoient des couleurs
float (n, 3) dans [0, 1].
"""

import numpy as np

from .palette import Palette


class StripGeometry:
    def __init__(self, pos: np.ndarray):
        self.pos = pos
        self.n = len(pos)
        # Abscisse le long du ruban (0 → 1), pour les dégradés qui tournent
        self.t = (np.arange(self.n, dtype=np.float32) + 0.5) / max(1, self.n)
        # Distance au centre bas de l'écran le long du cadre (0 = bas centre,
        # 1 = haut centre) : les basses « montent » de là, comme un caisson.
        x, y = pos[:, 0], pos[:, 1]
        per = np.where(y >= 0.999, np.abs(x - 0.5),                       # bas
              np.where(y <= 0.001, 0.5 + 1.0 + (0.5 - np.abs(x - 0.5)),     # haut
                       0.5 + (1.0 - y)))                                   # côtés
        self.rise = (per / 2.0).astype(np.float32)  # 0..1
        self.side = np.where(x < 0.5, -1.0, 1.0).astype(np.float32)


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


class SoundEffect:
    """Effets audio. Etat interne : vagues, étincelles, flash."""

    def __init__(self):
        self.phase = 0.0
        self.waves: list[dict] = []
        self.sparks: np.ndarray | None = None
        self.flash = 0.0
        self.flash_color = np.ones(3, dtype=np.float32)
        self._beat = None
        self._snare = None
        self._color_i = 0
        self._rng = np.random.default_rng()
        self._spec_smooth = None

    def _new_beats(self, a: dict):
        beat = snare = False
        if self._beat is not None and a["beat_count"] != self._beat:
            beat = True
        if self._snare is not None and a["snare_count"] != self._snare:
            snare = True
        self._beat, self._snare = a["beat_count"], a["snare_count"]
        return beat, snare

    def render(self, effect: str, g: StripGeometry, pal: Palette, a: dict, sens: float, dt: float) -> np.ndarray:
        if self.sparks is None or len(self.sparks) != g.n:
            self.sparks = np.zeros(g.n, dtype=np.float32)
        bass = min(1.0, a["bass"] * sens)
        mid = min(1.0, a["mid"] * sens)
        high = min(1.0, a["high"] * sens)
        energy = min(1.0, a["energy"] * sens * 1.6)
        beat, snare = self._new_beats(a)
        strength = min(1.0, a["beat_strength"] * sens)

        self.phase = (self.phase + dt * (0.015 + 0.12 * energy + 0.25 * bass ** 3)) % 1.0
        if effect != getattr(self, "_effect", None):
            # Chaque effet a ses propres vagues (Pulse ≠ Ondes)
            self._effect = effect
            self.waves = []
        if effect == "spectrum":
            return self._spectrum(g, pal, a, sens, bass, dt)
        if effect == "strobe":
            return self._strobe(g, pal, mid, beat, strength, dt)
        if effect == "ripples":
            return self._ripples(g, pal, bass, mid, high, beat, snare, strength, dt)
        return self._pulse(g, pal, bass, mid, high, energy, beat, snare, strength, dt)

    # ---- « Pulse » : l'effet enceinte (défaut) -----------------------------
    def _pulse(self, g, pal, bass, mid, high, energy, beat, snare, strength, dt):
        # Dégradé de palette qui tourne doucement autour de l'écran
        base = pal.sample(g.t + self.phase)
        # Les basses gonflent depuis le bas (comme la membrane d'un caisson)
        reach = 0.1 + 1.0 * bass ** 1.2
        bloom = 1.0 - _smoothstep(reach * 0.55, reach, g.rise)
        level = 0.03 + 0.4 * mid ** 1.2 + 0.9 * bloom * bass ** 0.8

        if beat:
            self._color_i += 1
            self.waves.append({"r": 0.0, "life": 1.0, "c": pal.color(self._color_i), "s": 0.8 + strength})
            if strength > 0.75:
                self.flash = max(self.flash, (strength - 0.6) * 1.6)
                self.flash_color = pal.color(self._color_i + 2)
        out = base * level[:, None]

        # Ondes de choc qui montent des deux côtés à chaque kick
        alive = []
        for w in self.waves:
            w["r"] += dt * (0.9 + 0.6 * w["s"])
            w["life"] -= dt * 1.4
            if w["life"] <= 0 or w["r"] > 1.3:
                continue
            band = np.exp(-((g.rise - w["r"]) / 0.07) ** 2) * w["life"] * w["s"] * 0.8
            out = out + band[:, None] * w["c"]
            alive.append(w)
        self.waves = alive[-8:]

        # Étincelles sur les aigus (snare / hi-hat)
        self.sparks *= np.exp(-dt * 9)
        if snare:
            k = max(1, int(g.n * (0.03 + 0.08 * high)))
            idx = self._rng.choice(g.n, size=k, replace=False)
            self.sparks[idx] = 0.7 + 0.3 * high
        spark_col = pal.sample(g.t * 3 + self.phase + 0.5) * 0.6 + 0.4
        out = out + self.sparks[:, None] * spark_col

        # Flash « explosion » sur les très gros kicks
        if self.flash > 0.01:
            out = out * (1 + self.flash) + self.flash_color * self.flash * 0.5
            self.flash *= np.exp(-dt * 7)
        return out

    # ---- « Ondes » : vagues nées au hasard sur les kicks --------------------
    def _ripples(self, g, pal, bass, mid, high, beat, snare, strength, dt):
        base = pal.sample(g.t * 0.5 + self.phase)
        out = base * (0.04 + 0.22 * mid + 0.15 * bass)
        if beat:
            self._color_i += 1
            center = float(self._rng.random())
            self.waves.append({"x": center, "r": 0.0, "life": 1.0, "c": pal.color(self._color_i), "s": 0.6 + strength})
        if snare and high > 0.5:
            self.waves.append({"x": float(self._rng.random()), "r": 0.0, "life": 0.5, "c": pal.color(self._color_i + 1) * 0.6 + 0.4, "s": 0.5})
        alive = []
        for w in self.waves:
            w["r"] += dt * 0.45 * w["s"]
            w["life"] -= dt * 0.9
            if w["life"] <= 0:
                continue
            d = np.abs(g.t - w["x"])
            d = np.minimum(d, 1 - d)
            band = np.exp(-((d - w["r"]) / 0.025) ** 2) * w["life"] + np.exp(-(d / 0.02) ** 2) * w["life"] ** 3
            out = out + band[:, None] * w["c"] * w["s"]
            alive.append(w)
        self.waves = alive[-14:]
        return out

    # ---- « Strobe » : flashs francs sur les kicks ----------------------------
    # Au plus 4 flashs par seconde (confort visuel). Gros kick → tout le
    # ruban flashe avec un cœur blanc ; kick plus léger → une moitié, en
    # alternant gauche / droite.
    def _strobe(self, g, pal, mid, beat, strength, dt):
        self._since_flash = getattr(self, "_since_flash", 1.0) + dt
        if beat and self._since_flash >= 0.25:
            self._since_flash = 0.0
            self._color_i += 1
            self._strobe_col = pal.color(self._color_i)
            self._strobe_lvl = min(1.0, 0.55 + 0.6 * strength)
            self._strobe_white = max(0.0, (strength - 0.7) / 0.3)
            if strength > 0.7:
                self._strobe_side = 0.0
            else:  # alterne gauche / droite
                self._strobe_flip = -getattr(self, "_strobe_flip", -1.0)
                self._strobe_side = self._strobe_flip
        out = pal.sample(g.t * 0.5 + self.phase) * (0.02 + 0.1 * mid)
        lvl = getattr(self, "_strobe_lvl", 0.0)
        if lvl > 0.01:
            col = self._strobe_col * (1 - 0.6 * self._strobe_white) + 0.6 * self._strobe_white
            mask = 1.0 if self._strobe_side == 0.0 else (g.side == self._strobe_side).astype(np.float32)[:, None]
            out = out + col * lvl * mask
            self._strobe_lvl = lvl * np.exp(-dt * 14)  # extinction rapide (~70 ms)
        return out

    # ---- « Spectre » : égaliseur en miroir (graves en bas, aigus en haut) ---
    def _spectrum(self, g, pal, a, sens, bass, dt):
        spec = np.clip(a["spectrum"] * sens, 0, 1)
        if self._spec_smooth is None or len(self._spec_smooth) != len(spec):
            self._spec_smooth = spec
        self._spec_smooth = np.maximum(spec, self._spec_smooth * np.exp(-dt * 6))
        bands = len(spec)
        x = g.rise * (bands - 1)
        lvl = np.interp(x, np.arange(bands), self._spec_smooth)
        col = pal.sample(g.rise * 0.9 + self.phase * 0.3, cyclic=False)
        return col * (0.03 + lvl ** 1.6 * 1.1)[:, None]


class AmbientEffect:
    """Modes d'ambiance calmes (pas d'audio)."""

    def __init__(self):
        self.time = 0.0

    def render(self, effect: str, g: StripGeometry, pal: Palette, speed: float, dt: float) -> np.ndarray:
        rate = 0.15 + speed * 1.7
        self.time += dt * rate
        t = self.time
        if effect == "rainbow":
            h6 = ((g.t + t * 0.06) % 1.0)[:, None] * 6 - np.array([3, 2, 4], dtype=np.float32)
            rgb = np.clip(np.abs(h6) * np.array([1, -1, -1]) + np.array([-1, 2, 2]), 0, 1)
            return 0.05 + 0.95 * rgb
        if effect == "flow":
            return pal.sample(g.t + t * 0.04)
        if effect == "breathe":
            breath = 0.5 - 0.5 * np.cos(t * 0.9)
            col = pal.sample(g.t * 0.5 + t * 0.02)
            return col * (0.18 + 0.82 * breath ** 1.3)
        # aurora : rideaux de couleur qui ondulent lentement
        x = g.t * 2 * np.pi
        n1 = np.sin(x * 2 + t * 0.35) + np.sin(x * 3.1 - t * 0.23) * 0.6
        n2 = np.sin(x * 1.3 - t * 0.17 + 1.7) + np.sin(x * 4.3 + t * 0.29) * 0.4
        col = pal.sample(g.t * 0.6 + n1 * 0.12 + t * 0.01)
        glow = 0.25 + 0.75 * (0.5 + 0.5 * n2 / 1.4) ** 1.5
        return col * glow[:, None]


def color_mode(g: StripGeometry, colors_hex: list[str]) -> np.ndarray:
    from .palette import hex_to_rgb
    c1 = np.array(hex_to_rgb(colors_hex[0]), dtype=np.float32)
    c2 = np.array(hex_to_rgb(colors_hex[1]), dtype=np.float32)
    # c1 en bas, c2 en haut, dégradé doux sur les côtés
    f = _smoothstep(0.0, 1.0, g.rise)[:, None]
    return c1 * (1 - f) + c2 * f


class WipeTransition:
    """Transition entre deux looks : le nouveau monte du bas vers le haut des
    deux côtés à la fois, avec un liseré de LEDs blanches sur le front."""

    DURATION = 0.55

    def __init__(self):
        self.prev: np.ndarray | None = None
        self.t0: float | None = None
        self.last: np.ndarray | None = None  # dernière image affichée

    def trigger(self, n: int):
        # Départ depuis ce qui est affiché (noir au démarrage)
        self.prev = self.last.copy() if self.last is not None and len(self.last) == n else np.zeros((n, 3), np.float32)
        self.t0 = None

    def apply(self, colors: np.ndarray, g: StripGeometry, now: float) -> np.ndarray:
        if self.prev is not None and len(self.prev) == len(colors):
            if self.t0 is None:
                self.t0 = now  # démarre à la 1re image du nouveau look
            p = (now - self.t0) / self.DURATION
            if p >= 1.0:
                self.prev = None
            else:
                p = p * p * (3 - 2 * p)
                front = -0.08 + 1.2 * p
                mix = _smoothstep(front + 0.03, front - 0.03, g.rise)[:, None]  # 1 sous le front
                out = colors * mix + self.prev * (1 - mix)
                white = np.exp(-((g.rise - front) / 0.05) ** 2) * (1.0 - 0.4 * p)
                colors = np.clip(out + white[:, None], 0, 1)
        self.last = colors
        return colors


OUTRO_DURATION = 0.55


def outro_frame(last: np.ndarray, g: StripGeometry, p: float) -> np.ndarray:
    """Extinction : une lumière blanche descend du haut vers le bas des deux
    côtés et laisse le noir derrière elle (sens inverse de l'allumage)."""
    p = p * p * (3 - 2 * p)
    front = 1.08 - 1.16 * p                                     # haut → bas
    keep = _smoothstep(front + 0.03, front - 0.03, g.rise)[:, None]   # 1 sous le front
    white = np.exp(-((g.rise - front) / 0.05) ** 2) * (1.0 - 0.35 * p)
    return np.clip(last * keep + white[:, None], 0, 1)
