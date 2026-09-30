"""
permissions.py – Autorisations macOS nécessaires à Ambilight.

Appelé au lancement de l'app : si une autorisation manque, macOS affiche sa
fenêtre de demande (ou ouvre Réglages) pour « Ambilight ».
"""

try:
    import Quartz
except Exception:
    Quartz = None


def input_monitoring_ok() -> bool:
    try:
        return bool(Quartz.CGPreflightListenEventAccess())
    except Exception:
        return True


def screen_capture_ok() -> bool:
    try:
        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return True


def request_missing(need_screen: bool) -> list[str]:
    """Demande ce qui manque ; retourne la liste des autorisations absentes."""
    missing = []
    if Quartz is None:
        return missing
    if not input_monitoring_ok():
        missing.append("Surveillance de l'entrée")
        try:
            Quartz.CGRequestListenEventAccess()
        except Exception:
            pass
    if need_screen and not screen_capture_ok():
        missing.append("Enregistrement de l'écran")
        try:
            Quartz.CGRequestScreenCaptureAccess()
        except Exception:
            pass
    return missing
