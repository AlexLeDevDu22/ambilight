"""
input_events.py – Écoute globale des clics et de la molette (macOS).

CGEventTap en écoute seule (aucun événement n'est bloqué ni modifié).
Nécessite l'autorisation « Surveillance de l'entrée » pour le terminal /
l'app qui lance le serveur ; sans elle le mode Réactif est simplement inactif.
"""

import queue
import threading

try:
    import Quartz
    QUARTZ_OK = True
except Exception:
    Quartz = None
    QUARTZ_OK = False


class InputMonitor:
    def __init__(self):
        self.events: "queue.SimpleQueue[tuple[str, float]]" = queue.SimpleQueue()
        self.status = "inactif"
        self.active = False
        self._thread: threading.Thread | None = None
        self._tap = None
        self._enabled = False

    def start(self):
        """Démarre l'écoute (une seule fois, reste active ensuite)."""
        self._enabled = True
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="input-tap", daemon=True)
            self._thread.start()

    def set_enabled(self, on: bool):
        self._enabled = on
        if on:
            self.start()

    def drain(self) -> list[tuple[str, float]]:
        out = []
        try:
            while True:
                out.append(self.events.get_nowait())
        except queue.Empty:
            pass
        return out

    def _callback(self, proxy, etype, event, refcon):
        try:
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(self._tap, True)
            elif self._enabled:
                if etype == Quartz.kCGEventLeftMouseDown:
                    self.events.put(("left", 0.0))
                elif etype == Quartz.kCGEventRightMouseDown:
                    self.events.put(("right", 0.0))
                elif etype == Quartz.kCGEventOtherMouseDown:
                    self.events.put(("middle", 0.0))
                elif etype == Quartz.kCGEventScrollWheel:
                    dy = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGScrollWheelEventDeltaAxis1)
                    if dy:
                        self.events.put(("scroll", float(dy)))
        except Exception:
            pass
        return event

    def _run(self):
        if not QUARTZ_OK:
            self.status = "Quartz indisponible"
            return
        mask = 0
        for t in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventRightMouseDown,
                  Quartz.kCGEventOtherMouseDown, Quartz.kCGEventScrollWheel):
            mask |= Quartz.CGEventMaskBit(t)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if tap is None:
            self.status = "autorise « Surveillance de l'entrée » pour le Terminal (Réglages › Confidentialité)"
            self._thread = None
            return
        self._tap = tap
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self.active = True
        self.status = "clics détectés"
        Quartz.CFRunLoopRun()
