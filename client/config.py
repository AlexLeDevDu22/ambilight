"""
config.py – Lecture et écriture du fichier config.json.
"""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULTS = {
    "num_leds": 113,
    "fps": 50,
    "screen_index": 0,
    "mouse_enabled": True,
    "mouse_sample_radius": 180,
    "border_depth_px": 300,
    "start_corner": "bottom-left",
    "direction": "counter-clockwise",
    "led_sides": {
        "bottom_left_count": 36,
        "right_count": 21,
        "top_count": 36,
        "left_count": 20,
        "bottom_right_count": 0,
    },
    "gamma": 2.0,
    "brightness": 1,
    "saturation_boost": 4,
    # Transitions (lissage temporel entre frames)
    "transition_speed": 0.5,       # 0.0 = instantané, 1.0 = très lent
    # Mode Sound Ambient
    "mode": "screen",              # "screen" ou "sound"
    "sound_device": None,          # None = défaut système
    "sound_effect": "ripples",    # "spectrum", "ripples"
    "sound_hue_speed": 0.1,       # vitesse de drift de teinte (mode son)
    "sound_smoothing": 0.3,        # EMA smoothing analyseur audio
    # Audio sources (nouveau)
    "audio_source": "system",         # "mic", "system", "spotify"
    "audio_intensity": 1.0,        # 0.5 - 2.0, contrôle en temps réel
    "realtime_brightness": 1.0,    # 0.1 - 2.0, intensité lumineuse (son uniquement)
}


def load() -> dict:
    """Charge config.json et comble les valeurs manquantes avec DEFAULTS."""
    if not CONFIG_PATH.exists():
        save(DEFAULTS)
        return dict(DEFAULTS)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Merge récursif simple : top-level keys
    merged = dict(DEFAULTS)
    merged.update(data)
    # Pour les sous-dicts (led_sides)
    if "led_sides" in data:
        merged["led_sides"] = dict(DEFAULTS["led_sides"])
        merged["led_sides"].update(data["led_sides"])

    return merged


def save(cfg: dict) -> None:
    """Sauvegarde la config dans config.json (sans les clés internes _*)."""
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
