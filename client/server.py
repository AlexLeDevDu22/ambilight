"""
server.py – Serveur local Ambilight + interface web.

    python server.py            → http://127.0.0.1:8787 (ouvre le navigateur)
    python server.py --no-browser
    python server.py --no-menubar   (sans icône dans la barre de menus)

En temps normal il est lancé par Ambilight.app (voir update.sh) : icône dans
la barre de menus, démarrage à l'ouverture de session, mises à jour à chaud.

Architecture :
  • connexions matérielles persistantes (Arduino, souris) ouvertes au lancement
  • un thread par moteur (ruban, souris), réglages appliqués à chaud
  • API JSON + flux temps réel (Server-Sent Events) pour l'aperçu live
  • réglages enregistrés à chaque changement (config.json)
"""

import argparse
import errno
import json
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.audio import AudioAnalyzer
from core.config import ConfigStore
from core.input_events import InputMonitor
from core.mouse_device import RevengerST
from core.mouse_engine import MouseEngine
from core.palette import PRESETS, PaletteProvider, SpotifyWatcher
from core.remote import RemoteControl
from core.screen import screen_count
from core.serial_link import SerialLink, list_ports
from core.sleep import SmartSleep
from core.strip_engine import StripEngine
from core.updater import AutoUpdater

HOST = "127.0.0.1"
PORT = 8787
WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/icon.png": ("../Icon.png", "image/png"),
}


class App:
    def __init__(self):
        self.store = ConfigStore()
        self.spotify = SpotifyWatcher()
        self.palettes = PaletteProvider(self.spotify)
        self.audio = AudioAnalyzer()
        self.remote = RemoteControl(self)
        self.link = SerialLink(lambda: self.store.get()["hardware"]["serial_port"], self.remote.on_serial_line)
        self.mouse_dev = RevengerST()
        self.inputs = InputMonitor()
        self.strip = StripEngine(self.store, self.link, self.audio, self.palettes)
        self.mouse = MouseEngine(self.store, self.mouse_dev, self.audio, self.palettes, self.inputs)
        self.mouse.strip = self.strip
        self.sleep = SmartSleep(self)
        self._ctl_lock = threading.Lock()
        self.updater: AutoUpdater | None = None
        self.quit_event = threading.Event()

    def boot(self):
        if os.environ.get("AMBILIGHT_APP"):
            from core import permissions
            missing = permissions.request_missing(self.store.get()["leds"]["mode"] == "screen")
            if missing:
                print(f"[permissions] à autoriser pour Ambilight : {', '.join(missing)}")
        self.spotify.start()
        self.link.start()           # connexion Arduino en tâche de fond, dès maintenant
        threading.Thread(target=self._watch_mouse, name="mouse-watch", daemon=True).start()
        self.sleep.start()
        run = self.store.get()["run"]
        if run["leds"]:
            self.strip.start()
        if run["mouse"]:
            self.mouse.start()

    def _watch_mouse(self):
        """Garde la souris ouverte (démarrage instantané, rebranchement auto)."""
        while True:
            if not self.mouse.running and not self.mouse_dev.connected:
                self.mouse_dev.open()
            time.sleep(2.0)

    def shutdown(self):
        for engine in (self.strip, self.mouse):
            try:
                if engine.running:
                    engine.stop()
            except Exception as e:
                print(f"[arrêt] {e}")
        self.spotify.stop()
        self.link.close()
        self.mouse_dev.close()
        self.store.flush()

    # ------------------------------------------------------------------

    def control(self, target: str, action: str) -> None:
        engine = {"leds": self.strip, "mouse": self.mouse}[target]
        if self.sleep.sleeping:
            self.sleep.cancel(target)
        with self._ctl_lock:
            if action == "toggle":
                action = "stop" if engine.running else "start"
            if action == "start":
                engine.start()
            elif action == "stop":
                engine.stop()
            elif action == "restart":
                engine.stop()
                engine.start()
            self.store.update({"run": {target: engine.running}})

    def live(self) -> dict:
        cfg = self.store.get()
        spotify = self.spotify.snapshot()
        return {
            "leds": {
                "running": self.strip.running,
                "status": self.strip.status if self.strip.running else self.link.status,
                "fps": round(self.strip.fps if self.strip.running else 0.0, 1),
                "preview": self.strip.preview.hex(),
                "palette": self.palettes.get(cfg["leds"]["palette"]).hex(),
            },
            "mouse": {
                "running": self.mouse.running,
                "status": self.mouse.status if self.mouse.running else self.mouse_dev.status,
                "preview": self.mouse.preview,
                "palette": self.palettes.get(cfg["mouse"]["palette"]).hex(),
                "responsive": self.inputs.status,
            },
            "spotify": spotify,
            "audio_hint": self.audio.hint(spotify["playing"]),
            "levels": self._levels(),
            "serial": {"status": self.link.status, "connected": self.link.connected},
            "remote": self.remote.last,
            "sleep": {"on": self.sleep.sleeping, "reason": self.sleep.reason},
            "cfg": self.store.version,  # change → l'interface recharge les réglages
            "web": self.updater.web_version if self.updater else "",
            "update": self.updater.status if self.updater else "",
        }

    def _levels(self) -> list[float]:
        """7 barres d'égaliseur (réelles) si l'audio est actif, sinon []."""
        if not self.audio.active:
            return []
        spec = self.audio.snapshot()["spectrum"]
        bars = [spec[i * len(spec) // 7:(i + 1) * len(spec) // 7].max() for i in range(7)]
        return [round(float(b), 2) for b in bars]

    def state(self) -> dict:
        return {
            "config": self.store.get(),
            "presets": PRESETS,
            "ports": list_ports(),
            "screens": screen_count(),
            "live": self.live(),
        }


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 100_000:
                return {}
            try:
                data = json.loads(self.rfile.read(n))
                return data if isinstance(data, dict) else {}
            except ValueError:
                return {}

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in STATIC:
                name, ctype = STATIC[path]
                try:
                    body = (WEB_DIR / name).resolve().read_bytes()
                except OSError:
                    return self._send(404, b"not found", "text/plain")
                return self._send(200, body, ctype)
            if path == "/api/state":
                return self._json(app.state())
            if path == "/api/events":
                return self._events()
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            parts = path.strip("/").split("/")
            try:
                if path == "/api/config":
                    patch = self._body()
                    patch.pop("run", None)
                    cfg = app.store.update(patch)
                    return self._json({"config": cfg})
                if path == "/api/quit":
                    app.quit_event.set()
                    return self._json({"ok": True})
                if len(parts) == 3 and parts[0] == "api" and parts[1] in ("leds", "mouse") \
                        and parts[2] in ("start", "stop", "toggle", "restart"):
                    app.control(parts[1], parts[2])
                    return self._json({"live": app.live()})
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            self._send(404, b"not found", "text/plain")

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(app.live())
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(1 / 15)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            self.close_connection = True

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(description="Ambilight – serveur local")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-menubar", action="store_true")
    args = parser.parse_args()
    url = f"http://{HOST}:{args.port}"

    try:
        httpd = Server((HOST, args.port), None)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            # Déjà lancé : on ouvre simplement l'interface existante.
            print(f"Ambilight tourne déjà → {url}")
            if not args.no_browser:
                webbrowser.open(url)
            return
        raise

    app = App()
    app.updater = AutoUpdater(app)
    httpd.RequestHandlerClass = make_handler(app)

    def on_signal(*_):
        app.quit_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    app.boot()
    app.updater.start()
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.25}, name="http", daemon=True).start()
    print(f"✦ Ambilight prêt → {url}  (Ctrl+C pour quitter)")
    if not args.no_browser:
        webbrowser.open(url)

    def should_exit() -> bool:
        return app.quit_event.is_set() or app.updater.restart_requested.is_set()

    menubar = None
    if not args.no_menubar:
        try:
            from core.menubar import run_menubar
            menubar = run_menubar
        except Exception as e:
            print(f"[menubar] indisponible : {e}")
    if menubar:
        menubar(app, url, should_exit, app.quit_event.set)
    else:
        while not should_exit():
            time.sleep(0.3)

    restart = app.updater.restart_requested.is_set() and not app.quit_event.is_set()
    print("Redémarrage (code modifié)…" if restart else "Arrêt…")
    httpd.shutdown()
    httpd.server_close()
    app.shutdown()
    if restart:
        # Relance propre dans un nouveau processus, une fois celui-ci terminé.
        # (Un execv dans le même processus casse l'icône de la barre de menus.)
        argv = [a for a in sys.argv[1:] if a != "--no-browser"] + ["--no-browser"]
        if os.environ.get("AMBILIGHT_APP"):
            bundle = Path(sys.executable).resolve().parents[2]  # …/Ambilight.app
            relaunch = ["/usr/bin/open", "-g", "-a", str(bundle), "--args"] + argv
        else:
            relaunch = [sys.executable, "-u", str(Path(__file__).resolve())] + argv
        waiter = f'while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.1; done; exec "$@"'
        subprocess.Popen(["/bin/sh", "-c", waiter, "sh"] + relaunch, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sys.exit(0)


if __name__ == "__main__":
    main()
