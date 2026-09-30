"""
strip_engine.py – Boucle du ruban LED Arduino (écran / son / ambiance / couleur).

Les réglages sont relus à chaque image : changer de mode, de palette ou de
luminosité s'applique immédiatement, sans redémarrer.
"""

import threading
import time

import numpy as np

from .screen import LetterboxDetector, ScreenMapper, led_layout, open_capture
from .strip_effects import OUTRO_DURATION, AmbientEffect, SoundEffect, StripGeometry, WipeTransition, color_mode, outro_frame


class StripEngine:
    def __init__(self, store, link, audio, palettes):
        self._store = store
        self._link = link
        self._audio = audio
        self._palettes = palettes
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.running = False
        self.status = "arrêté"
        self.preview = b""
        self.fps = 0.0
        # Dernière image (avant luminosité) + position des LEDs : lue par la
        # souris en mode synchro « Ruban ».
        self.shared: tuple | None = None

    # ------------------------------------------------------------------

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.running = True
            self.status = "démarrage…"
            self._thread = threading.Thread(target=self._run, name="strip", daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop.set()
            t = self._thread
            self._thread = None
        if t:
            t.join(timeout=2.0)
        n = self._num_leds()
        self._link.blackout(n)
        self.running = False
        self.shared = None
        self.preview = bytes(3 * n)
        self.status = "arrêté"
        self.fps = 0.0

    def _num_leds(self) -> int:
        return sum(self._store.get()["hardware"]["led_sides"].values())

    # ------------------------------------------------------------------

    def _run(self):
        geom_key, geom = None, None
        capture, capture_idx, capture_t0 = None, None, 0.0
        mapper = ScreenMapper()
        letterbox = LetterboxDetector()
        sound = SoundEffect()
        wipe = WipeTransition()
        wipe_t = 0.0
        link_was_connected = False
        look = None  # mode / effet / palette / couleurs : un changement déclenche la transition
        ambient = AmbientEffect()
        audio_on = False
        last = time.perf_counter()
        frames, t_fps = 0, last
        last_audio_check = 0.0

        try:
            while not self._stop.is_set():
                try:
                    cfg = self._store.get()
                    L, H = cfg["leds"], cfg["hardware"]
                    interval = 1.0 / H["fps"]
                    now = time.perf_counter()
                    dt = min(0.1, now - last)
                    last = now

                    key = tuple(sorted(H["led_sides"].items()))
                    if key != geom_key:
                        geom, geom_key = StripGeometry(led_layout(H["led_sides"])), key

                    mode = L["mode"]
                    new_look = (mode, L["sound_effect"], L["ambient_effect"], L["palette"], tuple(L["colors"]))
                    if new_look != look:
                        # Glisser un sélecteur de couleur : on ne relance pas la
                        # transition en boucle, celle en cours suit les couleurs.
                        only_colors = look is not None and new_look[:4] == look[:4]
                        if not (only_colors and now - wipe_t < 0.8):
                            wipe.trigger(geom.n)
                            wipe_t = now
                        look = new_look
                    # Arduino (re)connecté (démarrage du serveur : il redémarre
                    # ~1,6 s) → l'animation d'allumage part de là, depuis le noir,
                    # sinon elle se jouerait dans le vide.
                    connected = self._link.connected
                    if connected and not link_was_connected:
                        wipe.last = None
                        wipe.trigger(geom.n)
                        wipe_t = now
                    link_was_connected = connected
                    # L'audio n'est ouvert que si le mode son est actif.
                    if (mode == "sound") != audio_on:
                        (self._audio.acquire if not audio_on else self._audio.release)()
                        audio_on = not audio_on
                    if mode != "screen" and capture is not None:
                        capture.close()
                        capture = None

                    colors = None
                    gamma = H["gamma"]
                    if mode == "screen":
                        if capture is None or capture_idx != H["screen_index"]:
                            if capture is not None:
                                capture.close()
                            capture = open_capture(H["screen_index"], H["fps"])
                            capture_idx = H["screen_index"]
                            capture_t0 = now
                        frame = capture.capture()
                        if frame is None:
                            if now - capture_t0 > 2.0:
                                self.status = "capture d'écran refusée (autorise l'enregistrement d'écran)"
                            self._stop.wait(0.05)
                            continue
                        native_w = capture.native_w
                        film = ""
                        if L["letterbox"]:
                            t, b, l, r = letterbox.update(frame, now)
                            if t or b or l or r:
                                h, w = frame.shape[:2]
                                frame = frame[t:h - b, l:w - r]
                                native_w = native_w * frame.shape[1] / w
                                film = f" · film {letterbox.aspect((h, w))}"
                        colors = mapper.map(frame, H, L["smoothing"], native_w)
                        self.status = "écran" + film
                    elif mode == "sound":
                        if now - last_audio_check > 1.0:
                            self._audio.ensure()
                            last_audio_check = now
                        pal = self._palettes.get(L["palette"])
                        colors = sound.render(L["sound_effect"], geom, pal, self._audio.snapshot(), L["sensitivity"], dt)
                        self.status = f"son · {self._audio.status}"
                    elif mode == "ambient":
                        pal = self._palettes.get(L["palette"])
                        colors = ambient.render(L["ambient_effect"], geom, pal, L["speed"], dt)
                        self.status = "ambiance"
                    else:
                        colors = color_mode(geom, L["colors"])
                        self.status = "couleur"

                    colors = wipe.apply(np.clip(colors, 0.0, 1.0), geom, now)
                    self.shared = (colors, geom.pos)
                    colors = colors * L["brightness"]
                    out = (np.power(colors, gamma) * 255.0 + 0.5).astype(np.uint8)
                    self._link.submit(out)
                    # Aperçu pour l'interface : couleurs perçues (sans gamma)
                    self.preview = (colors * 255).astype(np.uint8).tobytes()

                    if not self._link.connected:
                        self.status = self._link.status

                    frames += 1
                    if now - t_fps >= 1.0:
                        self.fps = frames / (now - t_fps)
                        frames, t_fps = 0, now

                    spare = interval - (time.perf_counter() - now)
                    if spare > 0:
                        self._stop.wait(spare)
                except Exception as e:
                    # Jamais fatal : on signale et on réessaie.
                    print(f"[strip] {e.__class__.__name__}: {e}")
                    self.status = f"erreur : {e}"
                    if capture is not None:
                        capture.close()
                    capture = None
                    self._stop.wait(1.0)
        finally:
            try:
                self._outro(wipe.last, geom)
            except Exception as e:
                print(f"[strip] extinction : {e}")
            if capture is not None:
                capture.close()
            if audio_on:
                self._audio.release()

    def _outro(self, last, geom):
        """Animation d'extinction (lumière blanche qui descend) avant le noir."""
        if last is None or geom is None or len(last) != geom.n or not self._link.connected:
            return
        cfg = self._store.get()
        bright, gamma = cfg["leds"]["brightness"], cfg["hardware"]["gamma"]
        t0 = time.perf_counter()
        while True:
            p = (time.perf_counter() - t0) / OUTRO_DURATION
            if p >= 1.0:
                break
            colors = outro_frame(last, geom, p) * bright
            self._link.submit((np.power(colors, gamma) * 255.0 + 0.5).astype(np.uint8))
            self.preview = (colors * 255).astype(np.uint8).tobytes()
            time.sleep(1 / 60)
