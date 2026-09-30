"""
autostart.py – Lancement d'Ambilight à l'ouverture de session (LaunchAgent).
"""

import plistlib
import subprocess
from pathlib import Path

LABEL = "local.ambilight.menubar"
APP_PATH = Path.home() / "Applications" / "Ambilight.app"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def app_installed() -> bool:
    return APP_PATH.exists()


def is_enabled() -> bool:
    return PLIST.exists()


def enable() -> bool:
    if not app_installed():
        return False
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "Label": LABEL,
        # Lancé via LaunchServices (open) : les permissions macOS restent
        # attachées à Ambilight.app. -g : en arrière-plan, sans ouvrir la page.
        "ProgramArguments": ["/usr/bin/open", "-g", "-a", str(APP_PATH), "--args", "--no-browser"],
        "RunAtLoad": True,
        "LimitLoadToSessionType": "Aqua",
    }
    with open(PLIST, "wb") as f:
        plistlib.dump(data, f)
    return True


def disable():
    try:
        subprocess.run(["launchctl", "bootout", f"gui/{_uid()}", str(PLIST)], capture_output=True, timeout=5)
    except Exception:
        pass
    PLIST.unlink(missing_ok=True)


def _uid() -> int:
    import os
    return os.getuid()
