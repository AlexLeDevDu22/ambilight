"""
serial_link.py – Liaison série persistante avec l'Arduino.

Protocole : 0xAA 0xBB | uint16_le nb_leds | R G B * n  → l'Arduino répond "OK".

• La connexion est ouverte UNE fois au lancement du serveur (l'ouverture du
  port redémarre l'Arduino : ~1,6 s). Démarrer / arrêter les LEDs ensuite
  est instantané.
• Un thread d'envoi ne garde que la DERNIÈRE trame (jamais de file
  d'attente → latence minimale) et attend le "OK" avant la suivante :
  sinon des octets arrivent pendant FastLED.show() (interruptions coupées)
  et sont perdus.
• Débranchement / rebranchement gérés : reconnexion automatique.
"""

import glob
import struct
import threading
import time

import serial

# 500000 bauds (firmware actuel, ~60 i/s) ; 115200 = ancien firmware, gardé
# en repli pour ne jamais rester bloqué si l'Arduino n'a pas été reflashé.
BAUDS = (500000, 115200)
HEADER = b"\xAA\xBB"


def list_ports() -> list[str]:
    return sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.wchusbserial*"))


class SerialLink:
    PING = HEADER[:1] + b"\xCC\x00\x00"  # "je suis là" (télécommande → serveur)

    def __init__(self, port_getter, on_line=None):
        self._port_getter = port_getter  # callable → "auto" ou chemin
        self._on_line = on_line          # lignes de l'Arduino hors "OK" (ex. "IR:POWER")
        self._rx = b""
        self._last_tx = 0.0
        self._ser: serial.Serial | None = None
        self._cond = threading.Condition()
        self._pending: bytes | None = None
        self._last_sent: bytes | None = None
        self._sent_seq = 0
        self._stop = threading.Event()
        self._suspended = threading.Event()
        self._thread = threading.Thread(target=self._run, name="serial", daemon=True)
        self.status = "recherche de l'Arduino…"
        self._baud = BAUDS[0]
        self.connected = False
        self.port: str | None = None
        self.fps = 0.0

    def start(self):
        self._thread.start()

    def close(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._thread.join(timeout=2)
        self._disconnect()

    def suspend(self, timeout: float = 3.0):
        """Libère le port série (flash du firmware) jusqu'à resume()."""
        self._suspended.set()
        with self._cond:
            self._cond.notify_all()
        deadline = time.monotonic() + timeout
        while self.connected and time.monotonic() < deadline:
            time.sleep(0.05)

    def resume(self):
        self._suspended.clear()

    # ------------------------------------------------------------------

    def submit(self, colors) -> None:
        """colors : ndarray (n,3) uint8 ou bytes RGB. Non bloquant."""
        payload = colors if isinstance(colors, (bytes, bytearray)) else colors.astype("uint8").tobytes()
        n = len(payload) // 3
        if n == 0:
            return
        packet = HEADER + struct.pack("<H", n) + payload
        with self._cond:
            self._pending = packet
            self._cond.notify()

    def blackout(self, n: int, timeout: float = 0.4) -> None:
        """Envoie du noir et attend qu'il soit parti (utilisé à l'arrêt)."""
        with self._cond:
            seq = self._sent_seq
        self._last_sent = None  # force l'envoi même si identique
        self.submit(bytes(3 * n))
        deadline = time.monotonic() + timeout
        with self._cond:
            while self.connected and self._sent_seq == seq and time.monotonic() < deadline:
                self._cond.wait(0.02)

    # ------------------------------------------------------------------

    def _resolve_port(self) -> str | None:
        wanted = self._port_getter()
        if wanted and wanted != "auto":
            return wanted
        ports = list_ports()
        return ports[0] if ports else None

    def _open_at(self, port: str, baud: int):
        """Ouvre le port à `baud` et vérifie que l'Arduino répond. None sinon."""
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.timeout = 0.05
        ser.write_timeout = 0.5
        ser.dtr = False
        ser.rts = False
        ser.open()
        try:
            # L'Uno redémarre à l'ouverture et annonce "READY" à sa vitesse.
            buf = b""
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline and not self._stop.is_set():
                buf += ser.read(64)
                if b"READY" in buf:
                    ser.reset_input_buffer()
                    return ser
                if len(buf) > 32 and b"READY" not in buf:
                    break  # charabia : mauvaise vitesse
            # Pas de redémarrage ? On sonde avec une trame d'une LED noire.
            ser.reset_input_buffer()
            ser.write(HEADER + struct.pack("<H", 1) + b"\x00\x00\x00")
            deadline = time.monotonic() + 0.2
            buf = b""
            while time.monotonic() < deadline:
                buf += ser.read(16)
                if b"OK" in buf:
                    return ser
        except (serial.SerialException, OSError):
            pass
        ser.close()
        return None

    def _connect(self) -> bool:
        port = self._resolve_port()
        if not port:
            self.status = "Arduino introuvable (branché ?)"
            return False
        self.status = f"connexion à {port}…"
        order = sorted(BAUDS, key=lambda b: b != self._baud)  # dernière vitesse valide d'abord
        for baud in order:
            if self._stop.is_set():
                return False
            try:
                ser = self._open_at(port, baud)
            except (serial.SerialException, OSError) as e:
                self.status = f"port {port} indisponible : {e}"
                return False
            if ser is not None:
                self._ser = ser
                self._baud = baud
                self.port = port
                self.connected = True
                self._last_sent = None
                self.status = f"connecté ({port.replace('/dev/cu.', '')} · {baud // 1000}k)"
                return True
        self.status = f"l'Arduino ne répond pas sur {port}"
        return False

    def _disconnect(self):
        self.connected = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _read_lines(self, want_ok: bool = False, timeout: float = 0.0) -> bool:
        """Lit ce que l'Arduino envoie. Renvoie True si "OK"/"ERR" reçu.
        Les autres lignes (touches de télécommande…) vont à on_line."""
        ser = self._ser
        deadline = time.monotonic() + timeout
        got_ok = False
        while True:
            n = ser.in_waiting
            if n or (want_ok and not got_ok):
                chunk = ser.read(n or 1)
                self._rx += chunk
            while b"\n" in self._rx:
                line, self._rx = self._rx.split(b"\n", 1)
                line = line.strip().decode("ascii", "ignore")
                if line in ("OK",) or line.startswith("ERR"):
                    got_ok = True
                elif line and self._on_line:
                    try:
                        self._on_line(line)
                    except Exception as e:
                        print(f"[serial] {e}")
            if len(self._rx) > 256:
                self._rx = b""
            if not want_ok or got_ok or time.monotonic() >= deadline:
                return got_ok

    def _wait_ok(self, timeout: float = 0.2):
        """Attend le "OK" de l'Arduino (fin de FastLED.show())."""
        self._read_lines(want_ok=True, timeout=timeout)

    def _run(self):
        frames, t_fps = 0, time.monotonic()
        while not self._stop.is_set():
            if self._suspended.is_set():
                if self.connected:
                    self._disconnect()
                self.status = "mise à jour du firmware…"
                self._stop.wait(0.2)
                continue
            if not self.connected:
                if not self._connect():
                    self._stop.wait(1.0)
                continue

            with self._cond:
                if self._pending is None:
                    self._cond.wait(0.03)
                packet, self._pending = self._pending, None
            if packet is None or packet == self._last_sent:
                try:
                    # Touches de télécommande + ping régulier (l'Arduino sait
                    # alors que le serveur est là et lui transmet les touches).
                    self._read_lines()
                    if time.monotonic() - self._last_tx > 1.0:
                        self._ser.write(self.PING)
                        self._last_tx = time.monotonic()
                except (serial.SerialException, OSError) as e:
                    self.status = f"Arduino déconnecté ({e.__class__.__name__}), reconnexion…"
                    self._disconnect()
                    continue
                # Le port choisi a changé dans les réglages ?
                wanted = self._port_getter()
                if wanted not in ("auto", None, "") and wanted != self.port:
                    self._disconnect()
                continue

            try:
                self._ser.write(packet)
                self._last_tx = time.monotonic()
                self._wait_ok()
                self._last_sent = packet
            except (serial.SerialException, OSError) as e:
                self.status = f"Arduino déconnecté ({e.__class__.__name__}), reconnexion…"
                self._disconnect()
                continue
            with self._cond:
                self._sent_seq += 1
                self._cond.notify_all()

            frames += 1
            now = time.monotonic()
            if now - t_fps >= 1.0:
                self.fps = frames / (now - t_fps)
                frames, t_fps = 0, now
        self._disconnect()
