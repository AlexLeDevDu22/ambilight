"""
main.py – Point d'entrée du système Ambilight.

Architecture :
  • Thread principal  : UI Tkinter
  • Thread secondaire : boucle capture → mapping → envoi série

Modes :
  • "screen" : ambilight classique (capture d'écran)
  • "sound"  : visualiseur audio (sounddevice + FFT)

Transitions : interpolation linéaire entre frames consécutives.
"""

import threading
import time
import traceback

import config as cfg_module
from led_strip import LedStrip
from screen_capture import ScreenCapture
from led_mapper import LedMapper
from sound_ambient import SoundAmbient
from ui import AmbilightUI
from mouse import MouseAmbient, get_mouse_position

DOWNSCALE = 4


def _lerp_color(
    prev: list[tuple[int, int, int]],
    curr: list[tuple[int, int, int]],
    alpha: float,
) -> list[tuple[int, int, int]]:
    """
    Interpolation linéaire entre deux listes de couleurs.
    alpha = 0.0 → 100% prev  /  alpha = 1.0 → 100% curr
    """
    result = []
    for (pr, pg, pb), (cr, cg, cb) in zip(prev, curr):
        r = int(pr + (cr - pr) * alpha)
        g = int(pg + (cg - pg) * alpha)
        b = int(pb + (cb - pb) * alpha)
        result.append((r, g, b))
    return result


def _adaptive_lerp_color(
    prev: list[tuple[int, int, int]],
    curr: list[tuple[int, int, int]],
    base_alpha: float,
) -> list[tuple[int, int, int]]:
    """
    Interpolation adaptative : les petits changements de couleur sont
    lissés beaucoup plus fort (évite le flickering), les gros changements
    passent vite (changement de scène, réactivité).
    """
    result = []
    for (pr, pg, pb), (cr, cg, cb) in zip(prev, curr):
        # Distance couleur normalisée (0.0 à 1.0)
        diff = ((cr - pr) ** 2 + (cg - pg) ** 2 + (cb - pb) ** 2) ** 0.5
        max_diff = 441.67  # sqrt(255²*3)
        norm_diff = min(1.0, diff / max_diff)

        # Petit changement → alpha très bas (lissage fort)
        # Gros changement → alpha élevé (réaction rapide)
        # Courbe sigmoïde pour une transition douce
        adaptive_alpha = base_alpha * (0.15 + 0.85 * (norm_diff ** 0.6))

        r = int(pr + (cr - pr) * adaptive_alpha)
        g = int(pg + (cg - pg) * adaptive_alpha)
        b = int(pb + (cb - pb) * adaptive_alpha)
        result.append((r, g, b))
    return result


class AmbilightApp:
    def __init__(self):
        self._cfg = cfg_module.load()
        self._stop_event = threading.Event()
        self._spotify_stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._spotify_thread: threading.Thread | None = None
        self._strip: LedStrip | None = None
        self._capture: ScreenCapture | None = None
        self._sound: SoundAmbient | None = None
        self._mouse_ambient: MouseAmbient | None = None

        self._ui = AmbilightUI(
            cfg=self._cfg,
            on_start=self._start,
            on_stop=self._stop,
            on_save=self._save,
        )

        # Démarrer la surveillance Spotify en arrière-plan
        self._spotify_stop_event.clear()
        self._spotify_thread = threading.Thread(target=self._spotify_background_loop, daemon=True)
        self._spotify_thread.start()

    # ------------------------------------------------------------------
    # Callbacks UI
    # ------------------------------------------------------------------

    def _start(self, cfg: dict):
        """Ouvre la connexion série et lance le thread de capture/son."""
        port = cfg.get("serial_port", "")
        mode = cfg.get("mode", "screen")

        # Connexion Arduino
        self._strip = LedStrip(port)

        if mode == "screen":
            screen_idx = cfg.get("screen_index", 0)
            self._capture = ScreenCapture(screen_index=screen_idx, downscale=DOWNSCALE)
            cfg["_downscale"] = DOWNSCALE
            if cfg.get("mouse_enabled", True):
                self._mouse_ambient = MouseAmbient()
                self._mouse_ambient.start()
        elif mode == "sound":
            device = cfg.get("sound_device", None)
            self._sound = SoundAmbient(cfg)
            self._sound.start(device_index=device)
        elif mode == "responsive":
            pass #TODO

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, args=(cfg,), daemon=True)
        self._thread.start()

    def _stop(self):
        """Arrête proprement le thread et ferme les ressources."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._strip:
            self._strip.close()
            self._strip = None
        if self._capture:
            self._capture.close()
            self._capture = None
        if self._sound:
            self._sound.stop()
            self._sound = None

    def _save(self, cfg: dict):
        cfg_module.save(cfg)

    def _spotify_background_loop(self):
        """Vérifie Spotify en continu, même quand le système n'est pas en cours."""
        from audio_sources import SpotifyAudioDetector
        while not self._spotify_stop_event.is_set():
            try:
                info = SpotifyAudioDetector.get_current_track()
                if info:
                    url, track, artist = info
                    full_track = f"{track} - {artist}" if artist else track
                    self._ui.update_track(full_track, url)
                    if self._sound:
                        self._sound.spotify_track = full_track
                else:
                    self._ui.update_track_cover(None)
                    if self._sound:
                        self._sound.spotify_track = None
            except Exception:
                pass
            # Vérifier toutes les 5 secondes
            for _ in range(50):
                if self._spotify_stop_event.is_set():
                    return
                time.sleep(0.1)

    # ------------------------------------------------------------------
    # Boucle principale (thread secondaire)
    # ------------------------------------------------------------------

    def _loop(self, cfg: dict):
        mode = cfg.get("mode", "screen")

        if mode == "screen":
            self._loop_screen(cfg)
        elif mode == "sound":
            self._loop_sound(cfg)

    def _loop_screen(self, cfg: dict):
        """Boucle ambilight classique avec transitions."""
        mapper = None
        prev_colors: list[tuple[int, int, int]] = []
        last_mouse_status_update = 0.0

        try:
            while not self._stop_event.is_set():
                t0 = time.perf_counter()

                # Mettre à jour la config au démarrage ou si num_leds change
                current_num = self._cfg.get("num_leds", 113)
                if not mapper or mapper._cfg.get("num_leds") != current_num:
                    mapper = LedMapper(self._cfg)
                    prev_colors = [(0, 0, 0)] * current_num

                # 1. Capture
                frame = self._capture.capture()
                mouse_pos = get_mouse_position(self._capture.screen_index)
                if self._mouse_ambient:
                    self._mouse_ambient.update_frame(
                        frame,
                        mouse_pos,
                        int(self._cfg.get("mouse_sample_radius", 180)),
                        DOWNSCALE,
                    )
                    mouse_status = self._mouse_ambient.status
                else:
                    mouse_status = "eclairage souris desactive"
                if t0 - last_mouse_status_update >= 0.2:
                    self._ui.update_mouse_status(mouse_pos, mouse_status)
                    last_mouse_status_update = t0

                # 2. Mapping
                mapper.update_config(self._cfg)
                raw_colors = mapper.map(frame)

                # 3. Transition adaptative (lissage fort pour petits changements, rapide pour gros)
                speed = float(self._cfg.get("transition_speed", 0.5))
                alpha = max(0.01, 1.0 - speed)
                n = self._cfg.get("num_leds", 113)
                raw_colors = raw_colors[:n]
                if len(prev_colors) != n:
                    prev_colors = [(0, 0, 0)] * n

                blended = _adaptive_lerp_color(prev_colors, raw_colors, alpha)
                prev_colors = blended

                # 4. Envoi Arduino
                if self._strip:
                    self._strip.send(blended)

                # 5. FPS réel
                t1 = time.perf_counter()
                elapsed = t1 - t0
                fps_real = 1.0 / max(elapsed, 1e-6)
                self._ui.update_fps(fps_real)

                # 6. Attente FPS
                fps_target = max(1, self._cfg.get("fps", 30))
                interval = 1.0 / fps_target
                sleep_time = interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            self._handle_error(e)
        finally:
            self._cleanup()

    def _loop_sound(self, cfg: dict):
        """Boucle Sound Ambient."""
        prev_colors: list[tuple[int, int, int]] = []

        try:
            while not self._stop_event.is_set():
                t0 = time.perf_counter()

                # Mettre à jour la config
                current_num = self._cfg.get("num_leds", 113)
                if not prev_colors or len(prev_colors) != current_num:
                    prev_colors = [(0, 0, 0)] * current_num

                # 1. Générer couleurs depuis l'audio
                self._sound.update_config(self._cfg)
                raw_colors = self._sound.get_colors()

                # 2. Transition
                speed = float(self._cfg.get("transition_speed", 0.3))
                alpha = max(0.01, 1.0 - speed)

                n = self._cfg.get("num_leds", 113)
                raw_colors = raw_colors[:n]
                if len(raw_colors) < n:
                    raw_colors += [(0, 0, 0)] * (n - len(raw_colors))
                if len(prev_colors) != n:
                    prev_colors = [(0, 0, 0)] * n

                blended = _lerp_color(prev_colors, raw_colors, alpha)
                prev_colors = blended

                # 3. Envoi Arduino
                self._strip.send(blended)

                # 4. Info UI
                t1 = time.perf_counter()
                elapsed = t1 - t0
                fps_real = 1.0 / max(elapsed, 1e-6)
                self._ui.update_fps(fps_real)

                # Afficher la piste Spotify si disponible
                if self._sound:
                    track = self._sound.spotify_track
                    if track:
                        self._ui.update_track(track)
                    else:
                        self._ui.update_track(None)

                fps_target = max(1, self._cfg.get("fps", 30))
                interval = 1.0 / fps_target
                sleep_time = interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as e:
            self._handle_error(e)
        finally:
            self._cleanup()

    def _handle_error(self, e: Exception):
        err_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        print(f"[Ambilight] Erreur : {err_msg}")
        self._ui.set_error(err_msg)

    def _cleanup(self):
        if self._strip:
            self._strip.close()
            self._strip = None
        if self._capture:
            self._capture.close()
            self._capture = None
        if self._sound:
            self._sound.stop()
            self._sound = None
        if self._mouse_ambient:
            self._mouse_ambient.stop()
            self._mouse_ambient = None

    # ------------------------------------------------------------------
    # Lancement
    # ------------------------------------------------------------------

    def run(self):
        self._ui.run()


if __name__ == "__main__":
    AmbilightApp().run()
