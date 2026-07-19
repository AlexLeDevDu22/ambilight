"""
audio_sources.py – Gestion des sources audio (micro, système, Spotify).

Supporte sur Mac:
  - Microphone standard (sounddevice)
  - Audio système (via loopback device ou ffmpeg)
  - Détection Spotify (via AppleScript ou spicetify)
"""

import subprocess
import threading
import time
import numpy as np
from typing import Optional, Callable

try:
    import sounddevice as sd
    SOUNDDEVICE_OK = True
except Exception:
    SOUNDDEVICE_OK = False


class AudioSourceBase:
    """Interface de base pour les sources audio."""

    def __init__(self, sample_rate: int = 44100, block_size: int = 1024):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._running = False

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def read_block(self) -> np.ndarray:
        raise NotImplementedError


class MicrophoneSource(AudioSourceBase):
    """Capture audio depuis le microphone via sounddevice."""

    def __init__(self, device_index: Optional[int] = None, **kwargs):
        super().__init__(**kwargs)
        if not SOUNDDEVICE_OK:
            raise RuntimeError("sounddevice non disponible")
        self.device_index = device_index
        self._stream = None
        self._buffer = None
        self._buffer_ready = threading.Event()

    def start(self):
        self._stream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._running = True

    def stop(self):
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _audio_callback(self, indata, frames, time_info, status):
        self._buffer = indata[:, 0].copy()
        self._buffer_ready.set()

    def read_block(self) -> np.ndarray:
        """Attend et retourne un bloc audio du micro."""
        self._buffer_ready.wait(timeout=1.0)
        self._buffer_ready.clear()
        return self._buffer if self._buffer is not None else np.zeros(self.block_size, dtype=np.float32)

    @staticmethod
    def list_devices() -> list[dict]:
        if not SOUNDDEVICE_OK:
            return []
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append({"index": i, "name": d["name"]})
        return devices

import threading
from typing import Optional

import numpy as np
import sounddevice as sd


class SystemAudioSourceBlackHole(AudioSourceBase):
    """Capture l'audio système via BlackHole."""

    def __init__(self, device_index: Optional[int] = None, **kwargs):
        super().__init__(**kwargs)

        self.device_index = device_index
        self._stream = None

        self._buffer = None
        self._buffer_ready = threading.Event()

    def _find_blackhole_device(self):
        """Trouve automatiquement BlackHole."""
        for i, d in enumerate(sd.query_devices()):
            name = d["name"].lower()

            if (
                "blackhole" in name
                and d["max_input_channels"] > 0
            ):
                return i

        raise RuntimeError(
            "BlackHole introuvable. Vérifie qu'il est installé."
        )

    def start(self):

        if self.device_index is None:
            self.device_index = self._find_blackhole_device()

        info = sd.query_devices(self.device_index)

        channels = min(
            2,
            int(info["max_input_channels"])
        )

        self._stream = sd.InputStream(
            device=self.device_index,
            channels=channels,
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            dtype="float32",
            callback=self._audio_callback,
        )

        self._stream.start()
        self._running = True

        print(
            f"[SystemAudio] Capture via {info['name']}"
        )

    def stop(self):

        self._running = False

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

            self._stream = None

    def _audio_callback(
        self,
        indata,
        frames,
        time_info,
        status,
    ):
        if status:
            return

        # BlackHole est généralement stéréo.
        # Conversion en mono pour rester compatible
        # avec MicrophoneSource.
        if indata.ndim == 2:
            audio = np.mean(
                indata,
                axis=1,
                dtype=np.float32
            )
        else:
            audio = indata.copy()

        self._buffer = audio.astype(np.float32)
        self._buffer_ready.set()

    def read_block(self) -> np.ndarray:
        """Retourne un bloc audio système."""

        self._buffer_ready.wait(timeout=1.0)
        self._buffer_ready.clear()

        if self._buffer is not None:
            return self._buffer

        return np.zeros(
            self.block_size,
            dtype=np.float32,
        )

    @staticmethod
    def list_devices():

        devices = []

        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append(
                    {
                        "index": i,
                        "name": d["name"],
                    }
                )

        return devices


class SpotifyAudioDetector:
    """
    Détecte et capture l'audio Spotify sur macOS.
    Utilise AppleScript pour extraire les infos du track en cours.
    """

    SPOTIFY_SCRIPT = """
    tell application "Spotify"
        if player state is playing then
            set artURL to artwork url of current track
            set tName to name of current track
            set tArtist to artist of current track
            return artURL & "|||" & tName & "|||" & tArtist
        end if
    end tell
    """

    @staticmethod
    def get_current_track() -> Optional[tuple[str, str, str]]:
        """Retourne (artwork_url, track_name, artist) si Spotify joue."""
        try:
            result = subprocess.run(
                ["osascript", "-e", SpotifyAudioDetector.SPOTIFY_SCRIPT],
                capture_output=True, text=True, timeout=2
            )
            out = result.stdout.strip()
            if "|||" in out and out:
                parts = out.split("|||")
                if len(parts) >= 3:
                    url = parts[0].strip()
                    name = parts[1].strip()
                    artist = parts[2].strip()
                    if url and name:  # Valider les données
                        return url, name, artist
        except Exception:
            pass
        return None

    @staticmethod
    def is_spotify_playing() -> bool:
        """Vérifie si Spotify est en lecture."""
        return SpotifyAudioDetector.get_current_track() is not None


class AudioSourceManager:
    """Gère les sources audio selon la configuration."""

    MODES = {
        "system": SystemAudioSourceBlackHole,
        "mic": MicrophoneSource,
    }

    def __init__(self, mode: str = "system", device_index: Optional[int] = None, **kwargs):
        self.mode = mode
        self.device_index = device_index
        self.kwargs = kwargs
        self._source: Optional[AudioSourceBase] = None
        self._create_source()

    def _create_source(self):
        if self.mode == "system":
            self._source = SystemAudioSourceBlackHole(**self.kwargs)
        elif self.mode == "mic":
            self._source = MicrophoneSource(device_index=self.device_index, **self.kwargs)
        else:
            raise ValueError(f"Mode audio inconnu: {self.mode}. Modes disponibles: {list(self.MODES.keys())}")

    def start(self):
        if self._source:
            self._source.start()

    def stop(self):
        if self._source:
            self._source.stop()

    def read_block(self) -> np.ndarray:
        if self._source:
            return self._source.read_block()
        return np.zeros(self.kwargs.get("block_size", 1024), dtype=np.float32)

    def switch_mode(self, mode: str, device_index: Optional[int] = None):
        """Change la source audio."""
        if self._source:
            self._source.stop()
        self.mode = mode
        self.device_index = device_index
        self._create_source()
        self._source.start()

    @staticmethod
    def get_available_modes() -> list[str]:
        """Retourne les modes audio disponibles."""
        modes = ["mic"]
        if SOUNDDEVICE_OK:
            modes.append("system")
        return modes
