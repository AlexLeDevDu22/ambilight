"""
auth.py – Accès depuis le réseau local (app iPhone…) : appairage par code.

  1. L'app demande à s'appairer (POST /api/pair) → le Mac affiche un code à
     4 chiffres (interface web, notification macOS, barre de menus).
  2. L'utilisateur tape ce code dans l'app (POST /api/pair/confirm) → l'app
     reçoit un jeton permanent, à envoyer ensuite dans chaque requête :
         Authorization: Bearer <jeton>
Les requêtes venant du Mac lui-même (127.0.0.1) n'ont pas besoin de jeton.
"""

import secrets
import subprocess
import threading
import time

PAIR_TTL = 120  # secondes pour taper le code


class Auth:
    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}  # pairing_id → {device, code, expires, tries}

    # ------------------------------------------------------------------
    def devices(self) -> dict[str, dict]:
        return self.store.get()["general"]["devices"]

    def check(self, token: str | None) -> bool:
        return bool(token) and token in self.devices()

    def touch(self, token: str):
        """Mémorise la dernière activité (affichée dans l'interface)."""
        dev = self.devices().get(token)
        if dev and time.time() - dev.get("last_seen", 0) > 60:
            self.store.update({"general": {"devices": {token: {**dev, "last_seen": int(time.time())}}}})

    def revoke(self, token: str):
        devices = dict(self.devices())
        devices.pop(token, None)
        self.store.update({"general": {"devices": None}})
        self.store.update({"general": {"devices": devices}})

    # ------------------------------------------------------------------
    def request(self, device: str) -> dict:
        device = (device or "Appareil").strip()[:40]
        with self._lock:
            self._cleanup()
            pid = secrets.token_hex(8)
            code = f"{secrets.randbelow(10000):04d}"
            self._pending[pid] = {"device": device, "code": code, "expires": time.time() + PAIR_TTL, "tries": 0}
        _notify(f"{device} veut se connecter", f"Code : {code}")
        return {"pairing_id": pid, "expires_in": PAIR_TTL}

    def confirm(self, pairing_id: str, code: str) -> str | None:
        with self._lock:
            self._cleanup()
            p = self._pending.get(pairing_id)
            if not p:
                return None
            p["tries"] += 1
            if p["tries"] > 5:
                self._pending.pop(pairing_id, None)
                return None
            if not secrets.compare_digest(str(code).strip(), p["code"]):
                return None
            self._pending.pop(pairing_id, None)
        token = secrets.token_urlsafe(24)
        self.store.update({"general": {"devices": {token: {
            "name": p["device"], "paired": int(time.time()), "last_seen": int(time.time())}}}})
        return token

    def pending(self) -> list[dict]:
        """Codes en attente, affichés sur le Mac."""
        with self._lock:
            self._cleanup()
            return [{"device": p["device"], "code": p["code"], "expires_in": int(p["expires"] - time.time())}
                    for p in self._pending.values()]

    def _cleanup(self):
        now = time.time()
        for pid in [k for k, p in self._pending.items() if p["expires"] < now]:
            self._pending.pop(pid, None)


def _notify(title: str, text: str):
    script = f'display notification "{text}" with title "Ambilight" subtitle "{title}" sound name "Glass"'
    try:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
