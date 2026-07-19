"""
led_strip.py – Communication série avec l'Arduino.
Protocole : header 0xAA 0xBB | uint16_le nombre_leds | R G B * n
L'Arduino répond "READY" au démarrage, "OK" après chaque paquet.

Optimisation latence : on envoie sans attendre le "OK" (non-bloquant).
On vide juste le buffer entrant avant chaque envoi pour éviter l'accumulation.
"""

import serial
import struct
import time
import threading


class LedStrip:
    HEADER = b"\xAA\xBB"
    BAUD_RATE = 115200
    MAX_LEDS = 113

    def __init__(self, port: str, timeout: float = 3.0):
        try:
            self.ser = serial.Serial()
            self.ser.port = port
            self.ser.baudrate = self.BAUD_RATE
            self.ser.timeout = timeout
            self.ser.dtr = False   # empêche le reset Arduino à l'ouverture
            self.ser.rts = False
            self.ser.open()
        except serial.SerialException as e:
            assert port, "Arduino non détecté"
            raise RuntimeError(f"Impossible de se connecter sur {port} : {e}")

        time.sleep(0.1)
        self.ser.reset_input_buffer()
        line = self.ser.readline().decode("utf-8", errors="ignore").strip()
        if line != "READY":
            raise RuntimeError(f"Réponse inattendue de l'Arduino : {repr(line)}")

        # Thread de lecture des "OK" en arrière-plan (évite le blocage)
        self._lock = threading.Lock()
        self._reader_stop = threading.Event()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self):
        """Lit et jette les réponses Arduino en arrière-plan."""
        while not self._reader_stop.is_set():
            try:
                if self.ser.is_open and self.ser.in_waiting:
                    self.ser.readline()
                else:
                    time.sleep(0.001)
            except Exception:
                break

    def send(self, colors: list[tuple[int, int, int]]) -> None:
        """Envoie une liste de couleurs RGB à l'Arduino (non-bloquant)."""
        if not colors:
            raise ValueError("Liste de couleurs vide.")
        if len(colors) > self.MAX_LEDS:
            raise ValueError(f"Trop de LEDs : {len(colors)} > {self.MAX_LEDS}")

        packet = bytearray()
        packet += self.HEADER
        packet += struct.pack("<H", len(colors))
        for r, g, b in colors:
            packet += bytes([r & 0xFF, g & 0xFF, b & 0xFF])

        with self._lock:
            self.ser.write(packet)
            self.ser.flush()
        # Pas d'attente de "OK" → latence réduite

    def close(self) -> None:
        self._reader_stop.set()
        if self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
