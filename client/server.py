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
import base64
import errno
import hashlib
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np

from core.audio import AudioAnalyzer
from core.auth import Auth
from core.config import CONFIG_PATH, ConfigStore
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
        self.auth = Auth(self.store)
        self.port = PORT

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
        self.stop_bonjour()
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

    def live(self, local: bool = True, lite: bool = False) -> dict:
        cfg = self.store.get()
        spotify = self.spotify.snapshot()
        preview = self.strip.preview
        if lite:
            # App : 32 couleurs suffisent pour un aperçu (au lieu de 113)
            n = len(preview) // 3
            idx = [int(i * n / 32) for i in range(32)] if n else []
            preview = b"".join(preview[i * 3:i * 3 + 3] for i in idx)
        out = {
            "leds": {
                "running": self.strip.running,
                "mode": cfg["leds"]["mode"],
                "status": self.strip.status if self.strip.running else self.link.status,
                "fps": round(self.strip.fps if self.strip.running else 0.0, 1),
                "preview": preview.hex(),
                "palette": self.palettes.get(cfg["leds"]["palette"]).hex(),
            },
            "mouse": {
                "running": self.mouse.running,
                "mode": cfg["mouse"]["mode"],
                "status": self.mouse.status if self.mouse.running else self.mouse_dev.status,
                "preview": self.mouse.preview,
                "palette": self.palettes.get(cfg["mouse"]["palette"]).hex(),
                "responsive": self.inputs.status,
            },
            "spotify": spotify,
            "nowplaying": spotify,  # alias plus clair pour l'app (source : "spotify" ou nom de l'app)
            "audio": {
                "source": "network" if self.audio.external_active else ("blackhole" if self.audio.active else "none"),
                "network_client": self.audio.external_name if self.audio.external_active else None,
            },
            "audio_hint": self.audio.hint(spotify["playing"]),
            "levels": self._levels(),
            "serial": {"status": self.link.status, "connected": self.link.connected},
            "remote": self.remote.last,
            "sleep": {"on": self.sleep.sleeping, "reason": self.sleep.reason},
            "cfg": self.store.version,  # change → l'interface recharge les réglages
        }
        if local:
            out["web"] = self.updater.web_version if self.updater else ""
            out["update"] = self.updater.status if self.updater else ""
            out["pairing"] = self.auth.pending()
        return out

    def _levels(self) -> list[float]:
        """7 barres d'égaliseur (réelles) si l'audio est actif, sinon []."""
        if not (self.audio.active or self.audio.external_active):
            return []
        spec = self.audio.snapshot()["spectrum"]
        bars = [spec[i * len(spec) // 7:(i + 1) * len(spec) // 7].max() for i in range(7)]
        return [round(float(b), 2) for b in bars]

    def public_config(self, cfg: dict, local: bool) -> dict:
        """Config sans les jetons des appareils pour les clients réseau."""
        if local:
            return cfg
        cfg = dict(cfg)
        cfg["general"] = {k: v for k, v in cfg["general"].items() if k != "devices"}
        return cfg

    def state(self, local: bool = True) -> dict:
        out = {
            "config": self.public_config(self.store.get(), local),
            "presets": PRESETS,
            "catalog": self.catalog(),
            "live": self.live(local=local, lite=not local),
        }
        if local:
            out["ports"] = list_ports()
            out["screens"] = screen_count()
            out["network"] = {"addresses": _lan_addresses(), "port": self.port}
        return out

    def info(self, token: str | None = None) -> dict:
        return {
            "name": "Ambilight",
            "api_version": 1,
            "computer": _computer_name(),
            "paired": self.auth.check(token),
            "devices": {"leds": True, "mouse": True},
        }

    @staticmethod
    def catalog() -> dict:
        """Tous les choix possibles avec leurs libellés (pour construire une interface)."""
        from core.config import LED_AMBIENT_EFFECTS, LED_MODES, LED_SOUND_EFFECTS, MOUSE_MODES, MOUSE_SOUND_EFFECTS
        from core.remote import EFFECT_LABELS, LED_LABELS, MOUSE_LABELS
        mouse_effects = {"pulse": "Pulse", "spin": "Rotation"}
        return {
            "leds": {
                "modes": [{"id": m, "label": LED_LABELS[m]} for m in LED_MODES],
                "sound_effects": [{"id": e, "label": EFFECT_LABELS[e]} for e in LED_SOUND_EFFECTS],
                "ambient_effects": [{"id": e, "label": EFFECT_LABELS[e]} for e in LED_AMBIENT_EFFECTS],
            },
            "mouse": {
                "modes": [{"id": m, "label": MOUSE_LABELS[m]} for m in MOUSE_MODES],
                "sound_effects": [{"id": e, "label": mouse_effects[e]} for e in MOUSE_SOUND_EFFECTS],
            },
            "palettes": [{"id": "cover", "label": "Pochette", "colors": None}]
                        + [{"id": k, "label": v["label"], "colors": v["colors"]} for k, v in PRESETS.items()],
        }

    # ---- Annonce Bonjour (l'app trouve le Mac toute seule) -----------------
    def start_bonjour(self):
        try:
            self._bonjour = subprocess.Popen(
                ["dns-sd", "-R", f"Ambilight ({_computer_name()})", "_ambilight._tcp", "local", str(self.port),
                 "api=1", "path=/api"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"[bonjour] {e}")

    def stop_bonjour(self):
        p = getattr(self, "_bonjour", None)
        if p:
            p.terminate()


def _computer_name() -> str:
    try:
        return subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True,
                              timeout=2).stdout.strip() or socket.gethostname()
    except Exception:
        return socket.gethostname()


def _lan_addresses() -> list[str]:
    """Adresses IPv4 du Mac sur le réseau local (pour une connexion manuelle)."""
    addrs = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
# Accessibles sans jeton depuis le réseau (découverte + appairage)
PUBLIC_PATHS = {"/api/info", "/api/pair", "/api/pair/confirm"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        # ---- Utilitaires ---------------------------------------------------
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

        def _body(self, limit: int = 100_000) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > limit:
                return {}
            try:
                data = json.loads(self.rfile.read(n))
                return data if isinstance(data, dict) else {}
            except ValueError:
                return {}

        def _query(self) -> dict:
            return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

        @property
        def _local(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

        def _token(self) -> str | None:
            h = self.headers.get("Authorization", "")
            if h.lower().startswith("bearer "):
                return h[7:].strip()
            return self._query().get("token")

        def _authorized(self, path: str) -> bool:
            """Le Mac lui-même : libre. Le réseau : jeton obligatoire (sauf appairage)."""
            if self._local or path in PUBLIC_PATHS:
                return True
            token = self._token()
            if app.auth.check(token):
                app.auth.touch(token)
                return True
            self._json({"error": "unauthorized", "hint": "appairage requis : POST /api/pair"}, 401)
            return False

        # ---- GET ------------------------------------------------------------
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in STATIC:
                if not self._local:
                    return self._send(403, b"interface disponible uniquement sur le Mac", "text/plain; charset=utf-8")
                name, ctype = STATIC[path]
                try:
                    body = (WEB_DIR / name).resolve().read_bytes()
                except OSError:
                    return self._send(404, b"not found", "text/plain")
                return self._send(200, body, ctype)
            if not self._authorized(path):
                return
            if path == "/api/info":
                return self._json(app.info(self._token()))
            if path == "/api/state":
                return self._json(app.state(local=self._local))
            if path == "/api/catalog":
                return self._json(app.catalog())
            if path == "/api/events":
                return self._events(lite=self._query().get("lite") == "1" or not self._local)
            if path == "/api/nowplaying/artwork":
                art = app.spotify.external_artwork()
                if not art:
                    return self._send(404, b"", "image/jpeg")
                ctype = "image/png" if art[:4] == b"\x89PNG" else "image/jpeg"
                return self._send(200, art, ctype, {"Cache-Control": "max-age=3600"})
            if path == "/api/audio":
                return self._websocket()
            self._send(404, b"not found", "text/plain")

        # ---- POST -----------------------------------------------------------
        def do_POST(self):
            path = urlsplit(self.path).path
            parts = path.strip("/").split("/")
            if not self._authorized(path):
                return
            try:
                if path == "/api/config":
                    patch = self._body()
                    patch.pop("run", None)
                    if not self._local:
                        (patch.get("general") or {}).pop("devices", None)
                        (patch.get("general") or {}).pop("lan", None)
                    lan_before = app.store.get()["general"]["lan"]
                    cfg = app.store.update(patch)
                    if cfg["general"]["lan"] != lan_before and app.updater:
                        app.updater.restart_requested.set()  # réécoute sur la bonne interface
                    return self._json({"config": app.public_config(cfg, self._local)})
                if path == "/api/quit":
                    if not self._local:
                        return self._json({"error": "forbidden"}, 403)
                    app.quit_event.set()
                    return self._json({"ok": True})
                if path == "/api/power":
                    on = bool(self._body().get("on", True))
                    app.control("leds", "start" if on else "stop")
                    app.control("mouse", "start" if on else "stop")
                    return self._json({"live": app.live(local=self._local)})
                if len(parts) == 3 and parts[0] == "api" and parts[1] in ("leds", "mouse") \
                        and parts[2] in ("start", "stop", "toggle", "restart"):
                    app.control(parts[1], parts[2])
                    return self._json({"live": app.live(local=self._local)})
                if path == "/api/nowplaying":
                    body = self._body(limit=4_000_000)
                    art = None
                    if body.get("artwork"):
                        try:
                            art = base64.b64decode(body["artwork"], validate=False)[:3_000_000]
                        except (ValueError, TypeError):
                            art = None
                    app.spotify.set_external(body, art)
                    return self._json({"ok": True, "spotify": app.spotify.snapshot()})
                if path == "/api/pair":
                    return self._json(app.auth.request(self._body().get("device", "")))
                if path == "/api/pair/confirm":
                    body = self._body()
                    token = app.auth.confirm(str(body.get("pairing_id", "")), str(body.get("code", "")))
                    if not token:
                        return self._json({"error": "code invalide ou expiré"}, 403)
                    return self._json({"token": token, "info": app.info(token)})
                if path == "/api/devices/revoke":
                    if not self._local:
                        return self._json({"error": "forbidden"}, 403)
                    app.auth.revoke(str(self._body().get("token", "")))
                    return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            self._send(404, b"not found", "text/plain")

        # ---- Flux temps réel (Server-Sent Events) -------------------------
        def _events(self, lite: bool):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            local = self._local
            try:
                while True:
                    payload = json.dumps(app.live(local=local, lite=lite))
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(1 / 15)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            self.close_connection = True

        # ---- WebSocket : son de l'app → analyse audio ----------------------
        def _websocket(self):
            key = self.headers.get("Sec-WebSocket-Key")
            if not key or self.headers.get("Upgrade", "").lower() != "websocket":
                return self._json({"error": "WebSocket attendu"}, 400)
            q = self._query()
            try:
                sr = int(q.get("sample_rate", 48000))
            except ValueError:
                sr = 48000
            sr = max(8000, min(96000, sr))
            name = (q.get("name") or "app")[:40]
            accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.close_connection = True
            self.connection.settimeout(10)
            print(f"[audio] flux réseau ouvert : {name} ({sr} Hz)")
            buf = b""
            try:
                while True:
                    head = self.rfile.read(2)
                    if len(head) < 2:
                        break
                    fin, op = head[0] & 0x80, head[0] & 0x0F
                    masked, ln = head[1] & 0x80, head[1] & 0x7F
                    if ln == 126:
                        ln = struct.unpack(">H", self.rfile.read(2))[0]
                    elif ln == 127:
                        ln = struct.unpack(">Q", self.rfile.read(8))[0]
                    if ln > 1 << 20:
                        break
                    mask = self.rfile.read(4) if masked else b""
                    data = self.rfile.read(ln)
                    if masked and data:
                        m = np.frombuffer((mask * (ln // 4 + 1))[:ln], dtype=np.uint8)
                        data = (np.frombuffer(data, dtype=np.uint8) ^ m).tobytes()
                    if op == 0x8:  # fermeture
                        self._ws_send(0x8, data[:2])
                        break
                    if op == 0x9:  # ping → pong
                        self._ws_send(0xA, data)
                        continue
                    if op == 0x1:  # texte : réglage du format ({"sample_rate": 44100})
                        try:
                            sr = max(8000, min(96000, int(json.loads(data).get("sample_rate", sr))))
                        except (ValueError, AttributeError):
                            pass
                        continue
                    if op in (0x2, 0x0):
                        buf += data
                        if fin:
                            app.audio.feed_external(buf, sr, name)
                            buf = b""
            except (OSError, ConnectionError, struct.error):
                pass
            print(f"[audio] flux réseau fermé : {name}")

        def _ws_send(self, op: int, payload: bytes = b""):
            try:
                self.wfile.write(bytes([0x80 | op, len(payload)]) + payload)
                self.wfile.flush()
            except OSError:
                pass

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

    # Accès réseau (app iPhone) activé ? → écoute sur toutes les interfaces
    try:
        lan = json.loads(CONFIG_PATH.read_text()).get("general", {}).get("lan", True)
    except (OSError, ValueError):
        lan = True
    bind = "0.0.0.0" if lan else HOST

    try:
        httpd = Server((bind, args.port), None)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            # Déjà lancé : on ouvre simplement l'interface existante.
            print(f"Ambilight tourne déjà → {url}")
            if not args.no_browser:
                webbrowser.open(url)
            return
        raise

    app = App()
    app.port = args.port
    app.updater = AutoUpdater(app)
    httpd.RequestHandlerClass = make_handler(app)

    def on_signal(*_):
        app.quit_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    app.boot()
    app.updater.start()
    if lan:
        app.start_bonjour()
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
