"""
sleep.py – Mise en veille intelligente.

Écran verrouillé, écran éteint ou Mac qui s'endort → le ruban et la souris
s'éteignent (avec l'animation d'extinction) ; au retour (écran déverrouillé
et allumé) ce qui était allumé se rallume tout seul.

Source de vérité : une vérification chaque seconde (verrouillage + écran
éteint), qui marche partout. Les notifications macOS (branchées par la barre
de menus) servent à réagir tout de suite, surtout juste avant la veille du Mac
(capot fermé) où le processus est ensuite gelé.
"""

import threading

try:
    import Quartz
except Exception:
    Quartz = None


def screen_locked() -> bool:
    try:
        d = Quartz.CGSessionCopyCurrentDictionary()
        return bool(d and d.get("CGSSessionScreenIsLocked", False))
    except Exception:
        return False


def display_asleep() -> bool:
    try:
        return bool(Quartz.CGDisplayIsAsleep(Quartz.CGMainDisplayID()))
    except Exception:
        return False


class SmartSleep:
    def __init__(self, app):
        self.app = app
        self.sleeping = False
        self.reason = ""
        self._resume = {"leds": False, "mouse": False}
        self._system_sleep = False
        self._lock = threading.Lock()
        self._poke = threading.Event()

    def start(self):
        if Quartz is None:
            return
        threading.Thread(target=self._run, name="smart-sleep", daemon=True).start()

    # Notifications macOS (thread principal) ------------------------------
    def will_sleep(self):
        """Le Mac va s'endormir : on éteint tout de suite (on sera gelé après)."""
        self._system_sleep = True
        self._check()

    def did_wake(self):
        self._system_sleep = False
        self._poke.set()

    def poke(self):
        """Écran verrouillé / déverrouillé / éteint / rallumé : vérifier maintenant."""
        self._poke.set()

    def cancel(self, target: str):
        """Action manuelle pendant la veille : on ne rallumera pas `target`."""
        self._resume[target] = False

    # ---------------------------------------------------------------------
    def _run(self):
        while True:
            self._poke.wait(1.0)
            self._poke.clear()
            try:
                self._check()
            except Exception as e:
                print(f"[veille] {e}")

    def _away(self) -> str:
        if self._system_sleep:
            return "Mac en veille"
        if screen_locked():
            return "écran verrouillé"
        if display_asleep():
            return "écran éteint"
        return ""

    def _check(self):
        with self._lock:
            enabled = self.app.store.get()["general"]["smart_sleep"]
            reason = self._away() if enabled else ""
            if reason and not self.sleeping:
                self._go_to_sleep(reason)
            elif not reason and self.sleeping:
                self._wake_up()
            elif reason:
                self.reason = reason

    def _go_to_sleep(self, reason: str):
        app = self.app
        self._resume = {"leds": app.strip.running, "mouse": app.mouse.running}
        self.sleeping, self.reason = True, reason
        if not any(self._resume.values()):
            return
        print(f"[veille] {reason} → extinction")
        # Pas via app.control : l'état « allumé » mémorisé reste intact.
        threads = [threading.Thread(target=e.stop) for e, on in
                   ((app.strip, self._resume["leds"]), (app.mouse, self._resume["mouse"])) if on]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)

    def _wake_up(self):
        app = self.app
        self.sleeping, self.reason = False, ""
        if any(self._resume.values()):
            print("[veille] retour → rallumage")
        # On ne rallume que ce qui était allumé et que l'utilisateur n'a pas
        # rallumé lui-même entre-temps (télécommande…).
        if self._resume["leds"] and not app.strip.running:
            app.strip.start()
        if self._resume["mouse"] and not app.mouse.running:
            app.mouse.start()
        self._resume = {"leds": False, "mouse": False}
