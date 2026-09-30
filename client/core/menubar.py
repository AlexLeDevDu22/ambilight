"""
menubar.py – Icône Ambilight dans la barre de menus macOS.

Tourne sur le thread principal (exigence d'AppKit) ; le serveur HTTP et les
moteurs tournent dans leurs threads. Un minuteur rend la main à Python
toutes les 0,3 s : signaux (Ctrl+C), arrêt demandé, redémarrage à chaud.
"""

import threading

import objc
from AppKit import (
    NSApplication,
    NSWorkspaceDidWakeNotification,
    NSWorkspaceScreensDidSleepNotification,
    NSWorkspaceScreensDidWakeNotification,
    NSWorkspaceWillSleepNotification,
    NSApplicationActivationPolicyAccessory,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSWorkspace,
)
from Foundation import NSDistributedNotificationCenter, NSObject, NSTimer, NSURL

from . import autostart

LED_MODES = [("screen", "Écran"), ("sound", "Son"), ("ambient", "Ambiance"), ("color", "Couleur")]
MOUSE_MODES = [("sound", "Son"), ("flow", "Flow"), ("breathe", "Respiration"), ("aurora", "Aurore"),
               ("color", "Couleur"), ("sync", "Ruban (synchro)")]


def _symbol(name: str):
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "Ambilight")
    if img is not None:
        img.setTemplate_(True)
    return img


class MenuController(NSObject):
    def initWithApp_url_hooks_(self, app, url, hooks):
        self = objc.super(MenuController, self).init()
        if self is None:
            return None
        self.app = app
        self.url = url
        self.hooks = hooks  # {"tick": callable → bool (True = quitter la boucle)}
        self._icon_on = _symbol("lightbulb.fill")
        self._icon_off = _symbol("lightbulb")
        self._icon_state = None
        return self

    # ------------------------------------------------------------------
    @objc.python_method
    def setup(self):
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        button = self.item.button()
        if self._icon_off is not None:
            button.setImage_(self._icon_off)
        else:
            button.setTitle_("◐")
        button.setToolTip_("Ambilight")

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(self)

        self.status_line = self._add(menu, "Ambilight", None)
        self.status_line.setEnabled_(False)
        menu.addItem_(NSMenuItem.separatorItem())

        self.leds_item = self._add(menu, "Ruban LED", "toggleLeds:", "l")
        self.leds_modes = self._submenu(menu, "Mode du ruban", LED_MODES, "setLedMode:")
        self.mouse_item = self._add(menu, "Souris", "toggleMouse:", "m")
        self.mouse_modes = self._submenu(menu, "Mode de la souris", MOUSE_MODES, "setMouseMode:")
        menu.addItem_(NSMenuItem.separatorItem())

        self._add(menu, "Ouvrir l'interface…", "openUI:", "o")
        self.login_item = self._add(menu, "Lancer à l'ouverture de session", "toggleLogin:")
        menu.addItem_(NSMenuItem.separatorItem())
        self._add(menu, "Quitter Ambilight", "quit:", "q")
        self.item.setMenu_(menu)

        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.3, self, "tick:", None, True)

        # Veille intelligente : réagir tout de suite aux événements système
        ws = NSWorkspace.sharedWorkspace().notificationCenter()
        ws.addObserver_selector_name_object_(self, "willSleep:", NSWorkspaceWillSleepNotification, None)
        ws.addObserver_selector_name_object_(self, "didWake:", NSWorkspaceDidWakeNotification, None)
        ws.addObserver_selector_name_object_(self, "screenChanged:", NSWorkspaceScreensDidSleepNotification, None)
        ws.addObserver_selector_name_object_(self, "screenChanged:", NSWorkspaceScreensDidWakeNotification, None)
        dist = NSDistributedNotificationCenter.defaultCenter()
        dist.addObserver_selector_name_object_(self, "screenChanged:", "com.apple.screenIsLocked", None)
        dist.addObserver_selector_name_object_(self, "screenChanged:", "com.apple.screenIsUnlocked", None)
        self.refresh()

    @objc.python_method
    def _add(self, menu, title, action, key=""):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if action:
            it.setTarget_(self)
        menu.addItem_(it)
        return it

    @objc.python_method
    def _submenu(self, menu, title, modes, action):
        parent = self._add(menu, title, None)
        sub = NSMenu.alloc().init()
        sub.setAutoenablesItems_(False)
        items = {}
        for value, label in modes:
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, action, "")
            it.setTarget_(self)
            it.setRepresentedObject_(value)
            sub.addItem_(it)
            items[value] = it
        parent.setSubmenu_(sub)
        return items

    # ------------------------------------------------------------------
    @objc.python_method
    def refresh(self):
        cfg = self.app.store.get()
        leds_on, mouse_on = self.app.strip.running, self.app.mouse.running
        self.leds_item.setState_(1 if leds_on else 0)
        self.mouse_item.setState_(1 if mouse_on else 0)
        for value, it in self.leds_modes.items():
            it.setState_(1 if cfg["leds"]["mode"] == value else 0)
        for value, it in self.mouse_modes.items():
            it.setState_(1 if cfg["mouse"]["mode"] == value else 0)
        self.login_item.setState_(1 if autostart.is_enabled() else 0)
        self.login_item.setEnabled_(autostart.app_installed())
        parts = []
        parts.append("Ruban allumé" if leds_on else "Ruban éteint")
        parts.append("souris allumée" if mouse_on else "souris éteinte")
        if not self.app.link.connected:
            parts.append("Arduino absent")
        if self.app.sleep.sleeping:
            parts.append(f"en veille ({self.app.sleep.reason})")
        upd = self.app.updater.status if self.app.updater else ""
        self.status_line.setTitle_(" · ".join(parts) + (f" — {upd}" if upd else ""))
        on = leds_on or mouse_on
        if on != self._icon_state and self._icon_on is not None:
            self._icon_state = on
            self.item.button().setImage_(self._icon_on if on else self._icon_off)

    def willSleep_(self, note):
        self.app.sleep.will_sleep()

    def didWake_(self, note):
        self.app.sleep.did_wake()

    def screenChanged_(self, note):
        self.app.sleep.poke()

    def menuWillOpen_(self, menu):
        self.refresh()

    def tick_(self, timer):
        self.refresh()
        if self.hooks["tick"]():
            self.timer.invalidate()
            NSApplication.sharedApplication().stop_(None)
            # stop_ n'agit qu'au prochain événement : on en poste un
            from AppKit import NSEvent, NSApplicationDefined
            ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                NSApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0)
            NSApplication.sharedApplication().postEvent_atStart_(ev, True)

    # ------------------------------------------------------------------
    def toggleLeds_(self, sender):
        threading.Thread(target=self.app.control, args=("leds", "toggle"), daemon=True).start()

    def toggleMouse_(self, sender):
        threading.Thread(target=self.app.control, args=("mouse", "toggle"), daemon=True).start()

    def setLedMode_(self, sender):
        self.app.store.update({"leds": {"mode": sender.representedObject()}})
        if not self.app.strip.running:
            self.toggleLeds_(sender)

    def setMouseMode_(self, sender):
        self.app.store.update({"mouse": {"mode": sender.representedObject()}})
        if not self.app.mouse.running:
            self.toggleMouse_(sender)

    def openUI_(self, sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(self.url))

    def toggleLogin_(self, sender):
        if autostart.is_enabled():
            autostart.disable()
        else:
            autostart.enable()
        self.refresh()

    def quit_(self, sender):
        self.hooks["quit"]()


def run_menubar(app, url: str, tick, quit_cb):
    """Bloque jusqu'à ce que tick() renvoie True."""
    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # pas d'icône dans le Dock
    ctl = MenuController.alloc().initWithApp_url_hooks_(app, url, {"tick": tick, "quit": quit_cb})
    ctl.setup()
    nsapp.run()
    try:
        NSStatusBar.systemStatusBar().removeStatusItem_(ctl.item)
    except Exception:
        pass
