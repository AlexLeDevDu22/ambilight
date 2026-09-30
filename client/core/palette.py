"""
palette.py – Palettes de couleurs : presets génériques + cover Spotify.

La cover du morceau en cours est récupérée via AppleScript (sans jamais
lancer Spotify s'il est fermé), puis réduite à 3-5 couleurs vives et
harmonieuses, adaptées aux LEDs.
"""

import colorsys
import io
import os
import ssl
import subprocess
import threading
import time
import urllib.request

import numpy as np

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False


PRESETS: dict[str, dict] = {
    "sunset": {"label": "Sunset", "colors": ["#ff4e50", "#ff8a4c", "#ffc05c", "#e0457b", "#8a3ffc"]},
    "ocean":  {"label": "Océan",  "colors": ["#00c6ff", "#0066ff", "#00e5a0", "#6a5cff", "#00ffd5"]},
    "aurora": {"label": "Aurore", "colors": ["#00ffa3", "#03e1ff", "#b01fff", "#6b2ff7", "#00ff6a"]},
    "neon":   {"label": "Néon",   "colors": ["#ff00a0", "#00f0ff", "#fff200", "#8a00ff", "#00ff6a"]},
    "forest": {"label": "Forêt",  "colors": ["#9be15d", "#00b09b", "#f7b733", "#2ecc71", "#c6ff00"]},
    "candy":  {"label": "Candy",  "colors": ["#ff7eb3", "#ffb86c", "#a18cff", "#ff5ecd", "#7afcff"]},
    "fire":   {"label": "Feu",    "colors": ["#ff1a00", "#ff5a00", "#ff9a00", "#ffd000", "#ff0055"]},
}
FALLBACK_PRESET = "sunset"


def _ssl_context() -> ssl.SSLContext:
    """Le Python de python.org n'embarque pas de certificats : on prend
    certifi s'il est là, sinon ceux du système macOS."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


_SSL = _ssl_context()


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(c) -> str:
    r, g, b = (max(0, min(255, int(round(x * 255)))) for x in c)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


class Palette:
    """Liste de couleurs (float 0-1) avec helpers de dégradé."""

    def __init__(self, colors: list, name: str = ""):
        arr = np.array([hex_to_rgb(c) if isinstance(c, str) else c for c in colors], dtype=np.float32)
        if arr.size == 0:
            arr = np.array([hex_to_rgb(c) for c in PRESETS[FALLBACK_PRESET]["colors"]], dtype=np.float32)
        self.colors = arr
        self.name = name

    def __len__(self):
        return len(self.colors)

    def color(self, i: int) -> np.ndarray:
        return self.colors[i % len(self.colors)]

    def sample(self, t: np.ndarray | float, cyclic: bool = True) -> np.ndarray:
        """Couleur(s) interpolée(s) en douceur (t dans [0,1), cyclique)."""
        t = np.asarray(t, dtype=np.float32)
        k = len(self.colors)
        if k == 1:
            return np.broadcast_to(self.colors[0], t.shape + (3,)).copy()
        if cyclic:
            pos = (t % 1.0) * k
            i0 = np.floor(pos).astype(int) % k
            i1 = (i0 + 1) % k
        else:
            pos = np.clip(t, 0, 1) * (k - 1)
            i0 = np.clip(np.floor(pos).astype(int), 0, k - 1)
            i1 = np.clip(i0 + 1, 0, k - 1)
        f = pos - np.floor(pos)
        f = f * f * (3 - 2 * f)  # smoothstep : transitions plus douces
        return self.colors[i0] * (1 - f)[..., None] + self.colors[i1] * f[..., None]

    def hex(self) -> list[str]:
        return [rgb_to_hex(c) for c in self.colors]


def _vivid(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """Rend une couleur de cover exploitable en LED (pas de gris terne)."""
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    s = min(1.0, max(0.6, s * 1.35))
    v = max(0.85, v)
    return colorsys.hsv_to_rgb(h, s, v)


def palette_from_image(img: "Image.Image") -> list[str]:
    img = img.convert("RGB").resize((72, 72))
    q = img.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = q.getcolors() or []  # [(count, index)]
    total = sum(c for c, _ in counts) or 1
    scored = []
    for count, idx in counts:
        rgb = tuple(pal[idx * 3 + j] / 255.0 for j in range(3))
        h, s, v = colorsys.rgb_to_hsv(*rgb)
        # Les couleurs vives et présentes gagnent, le gris/noir perd.
        score = (count / total) * (0.15 + s) ** 1.5 * (0.2 + v)
        scored.append((score, h, s, v, rgb))
    scored.sort(reverse=True)

    chosen = []
    for score, h, s, v, rgb in scored:
        if s < 0.18 or v < 0.18:
            continue
        if all(_hue_dist(h, c[0]) > 0.05 for c in chosen):
            chosen.append((h, rgb))
        if len(chosen) == 5:
            break

    if not chosen:
        # Cover en noir & blanc : on garde un duo froid élégant.
        return ["#7b5cff", "#00d4ff", "#ff4d6d"]

    base_h = chosen[0][0]
    # Compléter avec des teintes analogues pour garder l'harmonie.
    step = 0.07
    while len(chosen) < 3:
        n = len(chosen)
        h = (base_h + step * (1 if n % 2 else -1) * ((n + 1) // 2)) % 1.0
        chosen.append((h, colorsys.hsv_to_rgb(h, 0.85, 1.0)))

    # Ordre harmonieux : par teinte autour de la couleur dominante.
    chosen.sort(key=lambda c: (c[0] - base_h) % 1.0)
    return [rgb_to_hex(_vivid(rgb)) for _, rgb in chosen]


class SpotifyWatcher:
    """Surveille le morceau Spotify en cours et extrait la palette de la cover."""

    SCRIPT = (
        'if application "Spotify" is running then\n'
        '  tell application "Spotify"\n'
        '    if player state is playing then\n'
        '      return (artwork url of current track) & "|||" & (name of current track) & "|||" & (artist of current track)\n'
        '    end if\n'
        '  end tell\n'
        'end if\n'
        'return ""'
    )
    POLL = 2.0

    def __init__(self):
        self._lock = threading.Lock()
        self.track: str | None = None
        self.artist: str | None = None
        self.cover_url: str | None = None
        self.colors: list[str] | None = None
        self.version = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="spotify", daemon=True)
        self._cache: dict[str, list[str]] = {}

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "playing": self.track is not None,
                "track": self.track,
                "artist": self.artist,
                "cover": self.cover_url,
                "colors": self.colors,
            }

    def _query(self):
        try:
            r = subprocess.run(["osascript", "-e", self.SCRIPT], capture_output=True, text=True, timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            return None
        parts = r.stdout.strip().split("|||")
        if len(parts) >= 3 and parts[0].strip():
            return parts[0].strip(), parts[1].strip(), parts[2].strip()
        return None

    def _extract(self, url: str) -> list[str] | None:
        if url in self._cache:
            return self._cache[url]
        if not PIL_OK:
            return None
        try:
            with urllib.request.urlopen(url, timeout=4, context=_SSL) as resp:
                data = resp.read()
            colors = palette_from_image(Image.open(io.BytesIO(data)))
        except Exception as e:
            print(f"[spotify] cover illisible : {e}")
            return None
        self._cache[url] = colors
        if len(self._cache) > 64:
            self._cache.pop(next(iter(self._cache)))
        return colors

    def _run(self):
        while not self._stop.is_set():
            info = self._query()
            if info is None:
                with self._lock:
                    if self.track is not None:
                        self.track = self.artist = self.cover_url = None
                        self.colors = None
                        self.version += 1
            else:
                url, track, artist = info
                if url != self.cover_url or track != self.track:
                    colors = self._extract(url)
                    with self._lock:
                        self.cover_url, self.track, self.artist = url, track, artist
                        if colors:
                            self.colors = colors
                        self.version += 1
            self._stop.wait(self.POLL)


class BlendPalette(Palette):
    """Fondu entre deux palettes (f = 0 → a, f = 1 → b)."""

    def __init__(self, a: Palette, b: Palette, f: float):
        self.a, self.b, self.f = a, b, f
        self.name = b.name
        k = max(len(a), len(b))
        self.colors = np.array([self.color(i) for i in range(k)], dtype=np.float32)

    def color(self, i: int) -> np.ndarray:
        return self.a.color(i) * (1 - self.f) + self.b.color(i) * self.f

    def sample(self, t, cyclic: bool = True) -> np.ndarray:
        return self.a.sample(t, cyclic) * (1 - self.f) + self.b.sample(t, cyclic) * self.f


class PaletteProvider:
    """Résout le nom de palette choisi ('cover' ou preset) en Palette.

    Quand la pochette change (morceau suivant), on passe en fondu de
    l'ancienne palette à la nouvelle au lieu de sauter d'un coup.
    """

    FADE = 2.0

    def __init__(self, spotify: SpotifyWatcher):
        self.spotify = spotify
        self._cache: dict[tuple, Palette] = {}
        self._lock = threading.Lock()
        self._cover_target: Palette | None = None
        self._cover_prev: Palette | None = None
        self._cover_t0 = 0.0

    def _preset(self, name: str) -> Palette:
        preset = PRESETS.get(name) or PRESETS[FALLBACK_PRESET]
        key = ("preset", name)
        if key not in self._cache:
            self._cache[key] = Palette(preset["colors"], name)
        return self._cache[key]

    def _cover(self) -> Palette:
        colors = self.spotify.colors
        target = Palette(colors, "cover") if colors else self._preset(FALLBACK_PRESET)
        now = time.monotonic()
        with self._lock:
            cur = self._cover_target
            if cur is None:
                self._cover_target = target
            elif target.hex() != cur.hex():
                # Départ du fondu depuis ce qui est affiché maintenant
                self._cover_prev = self._blend_now(now) if self._cover_prev else cur
                self._cover_target = target
                self._cover_t0 = now
            return self._blend_now(now)

    def _blend_now(self, now: float) -> Palette:
        prev, target = self._cover_prev, self._cover_target
        if prev is None:
            return target
        f = (now - self._cover_t0) / self.FADE
        if f >= 1.0:
            self._cover_prev = None
            return target
        f = f * f * (3 - 2 * f)
        return BlendPalette(prev, target, f)

    def get(self, name: str) -> Palette:
        if name == "cover":
            return self._cover()
        return self._preset(name)
