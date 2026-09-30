"""
config.py – Réglages persistants (config.json).

Chaque modification venant de l'interface est fusionnée, validée puis
enregistrée (écriture atomique, regroupée pour ne pas marteler le disque).
"""

import copy
import json
import os
import threading
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

LED_MODES = ("screen", "sound", "ambient", "color")
LED_SOUND_EFFECTS = ("pulse", "ripples", "spectrum", "strobe")
LED_AMBIENT_EFFECTS = ("aurora", "flow", "breathe", "rainbow")
MOUSE_MODES = ("sound", "flow", "breathe", "aurora", "color", "sync")
MOUSE_SOUND_EFFECTS = ("pulse", "spin")

DEFAULTS = {
    "leds": {
        "mode": "screen",
        "sound_effect": "pulse",
        "ambient_effect": "aurora",
        "palette": "cover",
        "brightness": 1.0,
        "sensitivity": 1.0,
        "speed": 0.5,
        "smoothing": 0.5,
        "letterbox": True,
        "colors": ["#ff4d6d", "#7b5cff"],
    },
    "mouse": {
        "mode": "sound",
        "sound_effect": "pulse",
        "palette": "cover",
        "brightness": 1.0,
        "sensitivity": 1.0,
        "speed": 0.5,
        "responsive": True,
        "colors": {"ring": "#7b5cff", "wheel": "#ff4d6d", "logo": "#00d4ff"},
    },
    "hardware": {
        "serial_port": "auto",
        "screen_index": 0,
        "fps": 60,
        "gamma": 2.0,
        "saturation": 1.6,
        "border_depth_px": 300,
        "led_sides": {
            "bottom_left_count": 36,
            "right_count": 21,
            "top_count": 36,
            "left_count": 20,
            "bottom_right_count": 0,
        },
    },
    "general": {
        # Écran verrouillé / éteint / Mac en veille → tout s'éteint, puis se rallume
        "smart_sleep": True,
        # Accès depuis le réseau local (app iPhone) : appairage par code
        "lan": True,
        "devices": {},  # jeton → {name, paired, last_seen}
    },
    # Ce qui tournait à la fermeture : relancé automatiquement au démarrage.
    "run": {"leds": False, "mouse": False},
}

MAX_LEDS = 113  # limite du firmware Arduino (NUM_LEDS)


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _hex(v, default):
    if isinstance(v, str) and len(v) == 7 and v[0] == "#":
        try:
            int(v[1:], 16)
            return v.lower()
        except ValueError:
            pass
    return default


def _choice(v, choices, default):
    return v if v in choices else default


def validate(cfg: dict) -> dict:
    """Retourne une config complète et bornée (ne lève jamais)."""
    d = DEFAULTS
    out = copy.deepcopy(d)
    src_l = cfg.get("leds") or {}
    src_m = cfg.get("mouse") or {}
    src_h = cfg.get("hardware") or {}
    src_r = cfg.get("run") or {}

    L = out["leds"]
    L["mode"] = _choice(src_l.get("mode"), LED_MODES, d["leds"]["mode"])
    L["sound_effect"] = _choice(src_l.get("sound_effect"), LED_SOUND_EFFECTS, d["leds"]["sound_effect"])
    L["ambient_effect"] = _choice(src_l.get("ambient_effect"), LED_AMBIENT_EFFECTS, d["leds"]["ambient_effect"])
    L["palette"] = str(src_l.get("palette") or d["leds"]["palette"])
    L["brightness"] = _clamp(src_l.get("brightness"), 0.05, 1.0, d["leds"]["brightness"])
    L["sensitivity"] = _clamp(src_l.get("sensitivity"), 0.3, 2.5, d["leds"]["sensitivity"])
    L["speed"] = _clamp(src_l.get("speed"), 0.0, 1.0, d["leds"]["speed"])
    L["smoothing"] = _clamp(src_l.get("smoothing"), 0.0, 0.95, d["leds"]["smoothing"])
    L["letterbox"] = bool(src_l.get("letterbox", d["leds"]["letterbox"]))
    colors = src_l.get("colors")
    if isinstance(colors, list) and len(colors) >= 2:
        L["colors"] = [_hex(colors[0], d["leds"]["colors"][0]), _hex(colors[1], d["leds"]["colors"][1])]

    M = out["mouse"]
    M["mode"] = _choice(src_m.get("mode"), MOUSE_MODES, d["mouse"]["mode"])
    M["sound_effect"] = _choice(src_m.get("sound_effect"), MOUSE_SOUND_EFFECTS, d["mouse"]["sound_effect"])
    M["palette"] = str(src_m.get("palette") or d["mouse"]["palette"])
    M["brightness"] = _clamp(src_m.get("brightness"), 0.05, 1.0, d["mouse"]["brightness"])
    M["sensitivity"] = _clamp(src_m.get("sensitivity"), 0.3, 2.5, d["mouse"]["sensitivity"])
    M["speed"] = _clamp(src_m.get("speed"), 0.0, 1.0, d["mouse"]["speed"])
    M["responsive"] = bool(src_m.get("responsive", d["mouse"]["responsive"]))
    mc = src_m.get("colors") or {}
    for k in ("ring", "wheel", "logo"):
        M["colors"][k] = _hex(mc.get(k), d["mouse"]["colors"][k])

    H = out["hardware"]
    port = src_h.get("serial_port")
    H["serial_port"] = port.strip() if isinstance(port, str) and port.strip() else "auto"
    H["screen_index"] = int(_clamp(src_h.get("screen_index"), 0, 8, 0))
    H["fps"] = int(_clamp(src_h.get("fps"), 10, 60, d["hardware"]["fps"]))
    H["gamma"] = _clamp(src_h.get("gamma"), 1.0, 3.0, d["hardware"]["gamma"])
    H["saturation"] = _clamp(src_h.get("saturation"), 0.5, 4.0, d["hardware"]["saturation"])
    H["border_depth_px"] = int(_clamp(src_h.get("border_depth_px"), 20, 800, d["hardware"]["border_depth_px"]))
    sides = src_h.get("led_sides") or {}
    for k, default in d["hardware"]["led_sides"].items():
        H["led_sides"][k] = int(_clamp(sides.get(k), 0, MAX_LEDS, default))
    # Le total ne peut pas dépasser ce que le firmware accepte.
    total = sum(H["led_sides"].values())
    if total == 0 or total > MAX_LEDS:
        H["led_sides"] = copy.deepcopy(d["hardware"]["led_sides"])

    src_g = cfg.get("general") or {}
    out["general"]["smart_sleep"] = bool(src_g.get("smart_sleep", d["general"]["smart_sleep"]))
    out["general"]["lan"] = bool(src_g.get("lan", d["general"]["lan"]))
    devices = src_g.get("devices") if isinstance(src_g.get("devices"), dict) else {}
    out["general"]["devices"] = {
        str(t): {"name": str(v.get("name", "Appareil"))[:40], "paired": int(v.get("paired", 0) or 0),
                 "last_seen": int(v.get("last_seen", 0) or 0)}
        for t, v in devices.items() if isinstance(v, dict) and len(str(t)) >= 16
    }
    out["run"] = {"leds": bool(src_r.get("leds", False)), "mouse": bool(src_r.get("mouse", False))}
    return out


def _migrate_legacy(data: dict) -> dict:
    """Convertit l'ancien config.json (à plat, version Tkinter)."""
    if "leds" in data or "hardware" in data:
        return data
    hw = {
        "serial_port": data.get("serial_port") or "auto",
        "screen_index": data.get("screen_index", 0),
        "fps": data.get("fps", 30),
        "gamma": data.get("gamma", 2.0),
        "border_depth_px": data.get("border_depth_px", 300),
        "led_sides": data.get("led_sides", {}),
    }
    leds = {"mode": data.get("mode", "screen") if data.get("mode") in ("screen", "sound") else "screen"}
    return {"hardware": hw, "leds": leds}


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class ConfigStore:
    """Config partagée, thread-safe, sauvegardée automatiquement."""

    SAVE_DELAY = 0.4

    def __init__(self, path: Path = CONFIG_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._cfg = validate(self._load())
        self.version = 0
        self._save_now()

    def _load(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _migrate_legacy(data) if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            print(f"[config] config.json illisible ({e}), valeurs par défaut utilisées")
            return {}

    def get(self) -> dict:
        """Snapshot (lecture seule par convention, jamais modifié en place)."""
        return self._cfg

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._cfg = validate(deep_merge(self._cfg, patch))
            self.version += 1
            self._schedule_save()
            return self._cfg

    def _schedule_save(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.SAVE_DELAY, self._save_now)
        self._timer.daemon = True
        self._timer.start()

    def _save_now(self):
        tmp = self._path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cfg, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError as e:
            print(f"[config] sauvegarde impossible : {e}")

    def flush(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._save_now()
