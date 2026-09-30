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

BAUD = 115200
HEADER = b"\xAA\xBB"


def list_ports() -> list[str]:
    return sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.wchusbserial*"))


class SerialLink:
    def __init__(self, port_getter):
        self._port_getter = port_getter  # callable → "auto" ou chemin
        self._ser: serial.Serial | None = None
        self._cond = threading.Condition()
        self._pending: bytes | None = None
        self._last_sent: bytes | None = None
        self._sent_seq = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="serial", daemon=True)
        self.status = "recherche de l'Arduino…"
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

    def _connect(self) -> bool:
        port = self._resolve_port()
        if not port:
            self.status = "Arduino introuvable (branché ?)"
            return False
        self.status = f"connexion à {port}…"
        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = BAUD
            ser.timeout = 0.05
            ser.write_timeout = 0.5
            ser.dtr = False
            ser.rts = False
            ser.open()
        except (serial.SerialException, OSError) as e:
            self.status = f"port {port} indisponible : {e}"
            return False

        # L'Arduino (Uno) redémarre à l'ouverture : on attend son "READY",
        # sans bloquer indéfiniment s'il ne redémarre pas.
        buf = b""
        deadline = time.monotonic() + 2.5
        try:
            while time.monotonic() < deadline and not self._stop.is_set():
                buf += ser.read(64)
                if b"READY" in buf:
                    break
            ser.reset_input_buffer()
        except (serial.SerialException, OSError) as e:
            self.status = f"Arduino muet : {e}"
            ser.close()
            return False

        self._ser = ser
        self.port = port
        self.connected = True
        self._last_sent = None
        self.status = f"connecté ({port.replace('/dev/cu.', '')})"
        return True

    def _disconnect(self):
        self.connected = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _wait_ok(self, timeout: float = 0.08):
        """Attend le "OK" de l'Arduino (fin de FastLED.show())."""
        ser = self._ser
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                buf += chunk
                if b"OK" in buf or b"ERR" in buf:
                    return

    def _run(self):
        frames, t_fps = 0, time.monotonic()
        while not self._stop.is_set():
            if not self.connected:
                if not self._connect():
                    self._stop.wait(1.0)
                continue

            with self._cond:
                if self._pending is None:
                    self._cond.wait(0.5)
                packet, self._pending = self._pending, None
            if packet is None:
                # Le port choisi a changé dans les réglages ?
                wanted = self._port_getter()
                if wanted not in ("auto", None, "") and wanted != self.port:
                    self._disconnect()
                continue
            if packet == self._last_sent:
                continue

            try:
                self._ser.write(packet)
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
