"""
remote.py – Télécommande IR (Elegoo 21 touches) → actions du serveur.

Quand le serveur tourne, l'Arduino lui transmet chaque touche ("IR:<TOUCHE>").
Serveur arrêté : l'Arduino garde ses modes autonomes.

  POWER        tout allumer / tout éteindre
  ▶︎ (PLAY)     ruban on/off           ST        souris on/off
  VOL+ / VOL−  luminosité (maintenir pour aller vite)
  FUNC         mode ruban suivant     EQ        mode souris suivant
  |◀◀ / ▶▶|    effet précédent / suivant (Son, Ambiance)
  ↑ / ↓        palette suivante / précédente (ruban + souris)
  1 2 3 4      ruban : Écran · Son · Ambiance · Couleur
  5 6 7 8 9    souris : Son · Flow · Respiration · Aurore · Couleur
  0            souris : synchro Ruban
"""

import queue
import threading
import time

from .config import LED_AMBIENT_EFFECTS, LED_MODES, LED_SOUND_EFFECTS, MOUSE_MODES
from .palette import PRESETS

LED_LABELS = {"screen": "Écran", "sound": "Son", "ambient": "Ambiance", "color": "Couleur"}
MOUSE_LABELS = {"sound": "Son", "flow": "Flow", "breathe": "Respiration", "aurora": "Aurore",
                "color": "Couleur", "sync": "Ruban"}
EFFECT_LABELS = {"pulse": "Pulse", "ripples": "Ondes", "spectrum": "Spectre", "strobe": "Strobe",
                 "aurora": "Aurore", "flow": "Flow", "breathe": "Respiration", "rainbow": "Arc-en-ciel"}
PALETTES = ["cover"] + list(PRESETS)
DIGIT_LED = {"1": "screen", "2": "sound", "3": "ambient", "4": "color"}
DIGIT_MOUSE = {"5": "sound", "6": "flow", "7": "breathe", "8": "aurora", "9": "color", "0": "sync"}


def _cycle(seq, cur, step):
    seq = list(seq)
    i = seq.index(cur) if cur in seq else 0
    return seq[(i + step) % len(seq)]


class RemoteControl:
    def __init__(self, app):
        self.app = app
        self.last = {"id": 0, "text": "", "t": 0.0}
        self._queue: "queue.SimpleQueue[tuple[str, bool]]" = queue.SimpleQueue()
        self._last_repeat = 0.0
        threading.Thread(target=self._worker, name="remote", daemon=True).start()

    def on_serial_line(self, line: str):
        """Appelé par le thread série : ne fait qu'empiler (jamais bloquer)."""
        if line.startswith("IR:RAW:"):
            print(f"[télécommande] touche inconnue, code {line[7:]}")
        elif line.startswith("IR:"):
            parts = line[3:].split(":")
            self._queue.put((parts[0], len(parts) > 1 and parts[1] == "R"))

    def _worker(self):
        while True:
            key, repeat = self._queue.get()
            try:
                text = self.handle(key, repeat)
                if text:
                    self.last = {"id": self.last["id"] + 1, "text": text, "t": time.time()}
                    print(f"[télécommande] {key} → {text}")
            except Exception as e:
                print(f"[télécommande] {key} : {e}")

    # ------------------------------------------------------------------
    def handle(self, key: str, repeat: bool) -> str:
        app = self.app
        cfg = app.store.get()
        L, M = cfg["leds"], cfg["mouse"]

        if repeat:
            # Seules VOL+ / VOL− se répètent (touche maintenue), sans s'emballer
            if key not in ("VOL_UP", "VOL_DOWN") or time.monotonic() - self._last_repeat < 0.12:
                return ""
            self._last_repeat = time.monotonic()

        if key == "POWER":
            if app.strip.running or app.mouse.running:
                app.control("leds", "stop")
                app.control("mouse", "stop")
                return "Tout éteint"
            app.control("leds", "start")
            app.control("mouse", "start")
            return "Tout allumé"
        if key == "PLAY":
            app.control("leds", "toggle")
            return "Ruban allumé" if app.strip.running else "Ruban éteint"
        if key == "ST":
            app.control("mouse", "toggle")
            return "Souris allumée" if app.mouse.running else "Souris éteinte"

        if key in ("VOL_UP", "VOL_DOWN"):
            step = 0.1 if key == "VOL_UP" else -0.1
            b = round(min(1.0, max(0.05, L["brightness"] + step)), 2)
            mb = round(min(1.0, max(0.05, M["brightness"] + step)), 2)
            app.store.update({"leds": {"brightness": b}, "mouse": {"brightness": mb}})
            return f"Luminosité {round(b * 100)} %"

        if key == "FUNC":
            return self._led_mode(_cycle(LED_MODES, L["mode"], 1))
        if key == "EQ":
            return self._mouse_mode(_cycle(MOUSE_MODES, M["mode"], 1))
        if key in DIGIT_LED:
            return self._led_mode(DIGIT_LED[key])
        if key in DIGIT_MOUSE:
            return self._mouse_mode(DIGIT_MOUSE[key])

        if key in ("PREV", "NEXT"):
            step = 1 if key == "NEXT" else -1
            if L["mode"] == "sound":
                eff = _cycle(LED_SOUND_EFFECTS, L["sound_effect"], step)
                app.store.update({"leds": {"sound_effect": eff}})
            elif L["mode"] == "ambient":
                eff = _cycle(LED_AMBIENT_EFFECTS, L["ambient_effect"], step)
                app.store.update({"leds": {"ambient_effect": eff}})
            else:
                return self._palette(step)
            self._ensure("leds")
            return f"Effet {EFFECT_LABELS.get(eff, eff)}"

        if key in ("UP", "DOWN"):
            return self._palette(1 if key == "UP" else -1)
        return ""

    def _ensure(self, target: str):
        engine = self.app.strip if target == "leds" else self.app.mouse
        if not engine.running:
            self.app.control(target, "start")

    def _led_mode(self, mode: str) -> str:
        self.app.store.update({"leds": {"mode": mode}})
        self._ensure("leds")
        return f"Ruban : {LED_LABELS[mode]}"

    def _mouse_mode(self, mode: str) -> str:
        self.app.store.update({"mouse": {"mode": mode}})
        self._ensure("mouse")
        return f"Souris : {MOUSE_LABELS[mode]}"

    def _palette(self, step: int) -> str:
        pal = _cycle(PALETTES, self.app.store.get()["leds"]["palette"], step)
        self.app.store.update({"leds": {"palette": pal}, "mouse": {"palette": pal}})
        name = "Cover" if pal == "cover" else PRESETS[pal]["label"]
        return f"Palette {name}"
