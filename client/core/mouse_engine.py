"""
mouse_engine.py – Modes lumineux de la souris Cougar Revenger ST.

Les trois zones (contour sur les côtés et l'arrière, molette, logo) sont
pilotées image par image en mode Direct : dégradés et va-et-vient de lumière
parfaitement fluides. L'effet matériel Flow (couleurs qui tournent) ne sert
plus que pour la réaction aux clics, en rafale courte.

Modes : son · flow · respiration · aurore · couleur
Réactif (option) : clic gauche → le contour tourne dans un sens, clic droit
dans l'autre, molette haut/bas pareil, clic milieu → tout pulse ; logo et
molette flashent aussi.
"""

import math
import threading
import time

import numpy as np

from .palette import Palette, hex_to_rgb, rgb_to_hex
from .mouse_device import FLOW_SLOTS

FPS = 40


def ring_gradient(pal: Palette) -> np.ndarray:
    """7 couleurs pour l'effet Flow (rafale de clic) : la palette en aller-
    retour, sans raccord artificiel entre la dernière et la première couleur."""
    i = np.arange(FLOW_SLOTS, dtype=np.float32)
    tri = 1.0 - np.abs(2.0 * i / FLOW_SLOTS - 1.0)
    return pal.sample(tri, cyclic=False)


def pingpong(x: float) -> float:
    """0 → 1 → 0 avec des demi-tours en douceur (pas de saut de couleur)."""
    return 0.5 - 0.5 * math.cos(math.pi * x)


def _ease(cur: float, target: float, rate: float, dt: float) -> float:
    return cur + (target - cur) * (1.0 - math.exp(-rate * dt))


def _color_dist(a, b) -> int:
    return max(abs(x - y) for ca, cb in zip(a, b) for x, y in zip(ca, cb))


def _to8(c) -> tuple[int, int, int]:
    c = np.clip(np.asarray(c, dtype=np.float32), 0, 1)
    return tuple(int(x * 255 + 0.5) for x in c)


class MouseEngine:
    def __init__(self, store, device, audio, palettes, inputs):
        self._store = store
        self._dev = device
        self._audio = audio
        self._palettes = palettes
        self._inputs = inputs
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.running = False
        self.status = "arrêtée"
        self.preview = {"ring": {"type": "direct", "color": "#000000"}, "wheel": "#000000", "logo": "#000000"}

    # ------------------------------------------------------------------

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.running = True
            self.status = "démarrage…"
            self._thread = threading.Thread(target=self._run, name="mouse", daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop.set()
            t = self._thread
            self._thread = None
        if t:
            t.join(timeout=2.0)
        if self._dev.connected:
            self._dev.all_off()
        self.running = False
        self.status = "arrêtée"
        self.preview = {"ring": {"type": "direct", "color": "#000000"}, "wheel": "#000000", "logo": "#000000"}

    # ------------------------------------------------------------------

    def _run(self):
        st = _State()
        audio_on = False
        last = time.perf_counter()
        last_connect_try = 0.0
        last_audio_check = 0.0
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                dt = min(0.1, now - last)
                last = now
                try:
                    cfg = self._store.get()["mouse"]
                    mode = cfg["mode"]

                    if (mode == "sound") != audio_on:
                        (self._audio.acquire if not audio_on else self._audio.release)()
                        audio_on = not audio_on
                    self._inputs.set_enabled(cfg["responsive"])

                    if not self._dev.connected:
                        if now - last_connect_try > 1.0:
                            last_connect_try = now
                            self._dev.open()
                        if not self._dev.connected:
                            self.status = self._dev.status
                            self._inputs.drain()
                            self._stop.wait(0.2)
                            continue

                    if audio_on and now - last_audio_check > 1.0:
                        self._audio.ensure()
                        last_audio_check = now

                    pal = self._palettes.get(cfg["palette"])
                    events = self._inputs.drain() if cfg["responsive"] else []
                    frame = self._render(st, mode, cfg, pal, events, now, dt)
                    frame = st.wipe.apply(frame, cfg, now)
                    self._output(st, frame, cfg["brightness"])

                    if cfg["responsive"] and not self._inputs.active and self._inputs.status != "inactif":
                        self.status = f"{self._dev.status} · réactif : {self._inputs.status}"
                    elif mode == "sound":
                        self.status = f"{self._dev.status} · {self._audio.status}"
                    else:
                        self.status = self._dev.status
                except Exception as e:
                    print(f"[mouse] {e.__class__.__name__}: {e}")
                    self.status = f"erreur : {e}"
                    self._stop.wait(1.0)

                spare = 1.0 / FPS - (time.perf_counter() - now)
                if spare > 0:
                    self._stop.wait(spare)
        finally:
            if audio_on:
                self._audio.release()

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def _render(self, st: "_State", mode: str, cfg: dict, pal: Palette, events, now: float, dt: float) -> dict:
        st.t += dt
        t = st.t
        speed = cfg["speed"]
        black = np.zeros(3, dtype=np.float32)
        ring = None
        wheel = logo = black

        if mode == "sound":
            a = self._audio.snapshot()
            sens = cfg["sensitivity"]
            bass = min(1.0, a["bass"] * sens)
            energy = min(1.0, a["energy"] * sens * 1.6)
            # Kick → logo explose ; snare → molette claque
            if st.beat is not None and a["beat_count"] != st.beat:
                strength = min(1.0, a["beat_strength"] * sens)
                st.logo_env = max(st.logo_env, strength)
                st.beat_i += 1
                st.glide_target += 0.05 + 0.1 * strength  # le dégradé avance sur le kick
            if st.snare is not None and a["snare_count"] != st.snare:
                st.wheel_env = max(st.wheel_env, min(1.0, a["snare_strength"] * sens))
                st.snare_i += 1
            st.beat, st.snare = a["beat_count"], a["snare_count"]
            st.logo_env *= math.exp(-dt * 5.5)
            st.wheel_env *= math.exp(-dt * 7.0)

            logo_c = pal.color(st.beat_i)
            wheel_c = pal.color(st.snare_i + 2)
            logo = logo_c * (0.1 + 0.9 * st.logo_env) + max(0.0, st.logo_env - 0.8) * 1.5  # blanc au sommet
            wheel = wheel_c * (0.1 + 0.9 * max(st.wheel_env, bass * 0.55))

            # Contour : la lumière monte et redescend avec les basses (va-et-
            # vient), la couleur glisse le long du dégradé de la palette.
            st.glide_target += dt * (0.015 + 0.08 * energy)
            st.glide = _ease(st.glide, st.glide_target, 3.0, dt)
            punch = min(1.0, bass * 1.3)
            st.ring_env = _ease(st.ring_env, punch, 16.0 if punch > st.ring_env else 2.4, dt)
            idle = 0.07 * (0.6 + 0.4 * math.sin(t * 1.3))
            silent = energy <= 0.03
            if cfg["sound_effect"] == "spin":
                # Rotation : dégradé multicolore qui tourne autour de la souris
                # (effet matériel Flow). Chaque relance de l'effet fait scintiller
                # quelques LEDs (firmware) : on le relance donc le moins possible.
                #  - vitesse : 3 paliers, tenus ≥ 2 s, au plus un changement / 6 s
                #  - sens : inversé seulement sur un vrai « drop »
                #  - couleurs : figées tant que le morceau ne change pas
                st.energy_s = _ease(st.energy_s, energy, 0.6, dt)
                e = st.energy_s
                tier = 13 if e < 0.08 else (8 if e < 0.55 else 4)
                if tier != st.spin_want:
                    st.spin_want, st.spin_want_t = tier, now
                if (st.spin_want != st.spin_speed and now - st.spin_want_t > 2.0
                        and now - st.spin_changed > 6.0):
                    st.spin_speed, st.spin_changed = st.spin_want, now
                if e < 0.2:
                    st.calm_since = st.calm_since or now
                elif e > 0.5:
                    if st.calm_since and now - st.calm_since > 3.0 and now - st.spin_changed > 6.0:
                        st.spin_cw = not st.spin_cw
                        st.spin_changed = now
                    st.calm_since = 0.0
                ring = ("flow", ring_gradient(pal), st.spin_speed, st.spin_cw)
            else:
                # Pulse : la lumière monte et redescend avec les basses
                level = idle if silent else max(idle, 0.16 + 0.84 * st.ring_env)
                ring = ("direct", pal.sample(pingpong(st.glide), cyclic=False) * level)

        elif mode == "flow":
            # Vague de couleur qui voyage de l'avant (molette) vers l'arrière
            # (contour puis logo), avec une lumière qui va et vient.
            p = t * (0.02 + speed * 0.09)
            rate = 0.35 + speed * 1.3
            lum = lambda lag: 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * rate - lag)) ** 1.5
            wheel = pal.sample(pingpong(p), cyclic=False) * lum(0.0)
            ring = ("direct", pal.sample(pingpong(p - 0.12), cyclic=False) * lum(0.9))
            logo = pal.sample(pingpong(p - 0.24), cyclic=False) * lum(1.8)

        elif mode == "breathe":
            rate = 0.5 + speed * 1.6
            drift = t * (0.015 + speed * 0.04)
            b = lambda ph: 0.12 + 0.88 * (0.5 - 0.5 * math.cos(t * rate + ph)) ** 1.4
            ring = ("direct", pal.sample(drift) * b(0.0))
            wheel = pal.sample(drift + 0.35) * b(1.2)
            logo = pal.sample(drift + 0.7) * b(0.0)

        elif mode == "aurora":
            s = 0.3 + speed * 1.4
            n = lambda f, ph: math.sin(t * s * f + ph) * 0.5 + math.sin(t * s * f * 1.7 + ph * 2) * 0.3
            ring = ("direct", pal.sample(t * 0.01 * s + n(0.21, 0) * 0.25) * (0.55 + 0.45 * (0.5 + 0.5 * n(0.37, 1))))
            wheel = pal.sample(0.33 + n(0.29, 2) * 0.3) * (0.4 + 0.6 * (0.5 + 0.5 * n(0.5, 3)))
            logo = pal.sample(0.66 + n(0.17, 4) * 0.3) * (0.5 + 0.5 * (0.5 + 0.5 * n(0.41, 5)))

        else:  # couleur perso
            c = cfg["colors"]
            ring = ("direct", np.array(hex_to_rgb(c["ring"]), dtype=np.float32))
            wheel = np.array(hex_to_rgb(c["wheel"]), dtype=np.float32)
            logo = np.array(hex_to_rgb(c["logo"]), dtype=np.float32)

        # ---- Réactif : clics & molette --------------------------------
        for kind, val in events:
            if kind == "left":
                st.react(now, cw=False, dur=0.6)
                st.flash("logo", pal.color(st.beat_i + 1), 1.0)
            elif kind == "right":
                st.react(now, cw=True, dur=0.6)
                st.flash("logo", pal.color(st.beat_i + 3), 1.0)
            elif kind == "middle":
                st.react(now, cw=True, dur=0.9, speed=0)
                st.flash("logo", np.ones(3, dtype=np.float32), 1.0)
                st.flash("wheel", np.ones(3, dtype=np.float32), 1.0)
            elif kind == "scroll":
                up = val > 0
                st.react(now, cw=not up, dur=0.45)
                st.flash("wheel", pal.color(0 if up else 2), min(1.0, st.flash_env["wheel"] + 0.45))
        for zone in ("wheel", "logo"):
            st.flash_env[zone] *= math.exp(-dt * 6.0)
        if st.flash_env["wheel"] > 0.01:
            wheel = np.maximum(wheel, st.flash_col["wheel"] * st.flash_env["wheel"])
        if st.flash_env["logo"] > 0.01:
            logo = np.maximum(logo, st.flash_col["logo"] * st.flash_env["logo"])
        if now < st.react_until:
            # Rotation rapide pleine palette dans le sens du clic
            ring = ("flow", ring_gradient(pal), st.react_speed, st.react_cw)

        return {"ring": ring, "wheel": wheel, "logo": logo}

    def _output(self, st: "_State", f: dict, brightness: float):
        ring = f["ring"]
        now = time.perf_counter()
        if ring[0] == "flow":
            _, cols, spd, cw = ring
            # Luminosité appliquée aux couleurs (registres de luminosité de
            # l'effet laissés à 255 : les faire varier crée des artefacts).
            c8 = [_to8(c * brightness) for c in cols]
            motion = (spd, cw)
            # Un changement de couleurs seul (morceau suivant, luminosité…) ne
            # relance l'effet que s'il est net, et au plus toutes les 4 s ;
            # vitesse / sens (déjà rares) s'appliquent tout de suite.
            if st.flow_cols is None or motion != st.flow_motion or not self._dev.flow_active():
                st.flow_cols, st.flow_motion, st.flow_t = c8, motion, now
            elif now - st.flow_t > 4.0 and _color_dist(c8, st.flow_cols) > 40:
                st.flow_cols, st.flow_t = c8, now
            self._dev.set_ring_flow(st.flow_cols, spd, cw, 255)
            ring_prev = {"type": "flow", "colors": ["#%02x%02x%02x" % c for c in st.flow_cols], "speed": spd, "cw": cw}
        else:
            st.flow_motion = None
            col = np.clip(ring[1], 0, 1) * brightness
            self._dev.set_direct(0, _to8(col))
            ring_prev = {"type": "direct", "color": rgb_to_hex(col)}
        wheel = np.clip(f["wheel"], 0, 1) * brightness
        logo = np.clip(f["logo"], 0, 1) * brightness
        self._dev.set_direct(1, _to8(wheel))
        self._dev.set_direct(2, _to8(logo))
        self.preview = {"ring": ring_prev, "wheel": rgb_to_hex(wheel), "logo": rgb_to_hex(logo)}


class MouseWipe:
    """Transition de look : un flash blanc balaie la souris de l'avant vers
    l'arrière (molette → contour → logo) et laisse le nouveau look derrière lui."""

    DURATION = 0.6
    # Position de chaque zone de l'avant (0) vers l'arrière (1)
    POS = {"wheel": 0.1, "ring": 0.45, "logo": 0.8}

    def __init__(self):
        self.look = None
        self.t_trigger = -10.0
        self.t0: float | None = None
        self.prev: dict | None = None
        self.last = {"ring": np.zeros(3, np.float32), "wheel": np.zeros(3, np.float32), "logo": np.zeros(3, np.float32)}

    @staticmethod
    def _ring_rgb(ring) -> np.ndarray:
        if ring[0] == "flow":
            return np.asarray(ring[1], dtype=np.float32).mean(axis=0)
        return np.asarray(ring[1], dtype=np.float32)

    def apply(self, frame: dict, cfg: dict, now: float) -> dict:
        c = cfg["colors"]
        look = (cfg["mode"], cfg["sound_effect"], cfg["palette"], c["ring"], c["wheel"], c["logo"])
        if look != self.look:
            only_colors = self.look is not None and look[:3] == self.look[:3]
            # Glisser un sélecteur de couleur ne relance pas le flash en boucle
            if not (only_colors and now - self.t_trigger < 0.8):
                self.prev = {k: v.copy() for k, v in self.last.items()}
                self.t0 = None
                self.t_trigger = now
            self.look = look

        cur = {"ring": self._ring_rgb(frame["ring"]), "wheel": np.asarray(frame["wheel"], np.float32),
               "logo": np.asarray(frame["logo"], np.float32)}
        if self.prev is not None:
            if self.t0 is None:
                self.t0 = now
            p = (now - self.t0) / self.DURATION
            if p >= 1.0:
                self.prev = None
            else:
                p = p * p * (3 - 2 * p)
                front = -0.1 + 1.1 * p
                out = {}
                for zone, pos in self.POS.items():
                    mix = min(1.0, max(0.0, (front - pos) / 0.08 + 0.5))
                    col = cur[zone] * mix + self.prev[zone] * (1 - mix)
                    white = math.exp(-((front - pos) / 0.12) ** 2) * (1.0 - 0.25 * p)
                    out[zone] = np.clip(col + white, 0, 1)
                frame = {"ring": ("direct", out["ring"]), "wheel": out["wheel"], "logo": out["logo"]}
                cur = out
        self.last = cur
        return frame


class _State:
    def __init__(self):
        self.wipe = MouseWipe()
        self.t = 0.0
        self.beat = self.snare = None
        self.beat_i = self.snare_i = 0
        self.logo_env = self.wheel_env = 0.0
        self.ring_env = 0.0
        self.glide = self.glide_target = 0.0
        self.energy_s = 0.0
        self.spin_speed, self.spin_cw, self.spin_changed = 13, True, -10.0
        self.spin_want, self.spin_want_t = 13, 0.0
        self.calm_since = 0.0
        self.flow_cols = None
        self.flow_motion = None
        self.flow_t = 0.0
        self.react_until = 0.0
        self.react_cw = True
        self.react_speed = 1
        self.flash_env = {"wheel": 0.0, "logo": 0.0}
        self.flash_col = {"wheel": np.ones(3, dtype=np.float32), "logo": np.ones(3, dtype=np.float32)}

    def react(self, now: float, cw: bool, dur: float, speed: int = 1):
        self.react_cw = cw
        self.react_speed = speed
        self.react_until = now + dur

    def flash(self, zone: str, color, level: float):
        self.flash_col[zone] = np.asarray(color, dtype=np.float32)
        self.flash_env[zone] = max(self.flash_env[zone], level)
