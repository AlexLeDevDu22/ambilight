"""
audio.py – Analyse audio temps réel partagée (BlackHole par défaut).

Un seul flux audio pour tout le monde (ruban + souris). L'analyse est faite
directement dans le callback sounddevice (~94 fois/s) : pas de thread de
lecture intermédiaire, latence minimale.

Expose un snapshot :
  bass / mid / high  : enveloppes 0-1 (attaque rapide, relâche douce)
  energy             : niveau global lissé (~1 s), pour les vitesses
  spectrum           : 16 bandes log 0-1
  beat_count / beat_strength   : coups de basse (kick)
  snare_count / snare_strength : attaques dans les aigus (snare, clap)
Les compteurs sont monotones : chaque consommateur détecte ses propres
nouveaux beats sans se marcher dessus.
"""

import threading
import time

import numpy as np

from .audio_output import TARGET_NAME, OutputRouter

try:
    import sounddevice as sd
    SD_OK = True
except Exception:  # PortAudio absent
    sd = None
    SD_OK = False

# Détection des kicks : moyenne de référence des basses, rapport et niveau min.
BEAT_AVG = 0.015
BEAT_RATIO = 1.25
BEAT_MIN = 0.35
BEAT_RISE = 1.6   # montée brutale en ~20 ms (un kick) ≠ basse qui ondule lentement

N_BANDS = 16
WINDOW = 2048
BLOCK = 512


class AudioAnalyzer:
    def __init__(self):
        self._lock = threading.Lock()        # cycle de vie du flux
        self._state_lock = threading.Lock()  # état d'analyse (callback)
        self._users = 0
        self._stream = None
        self.status = "inactif"
        self.device_name: str | None = None
        self._last_try = 0.0
        self._silent_since: float | None = time.monotonic()
        self.router = OutputRouter()
        self.route_msg = ""
        self._reset_state(48000)

    # ------------------------------------------------------------------
    # Cycle de vie (compteur de références)
    # ------------------------------------------------------------------

    def acquire(self):
        with self._lock:
            self._users += 1
            if self._users == 1:
                # Sortie macOS → « Ambilight » (enceintes + BlackHole)
                self.route_msg = self.router.engage()
            if self._stream is None:
                self._open()

    def release(self):
        with self._lock:
            self._users = max(0, self._users - 1)
            if self._users == 0:
                self._close()
                self.router.restore()
                self.status = "inactif"

    def ensure(self):
        """Relance le flux s'il est tombé (BlackHole retiré, veille…)."""
        with self._lock:
            if self._users == 0:
                return
            alive = self._stream is not None and self._stream.active
            if not alive and time.monotonic() - self._last_try > 2.0:
                self._close()
                self._open()

    def _find_device(self):
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if "blackhole" in d["name"].lower() and d["max_input_channels"] > 0:
                return i, d
        idx = sd.default.device[0]
        if idx is not None and idx >= 0:
            return idx, devices[idx]
        raise RuntimeError("aucune entrée audio")

    def _open(self):
        self._last_try = time.monotonic()
        if not SD_OK:
            self.status = "sounddevice indisponible"
            return
        try:
            idx, info = self._find_device()
            sr = int(info["default_samplerate"]) or 48000
            self._reset_state(sr)
            self._stream = sd.InputStream(
                device=idx,
                channels=min(2, int(info["max_input_channels"])),
                samplerate=sr,
                blocksize=BLOCK,
                dtype="float32",
                latency="low",
                callback=self._callback,
            )
            self._stream.start()
            self.device_name = info["name"]
            blackhole = "blackhole" in info["name"].lower()
            self.status = info["name"] if blackhole else f"{info['name']} (BlackHole introuvable)"
        except Exception as e:
            self._stream = None
            self.status = f"audio indisponible : {e}"

    def _close(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    # ------------------------------------------------------------------
    # Analyse
    # ------------------------------------------------------------------

    def _reset_state(self, sr: int):
        self.sr = sr
        self._buf = np.zeros(WINDOW, dtype=np.float32)
        self._win = np.hanning(WINDOW).astype(np.float32)
        freqs = np.fft.rfftfreq(WINDOW, 1.0 / sr)
        edges = np.geomspace(30, 12000, N_BANDS + 1)
        idx = np.searchsorted(freqs, edges)
        for i in range(1, len(idx)):  # au moins un bin FFT par bande
            idx[i] = max(idx[i], idx[i - 1] + 1)
        self._band_idx = idx[:-1]
        self._band_end = idx[-1]
        centers = np.sqrt(edges[:-1] * edges[1:])
        self._bass_bands = centers < 150
        self._mid_bands = (centers >= 150) & (centers < 2000)
        self._high_bands = centers >= 2000

        self._band_peak = np.full(N_BANDS, 1e-3, dtype=np.float32)
        self._peaks = {"bass": 1e-3, "mid": 1e-3, "high": 1e-3, "rms": 1e-4}
        self._bass_avg = 0.0
        self._bass_hist = [0.0, 0.0, 0.0]
        self._high_prev = np.zeros(int(self._high_bands.sum()), dtype=np.float32)
        self._flux_avg = 0.0
        self._clock = 0.0
        self._last_beat = -1.0
        self._last_snare = -1.0
        self._state = {
            "bass": 0.0, "mid": 0.0, "high": 0.0, "energy": 0.0,
            "spectrum": np.zeros(N_BANDS, dtype=np.float32),
            "beat_count": 0, "beat_strength": 0.0,
            "snare_count": 0, "snare_strength": 0.0,
            "silent": True,
        }

    def _norm(self, key: str, value: float, decay: float = 0.9993, floor: float = 1e-3) -> float:
        p = max(self._peaks[key] * decay, value, floor)
        self._peaks[key] = p
        return value / p

    def _callback(self, indata, frames, time_info, status):
        try:
            mono = indata.mean(axis=1) if indata.ndim == 2 else indata
            n = len(mono)
            self._buf = np.roll(self._buf, -n)
            self._buf[-n:] = mono
            self._clock += n / self.sr  # horloge audio (indépendante du scheduling)
            self._analyze(float(np.sqrt(np.mean(mono * mono))))
        except Exception:
            pass

    def _analyze(self, rms: float):
        now = self._clock
        spec = np.abs(np.fft.rfft(self._buf * self._win))
        power = spec[: self._band_end] ** 2
        bands = np.sqrt(np.add.reduceat(power, self._band_idx) / np.diff(np.append(self._band_idx, self._band_end)))

        st = self._state
        silent = rms < 2e-4
        if silent:
            if self._silent_since is None:
                self._silent_since = time.monotonic()
        else:
            self._silent_since = None

        # Spectre normalisé par bande (auto-gain lent)
        self._band_peak = np.maximum(self._band_peak * 0.9994, np.maximum(bands, 1e-3))
        spectrum = np.clip(bands / self._band_peak, 0, 1) ** 0.9

        bass_raw = float(bands[self._bass_bands].mean())
        mid_raw = float(bands[self._mid_bands].mean())
        high_raw = float(bands[self._high_bands].mean())
        bass = min(1.0, self._norm("bass", bass_raw)) ** 1.3
        mid = min(1.0, self._norm("mid", mid_raw))
        high = min(1.0, self._norm("high", high_raw))
        loud = min(1.0, self._norm("rms", rms, 0.9996, 1e-4))

        if silent:
            bass = mid = high = loud = 0.0
            spectrum = spectrum * 0.0

        # --- Kick : basse nettement au-dessus de sa moyenne récente
        self._bass_avg = self._bass_avg * (1 - BEAT_AVG) + bass_raw * BEAT_AVG
        ratio = bass_raw / (self._bass_avg + 1e-6)
        rise = bass_raw / (min(self._bass_hist) + 1e-6)
        self._bass_hist = self._bass_hist[1:] + [bass_raw]
        beat_strength = st["beat_strength"] * 0.9
        beat_count = st["beat_count"]
        if not silent and ratio > BEAT_RATIO and rise > BEAT_RISE and bass > BEAT_MIN and now - self._last_beat > 0.14:
            self._last_beat = now
            beat_count += 1
            beat_strength = min(1.0, 0.15 + 0.2 * float(np.log2(ratio)) + 0.35 * bass)

        # --- Snare / clap : flux spectral positif dans les aigus
        highs = bands[self._high_bands]
        flux = float(np.maximum(highs - self._high_prev, 0).sum())
        self._high_prev = highs
        self._flux_avg = self._flux_avg * 0.95 + flux * 0.05
        snare_strength = st["snare_strength"] * 0.88
        snare_count = st["snare_count"]
        if not silent and flux > self._flux_avg * 2.2 and high > 0.4 and now - self._last_snare > 0.1:
            self._last_snare = now
            snare_count += 1
            snare_strength = min(1.0, 0.4 + high * 0.6)

        def env(prev, new, release):
            return new if new > prev else prev * release + new * (1 - release)

        with self._state_lock:
            st["bass"] = env(st["bass"], bass, 0.86)
            st["mid"] = env(st["mid"], mid, 0.9)
            st["high"] = env(st["high"], high, 0.85)
            st["energy"] = st["energy"] * 0.985 + (0.5 * loud + 0.3 * bass + 0.2 * mid) * 0.015
            st["spectrum"] = np.maximum(spectrum, st["spectrum"] * 0.88)
            st["beat_count"], st["beat_strength"] = beat_count, beat_strength
            st["snare_count"], st["snare_strength"] = snare_count, snare_strength
            st["silent"] = silent

    @property
    def active(self) -> bool:
        return self._users > 0

    def silent_for(self) -> float:
        """Depuis combien de secondes BlackHole ne reçoit rien."""
        if self._stream is None:
            return 0.0
        since = self._silent_since
        return 0.0 if since is None else time.monotonic() - since

    def hint(self, music_playing: bool) -> str:
        """Message pour l'utilisateur si la musique joue mais rien n'arrive."""
        if not self.active:
            return ""
        if self._stream is None:
            return self.status
        if not music_playing or self.silent_for() < 2.5:
            return ""
        if not self.router.target_exists and self.route_msg:
            return (f"Aucun son capté : crée une sortie multiple « {TARGET_NAME} » "
                    "(enceintes + BlackHole) dans Configuration audio et MIDI.")
        if self.router.current_name().strip().lower() != TARGET_NAME.lower():
            return f"Aucun son capté : choisis la sortie audio « {TARGET_NAME} » dans le menu son de macOS."
        return ("La musique joue mais BlackHole ne reçoit rien : autorise le micro pour le Terminal "
                "(Réglages › Confidentialité et sécurité › Micro).")

    def snapshot(self) -> dict:
        with self._state_lock:
            s = dict(self._state)
            s["spectrum"] = self._state["spectrum"].copy()
        return s
