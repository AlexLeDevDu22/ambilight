"""
sound_ambient.py – Mode Sound Ambient pour Ambilight.

Analyse audio en temps réel (microphone ou loopback) via sounddevice + FFT.
Génère des couleurs LED basées sur :
  - Les basses (20-200 Hz)  → luminosité / couleur chaude
  - Les médiums (200-2000 Hz) → couleur principale
  - Les aigus (2000-8000 Hz) → flashes blancs / froids

Bonus : tente de récupérer la cover Spotify via AppleScript.
"""

import numpy as np
import colorsys
import threading
import time
import subprocess
import io
from typing import Optional

try:
    import sounddevice as sd
    SOUNDDEVICE_OK = True
except Exception:
    SOUNDDEVICE_OK = False

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False

try:
    import requests
    REQUESTS_OK = True
except Exception:
    REQUESTS_OK = False

from audio_sources import AudioSourceManager, SpotifyAudioDetector


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires couleur
# ─────────────────────────────────────────────────────────────────────────────

def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return _clamp(r * 255), _clamp(g * 255), _clamp(b * 255)


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


# ─────────────────────────────────────────────────────────────────────────────
# Récupération cover Spotify (Mac uniquement)
# ─────────────────────────────────────────────────────────────────────────────

SPOTIFY_SCRIPT = """
tell application "Spotify"
    if player state is playing then
        set artURL to artwork url of current track
        set tName to name of current track
        return artURL & "|||" & tName
    end if
end tell
"""


def _get_spotify_info() -> Optional[tuple[str, str]]:
    """Retourne (artwork_url, track_name) si Spotify joue, sinon None."""
    try:
        result = subprocess.run(
            ["osascript", "-e", SPOTIFY_SCRIPT],
            capture_output=True, text=True, timeout=2
        )
        out = result.stdout.strip()
        if "|||" in out:
            parts = out.split("|||", 1)
            return parts[0].strip(), parts[1].strip()
    except Exception:
        pass
    return None


def _dominant_colors_from_url(url: str, n_colors: int = 3) -> list[tuple[int, int, int]]:
    """Télécharge une image et extrait les n couleurs dominantes (k-means simple)."""
    if not PIL_OK or not REQUESTS_OK:
        return []
    try:
        r = requests.get(url, timeout=3)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img = img.resize((64, 64))
        pixels = np.array(img).reshape(-1, 3).astype(float)

        # K-means minimaliste
        from sklearn.cluster import KMeans  # tentative
        km = KMeans(n_clusters=n_colors, n_init=5, max_iter=50)
        km.fit(pixels)
        centers = km.cluster_centers_.astype(int)
        return [(int(c[0]), int(c[1]), int(c[2])) for c in centers]
    except Exception:
        pass

    # Fallback : médiane simple
    try:
        med = np.median(pixels, axis=0).astype(int)
        return [(int(med[0]), int(med[1]), int(med[2]))]
    except Exception:
        return []


def _dominant_colors_simple(url: str) -> list[tuple[int, int, int]]:
    """Version sans sklearn : palette via quantization PIL."""
    if not PIL_OK or not REQUESTS_OK:
        return []
    try:
        r = requests.get(url, timeout=3)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img = img.resize((64, 64))
        # Quantize à 16 couleurs
        quantized = img.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()  # [R,G,B, R,G,B, ...]
        # Trier par fréquence d'usage
        hist = quantized.histogram()
        pairs = sorted(zip(hist, range(len(hist))), reverse=True)
        colors = []
        for count, idx in pairs[:4]:
            r_val = palette[idx * 3]
            g_val = palette[idx * 3 + 1]
            b_val = palette[idx * 3 + 2]
            # Filtrer les couleurs trop sombres ou trop grises
            h, s, v = _rgb_to_hsv(r_val, g_val, b_val)
            if v > 0.15 and s > 0.1:
                colors.append((r_val, g_val, b_val))
        return colors if colors else [(255, 100, 50)]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Analyseur audio
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024  # ~23ms par bloc


class AudioAnalyzer:
    """
    Analyse audio en temps réel avec support multi-sources.
    Expose bass_level, mid_level, treble_level (0.0–1.0, lissés).
    Supporte: micro, audio système (Mac), Spotify.
    """

    def __init__(self, device=None, mode="mic", sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device = device
        self.mode = mode

        self.bass_level = 0.0
        self.mid_level = 0.0
        self.treble_level = 0.0
        self.volume = 0.0

        self._lock = threading.Lock()
        self._source = None
        self._read_thread = None
        self._smoothing = 0.3  # EMA

        # Historique pour normalisation dynamique (auto-gain)
        self._peak_bass = 0.01
        self._peak_mid = 0.01
        self._peak_treble = 0.01
        self._peak_decay = 0.9995  # décroissance lente

    def start(self):
        try:
            self._source = AudioSourceManager(
                mode=self.mode,
                device_index=self.device,
                sample_rate=self.sample_rate,
                block_size=self.block_size
            )
            self._source.start()
            self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()
        except Exception as e:
            raise RuntimeError(f"Erreur démarrage audio: {e}")

    def stop(self):
        if self._source:
            self._source.stop()
            self._source = None

    def _read_loop(self):
        """Lit en continu depuis la source audio."""
        try:
            while self._source:
                audio = self._source.read_block()
                if audio is not None and len(audio) > 0:
                    self._analyze_block(audio)
        except Exception:
            pass

    def _analyze_block(self, audio: np.ndarray):
        """Analyse un bloc audio."""
        if len(audio) == 0:
            return

        # FFT
        fft_vals = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
        freqs = np.fft.rfftfreq(len(audio), 1.0 / self.sample_rate)

        def band_energy(f_low, f_high):
            mask = (freqs >= f_low) & (freqs < f_high)
            if not np.any(mask):
                return 0.0
            return float(np.mean(fft_vals[mask]))

        bass_raw = band_energy(20, 200)
        mid_raw = band_energy(200, 2000)
        treble_raw = band_energy(2000, 8000)

        # Normalisation dynamique (auto-gain)
        self._peak_bass = max(self._peak_bass * self._peak_decay, bass_raw + 1e-6)
        self._peak_mid = max(self._peak_mid * self._peak_decay, mid_raw + 1e-6)
        self._peak_treble = max(self._peak_treble * self._peak_decay, treble_raw + 1e-6)

        bass_n = min(1.0, bass_raw / self._peak_bass)
        mid_n = min(1.0, mid_raw / self._peak_mid)
        treble_n = min(1.0, treble_raw / self._peak_treble)
        vol_n = float(np.sqrt(np.mean(audio ** 2))) * 20

        # EMA smoothing
        sm = self._smoothing
        with self._lock:
            self.bass_level = self.bass_level * sm + bass_n * (1 - sm)
            self.mid_level = self.mid_level * sm + mid_n * (1 - sm)
            self.treble_level = self.treble_level * sm + treble_n * (1 - sm)
            self.volume = self.volume * sm + min(1.0, vol_n) * (1 - sm)

    def get_levels(self) -> tuple[float, float, float, float]:
        """Retourne (bass, mid, treble, volume) lissés."""
        with self._lock:
            return self.bass_level, self.mid_level, self.treble_level, self.volume

    def switch_mode(self, new_mode: str, device_index: Optional[int] = None):
        """Change le mode/device audio."""
        if self._source:
            self._source.switch_mode(new_mode, device_index)

    @staticmethod
    def list_devices() -> list[dict]:
        """Liste les périphériques audio disponibles."""
        if not SOUNDDEVICE_OK:
            return []
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append({"index": i, "name": d["name"]})
        return devices


# ─────────────────────────────────────────────────────────────────────────────
# Générateur de couleurs LED en mode Sound
# ─────────────────────────────────────────────────────────────────────────────

class SoundColorGenerator:
    """
    Génère la liste de couleurs LED selon l'analyse audio avancée.

    Effets supportés :
    - "spectrum" : Répartition spatiale des fréquences avec dégradé multicolore.
    - "ripples" : Ondes de couleur déclenchées par les basses.
    - "frequency_bars" : Chaque LED représente une bande de fréquence avec sa couleur propre.
    """

    def __init__(self, num_leds: int, cfg: dict):
        self.num_leds = num_leds
        self.cfg = cfg
        self._hue_base = 0.0
        self._hue_drift = 0.0
        self._spotify_hues: list[float] = []
        self._prev_bass = 0.0
        self._time = 0.0
        self._ripples = []
        self._spectrum_smoothed = [0.0] * num_leds

    def set_spotify_palette(self, colors: list[tuple[int, int, int]]):
        """Injecte les couleurs dominantes de la cover Spotify."""
        raw_hues = []
        for r, g, b in colors:
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s > 0.15 and v > 0.1:
                raw_hues.append(h)

        if not raw_hues:
            self._spotify_hues = []
            return

        primary_hue = raw_hues[0]
        filtered_hues = [primary_hue]

        # Filtrer les teintes trop proches pour garantir une "différence"
        for h in raw_hues[1:]:
            too_close = False
            for fh in filtered_hues:
                dist = min(abs(h - fh), 1.0 - abs(h - fh))
                if dist < 0.08:  # 8% de distance min sur le cercle chromatique
                    too_close = True
                    break
            if not too_close:
                filtered_hues.append(h)

        # S'il nous manque des couleurs, on crée des couleurs analogues (éloignées mais pas opposées)
        # 0.12 correspond à une couleur proche mais distincte
        if len(filtered_hues) == 1:
            filtered_hues.append((primary_hue + 0.12) % 1.0)
            filtered_hues.append((primary_hue - 0.12) % 1.0)
        elif len(filtered_hues) == 2:
            filtered_hues.append((filtered_hues[1] + 0.12) % 1.0)

        self._spotify_hues = filtered_hues[:3]

    def _get_palette_hue(self, index: int) -> float:
        if self._spotify_hues:
            return self._spotify_hues[index % len(self._spotify_hues)]
        # Fallback dynamique si pas de palette Spotify
        offsets = [0.0, 0.33, 0.66, 0.15, 0.85]
        return (self._hue_drift + offsets[index % len(offsets)]) % 1.0

    def generate(
        self,
        bass: float,
        mid: float,
        treble: float,
        volume: float,
        dt: float,
    ) -> list[tuple[int, int, int]]:
        self._time += dt
        speed = self.cfg.get("sound_hue_speed", 0.05)
        
        # Effet dynamique : les couleurs tournent beaucoup plus vite quand il y a de grosses basses
        bass_boost = bass ** 3
        dynamic_speed = speed * (1.0 + bass_boost * 10.0)
        self._hue_drift = (self._hue_drift + dt * dynamic_speed) % 1.0

        effect = self.cfg.get("sound_effect", "ripples")

        if effect == "ripples":
            return self._generate_ripples(bass, mid, treble, volume, dt)
        elif effect == "frequency_bars":
            return self._generate_frequency_bars(bass, mid, treble, volume, dt)
        else:
            return self._generate_spectrum(bass, mid, treble, volume, dt)

    def _generate_spectrum(self, bass: float, mid: float, treble: float, volume: float, dt: float) -> list[tuple[int, int, int]]:
        colors = []
        n = self.num_leds
        brightness = float(self.cfg.get("brightness", 1.0))
        sat_boost = float(self.cfg.get("saturation_boost", 1.2))

        # On récupère 3 couleurs distinctes pour créer un beau dégradé
        c1_hue = self._get_palette_hue(0)
        c2_hue = self._get_palette_hue(1)
        c3_hue = self._get_palette_hue(2)

        c1_rgb = _hsv_to_rgb(c1_hue, min(1.0, sat_boost), 1.0)
        c2_rgb = _hsv_to_rgb(c2_hue, min(1.0, sat_boost), 1.0)
        c3_rgb = _hsv_to_rgb(c3_hue, min(1.0, sat_boost), 1.0)

        for i in range(n):
            t = i / max(1, n - 1)  # 0.0 → 1.0 sur le pourtour

            # Distance par rapport aux coins inférieurs (t=0 et t=1)
            dist_bottom = min(t, 1.0 - t) * 2.0  # 0.0 aux extrémités (bas), 1.0 au centre (haut)

            # Création d'un dégradé de couleur fluide sur le ruban
            if dist_bottom < 0.5:
                # Moitié inférieure: dégradé entre couleur 1 et couleur 2
                blend = dist_bottom * 2.0
                base_r = c1_rgb[0] * (1 - blend) + c2_rgb[0] * blend
                base_g = c1_rgb[1] * (1 - blend) + c2_rgb[1] * blend
                base_b = c1_rgb[2] * (1 - blend) + c2_rgb[2] * blend
            else:
                # Moitié supérieure: dégradé entre couleur 2 et couleur 3
                blend = (dist_bottom - 0.5) * 2.0
                base_r = c2_rgb[0] * (1 - blend) + c3_rgb[0] * blend
                base_g = c2_rgb[1] * (1 - blend) + c3_rgb[1] * blend
                base_b = c2_rgb[2] * (1 - blend) + c3_rgb[2] * blend

            # Pondération spatiale de l'intensité
            w_bass = max(0.0, 1.0 - dist_bottom)
            w_mid = 1.0 - abs(dist_bottom - 0.5) * 2.0
            w_treble = dist_bottom

            # Intensités dynamiques (puissance 1.5 pour plus de contraste: "redescend puis repart")
            v_bass = (bass ** 1.5) * w_bass * 1.5
            v_mid = (mid ** 1.5) * w_mid * 1.2
            v_treble = (treble ** 1.5) * w_treble * 1.0

            # Plancher très bas pour que ça s'éteigne presque sans son
            total_v = v_bass + v_mid + v_treble + 0.02

            val = brightness * min(1.0, total_v * 2.0)

            # Application de la luminosité sur la couleur de base (RGB)
            r = _clamp(base_r * val)
            g = _clamp(base_g * val)
            b = _clamp(base_b * val)

            colors.append((r, g, b))

        return colors

    def _generate_frequency_bars(self, bass: float, mid: float, treble: float, volume: float, dt: float) -> list[tuple[int, int, int]]:
        colors = []
        n = self.num_leds
        brightness = float(self.cfg.get("brightness", 1.0))
        sat_boost = float(self.cfg.get("saturation_boost", 1.2))

        c1_hue = self._get_palette_hue(0)
        c2_hue = self._get_palette_hue(1)
        c3_hue = self._get_palette_hue(2)

        for i in range(n):
            t = i / max(1, n - 1)

            if t < 0.4:
                freq_energy = bass * (1.0 - t / 0.4)
                hue = c1_hue
            elif t < 0.7:
                freq_energy = mid * (1.0 - abs(t - 0.55) / 0.15)
                hue = c2_hue
            else:
                freq_energy = treble * ((t - 0.7) / 0.3)
                hue = c3_hue

            freq_energy = freq_energy ** 1.5
            self._spectrum_smoothed[i] = self._spectrum_smoothed[i] * 0.7 + freq_energy * 0.3

            val = brightness * min(1.0, self._spectrum_smoothed[i] * 2.5 + 0.02)
            sat = min(1.0, sat_boost)

            r, g, b = _hsv_to_rgb(hue, sat, val)
            colors.append((r, g, b))

        return colors

    def _generate_ripples(self, bass: float, mid: float, treble: float, volume: float, dt: float) -> list[tuple[int, int, int]]:
        import random
        colors = []
        n = self.num_leds
        brightness = float(self.cfg.get("brightness", 1.0))
        sat_boost = float(self.cfg.get("saturation_boost", 1.2))

        # Détection de beat
        beat = max(0.0, bass - self._prev_bass) > 0.2
        self._prev_bass = bass

        if beat:
            hue = self._get_palette_hue(random.randint(0, 2))
            self._ripples.append({
                "pos": 0.0,
                "speed": 1.0 + random.random() * 0.5,
                "hue": hue,
                "life": 1.0
            })
            self._ripples.append({
                "pos": 1.0,
                "speed": -(1.0 + random.random() * 0.5),
                "hue": hue,
                "life": 1.0
            })

        for r in self._ripples:
            r["pos"] += r["speed"] * dt
            r["life"] -= dt * 0.8

        self._ripples = [r for r in self._ripples if r["life"] > 0]

        # Couleurs de fond en dégradé
        bg1_hue = self._get_palette_hue(0)
        bg2_hue = self._get_palette_hue(1)
        bg1_rgb = _hsv_to_rgb(bg1_hue, min(1.0, sat_boost), 1.0)
        bg2_rgb = _hsv_to_rgb(bg2_hue, min(1.0, sat_boost), 1.0)

        for i in range(n):
            t = i / max(1, n - 1)

            # Dégradé de fond
            blend = min(t, 1.0 - t) * 2.0
            base_r = bg1_rgb[0] * (1 - blend) + bg2_rgb[0] * blend
            base_g = bg1_rgb[1] * (1 - blend) + bg2_rgb[1] * blend
            base_b = bg1_rgb[2] * (1 - blend) + bg2_rgb[2] * blend

            v_bg = 0.05 + (mid ** 1.5) * 0.3
            r, g, b = base_r * v_bg, base_g * v_bg, base_b * v_bg

            # Ondes par-dessus
            for r_obj in self._ripples:
                dist = abs(t - r_obj["pos"])
                if dist < 0.15:
                    intensity = (1.0 - (dist / 0.15)**2) * r_obj["life"]
                    ripple_rgb = _hsv_to_rgb(r_obj["hue"], min(1.0, sat_boost), 1.0)
                    r += ripple_rgb[0] * intensity
                    g += ripple_rgb[1] * intensity
                    b += ripple_rgb[2] * intensity

            r_c = _clamp(r * brightness)
            g_c = _clamp(g * brightness)
            b_c = _clamp(b * brightness)
            colors.append((r_c, g_c, b_c))

        return colors


# ─────────────────────────────────────────────────────────────────────────────
# Gestionnaire principal Sound Ambient
# ─────────────────────────────────────────────────────────────────────────────

class SoundAmbient:
    """
    Interface principale du mode Sound Ambient.
    Supporte: micro, audio système, Spotify detection.
    """

    def __init__(self, cfg: dict):
        self._cfg = cfg
        audio_mode = cfg.get("audio_source", "mic")
        self._analyzer = AudioAnalyzer(sample_rate=SAMPLE_RATE, block_size=BLOCK_SIZE, mode=audio_mode)
        self._generator: Optional[SoundColorGenerator] = None
        self._last_t = time.perf_counter()
        self._running = False

        # Spotify
        self._spotify_track: Optional[str] = None
        self._spotify_cover_url: Optional[str] = None
        self._spotify_thread: Optional[threading.Thread] = None

    def start(self, device_index=None):
        num_leds = self._cfg.get("num_leds", 113)
        self._generator = SoundColorGenerator(num_leds, self._cfg)
        self._analyzer.device = device_index
        self._analyzer.start()
        self._running = True
        self._last_t = time.perf_counter()

        # Lancer la récupération Spotify en arrière-plan
        self._spotify_thread = threading.Thread(
            target=self._spotify_loop, daemon=True
        )
        self._spotify_thread.start()

        print(f"[SoundAmbient] Démarré avec mode audio: {self._cfg.get('audio_source', 'mic')}")

    def stop(self):
        self._running = False
        self._analyzer.stop()

    def update_config(self, cfg: dict):
        self._cfg = cfg
        if self._generator:
            self._generator.cfg = cfg
            self._generator.num_leds = cfg.get("num_leds", 113)

    def get_colors(self) -> list[tuple[int, int, int]]:
        """Retourne la liste de couleurs LED actuelle avec intensité appliquée."""
        if not self._generator:
            num = self._cfg.get("num_leds", 113)
            return [(0, 0, 0)] * num

        bass, mid, treble, volume = self._analyzer.get_levels()

        # Appliquer l'intensité audio (amplification/atténuation)
        audio_intensity = float(self._cfg.get("audio_intensity", 1.0))
        bass = min(1.0, bass * audio_intensity)
        mid = min(1.0, mid * audio_intensity)
        treble = min(1.0, treble * audio_intensity)

        now = time.perf_counter()
        dt = now - self._last_t
        self._last_t = now

        colors = self._generator.generate(bass, mid, treble, volume, dt)

        # ====== EFFET EXPLOSION DE BASSES ======
        # 1. Contraste dynamique : on assombrit l'image globale quand il n'y a pas de basse
        base_dimming = 0.3 + (bass * 0.7)  # 30% de luminosité mini, 100% avec pleine basse
        
        # 2. Flash d'explosion pour les basses très fortes (> 0.7)
        bass_flash = max(0.0, bass - 0.7) / 0.3  # De 0.0 à 1.0
        explosion_multiplier = 1.0 + (bass_flash * 2.5)  # Multiplie jusqu'à x3.5
        white_mix = bass_flash * 0.6  # Mix jusqu'à 60% de blanc pur pour l'éblouissement
        
        realtime_brightness = float(self._cfg.get("realtime_brightness", 1.0))
        
        final_colors = []
        for r, g, b in colors:
            r_dim = r * base_dimming
            g_dim = g * base_dimming
            b_dim = b * base_dimming
            
            if white_mix > 0:
                r_dim += (255 - r_dim) * white_mix
                g_dim += (255 - g_dim) * white_mix
                b_dim += (255 - b_dim) * white_mix
                
            r_final = min(255, int(r_dim * realtime_brightness * explosion_multiplier))
            g_final = min(255, int(g_dim * realtime_brightness * explosion_multiplier))
            b_final = min(255, int(b_dim * realtime_brightness * explosion_multiplier))
            
            final_colors.append((r_final, g_final, b_final))
            
        return final_colors

    def _spotify_loop(self):
        """Vérifie Spotify toutes les 5s et met à jour la palette."""
        while self._running:
            try:
                info = SpotifyAudioDetector.get_current_track()
                if info:
                    url, track, artist = info
                    full_track = f"{track}" if not artist else f"{track} - {artist}"
                    if full_track != self._spotify_track:
                        self._spotify_track = full_track
                        colors = _dominant_colors_simple(url)
                        if colors and self._generator:
                            self._generator.set_spotify_palette(colors)
                else:
                    # Plus de Spotify → palette libre
                    self._spotify_track = None
                    if self._generator:
                        self._generator.set_spotify_palette([])
            except Exception:
                pass
            for _ in range(50):  # 5s en petits morceaux
                if not self._running:
                    return
                time.sleep(0.1)

    @property
    def spotify_track(self) -> Optional[str]:
        return self._spotify_track

    @staticmethod
    def list_audio_devices() -> list[dict]:
        return AudioAnalyzer.list_devices()
