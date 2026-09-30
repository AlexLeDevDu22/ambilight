"""
updater.py – Mises à jour automatiques pendant que le serveur tourne.

  • code Python (server.py, core/*.py) modifié → le serveur se relance tout
    seul (les permissions macOS appartiennent à Ambilight.app : conservées) ;
  • interface web (web/*) modifiée → la page se recharge toute seule ;
  • requirements.txt modifié → pip install puis redémarrage ;
  • firmware Arduino (arduino-ambilight/src, platformio.ini) modifié →
    compilation + flash automatique, les LEDs reprennent ensuite.

Utilisable aussi en ligne de commande (par update.sh) :
    python -m core.updater flash [--force]
"""

import hashlib
import subprocess
import sys
import threading
import time
from pathlib import Path

CLIENT = Path(__file__).resolve().parent.parent
ROOT = CLIENT.parent
FIRMWARE = ROOT / "arduino-ambilight"
STATE = Path.home() / ".ambilight"
PIO_CANDIDATES = [Path.home() / ".platformio/penv/bin/pio", Path("/opt/homebrew/bin/pio"), Path("/usr/local/bin/pio")]


def _files(base: Path, patterns: list[str]) -> list[Path]:
    out = []
    for pat in patterns:
        out += [p for p in base.glob(pat) if p.is_file() and "__pycache__" not in p.parts]
    return sorted(set(out))


def _hash(paths: list[Path]) -> str:
    h = hashlib.sha1()
    for p in paths:
        try:
            h.update(str(p).encode())
            h.update(p.read_bytes())
        except OSError:
            pass
    return h.hexdigest()


def code_files() -> list[Path]:
    return _files(CLIENT, ["server.py", "core/*.py"])


def web_files() -> list[Path]:
    return _files(CLIENT, ["web/*"])


def firmware_files() -> list[Path]:
    return _files(FIRMWARE, ["src/*", "platformio.ini"])


def _read_state(name: str) -> str:
    try:
        return (STATE / name).read_text().strip()
    except OSError:
        return ""


def _write_state(name: str, value: str):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / name).write_text(value)


def find_pio() -> str | None:
    for p in PIO_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def flash_firmware(port: str | None = None, log=print) -> bool:
    """Compile et téléverse le firmware. Le port série doit être libre."""
    pio = find_pio()
    if not pio:
        log("[firmware] PlatformIO introuvable (pip install platformio)")
        return False
    cmd = [pio, "run", "-t", "upload"]
    if port:
        cmd += ["--upload-port", port]
    log("[firmware] compilation + flash…")
    try:
        r = subprocess.run(cmd, cwd=FIRMWARE, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"[firmware] échec : {e}")
        return False
    if r.returncode != 0:
        log("[firmware] échec :\n" + (r.stdout + r.stderr)[-1500:])
        return False
    _write_state("firmware.hash", _hash(firmware_files()))
    log("[firmware] flashé ✓")
    return True


def firmware_outdated() -> bool:
    return _hash(firmware_files()) != _read_state("firmware.hash")


class AutoUpdater:
    """Surveille les fichiers du projet (toutes les 1,5 s)."""

    def __init__(self, app):
        self.app = app
        self.restart_requested = threading.Event()
        self.status = ""
        self._code = _hash(code_files())
        self.web_version = _hash(web_files())[:12]
        self._reqs = _hash([CLIENT / "requirements.txt"])
        self._fw_busy = False
        self._fw_failed = ""  # ne pas recompiler en boucle un firmware cassé
        self._thread = threading.Thread(target=self._run, name="updater", daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        while not self.restart_requested.is_set():
            time.sleep(1.5)
            try:
                self._check()
            except Exception as e:
                print(f"[update] {e}")

    def _check(self):
        self.web_version = _hash(web_files())[:12]

        reqs = _hash([CLIENT / "requirements.txt"])
        if reqs != self._reqs:
            self._reqs = reqs
            self.status = "installation des dépendances…"
            print("[update] requirements.txt modifié → pip install")
            subprocess.run([str(CLIENT / ".venv/bin/python"), "-m", "pip", "install", "-q", "-r", str(CLIENT / "requirements.txt")],
                           capture_output=True, timeout=600)
            self._code = ""  # force le redémarrage

        code = _hash(code_files())
        if code != self._code:
            # On ne redémarre que si tout compile (sinon on garde la version qui marche).
            for f in code_files():
                try:
                    compile(f.read_bytes(), str(f), "exec")
                except SyntaxError as e:
                    self.status = f"erreur dans {f.name} (ligne {e.lineno}), redémarrage en attente"
                    print(f"[update] {f.name}:{e.lineno} {e.msg}")
                    return
            self._code = code
            print("[update] code modifié → redémarrage à chaud")
            self.restart_requested.set()
            return

        fw_hash = _hash(firmware_files())
        if (not self._fw_busy and fw_hash != _read_state("firmware.hash") and _read_state("firmware.hash")
                and fw_hash != self._fw_failed):
            # (premier flash via update.sh : on ne flashe pas « par surprise »)
            self._fw_busy = True
            threading.Thread(target=self._flash, daemon=True).start()

    def _flash(self):
        link = self.app.link
        self.status = "mise à jour du firmware Arduino…"
        try:
            link.suspend()
            fw_hash = _hash(firmware_files())
            ok = flash_firmware(link.port)
            self._fw_failed = "" if ok else fw_hash
            self.status = "" if ok else "échec du flash du firmware (voir le log)"
        finally:
            link.resume()
            self._fw_busy = False


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "flash":
        if "--force" in sys.argv or firmware_outdated():
            sys.exit(0 if flash_firmware() else 1)
        print("[firmware] déjà à jour")
    elif len(sys.argv) >= 2 and sys.argv[1] == "mark-flashed":
        _write_state("firmware.hash", _hash(firmware_files()))
