"""
ui.py – Interface Tkinter pour le système Ambilight.

Modes :
  • Screen Ambient : capture d'écran classique
  • Sound Ambient  : visualiseur audio
  • Responsive     : react au touche

Contrôles communs :
  • Bouton ON / OFF, FPS, Brightness, Gamma, Saturation
  • Vitesse de transition (nouveau)
  • Sélecteur de mode (nouveau)

Contrôles Sound Ambient :
  • Sélecteur de périphérique audio (nouveau)
  • Vitesse de drift de teinte (nouveau)
  • Affichage piste Spotify (nouveau)
"""

import tkinter as tk
from tkinter import ttk, messagebox
import glob
from typing import Callable, Optional

try:
    from sound_ambient import SoundAmbient
    SOUND_OK = True
except Exception:
    SOUND_OK = False

try:
    from PIL import Image, ImageTk
    import io
    import glob
    PIL_OK = True
except Exception:
    PIL_OK = False


# ─────────────────────────────────────────────────────────────────────────────
# Palette de couleurs UI
# ─────────────────────────────────────────────────────────────────────────────

BG      = "#0d0d1a"
PANEL   = "#13132a"
PANEL2  = "#1a1a38"
ACCENT  = "#e94560"
ACCENT2 = "#7b5ea7"
GREEN   = "#00c896"
FG      = "#eaeaea"
LABEL_FG = "#8899bb"
BORDER  = "#2a2a4a"


class AmbilightUI:
    def __init__(
        self,
        cfg: dict,
        on_start: Callable,
        on_stop: Callable,
        on_save: Callable[[dict], None],
    ):
        self._cfg = cfg
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_save = on_save
        self._running = False
        self._current_cover_image = None
        self._spotify_cover_photo = None

        self.root = tk.Tk()
        self.root.title("🎨 Ambilight Controller")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)

        self._build_ui()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # ── En-tête ───────────────────────────────────────────────────
        header = tk.Frame(root, bg=BG, pady=0)
        header.pack(fill="x")

        tk.Label(
            header, text="✦  AMBILIGHT  ✦",
            bg=BG, fg=ACCENT, font=("Helvetica", 18, "bold"),
        ).pack()
        tk.Label(
            header, text="Contrôleur d'éclairage d'ambiance",
            bg=BG, fg=LABEL_FG, font=("Helvetica", 10),
        ).pack()

        # Séparateur
        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=16)

        # ── Corps ─────────────────────────────────────────────────────
        body = tk.Frame(root, bg=BG, padx=16, pady=8)
        body.pack(fill="both")

        left_col = tk.Frame(body, bg=BG)
        left_col.grid(row=0, column=0, padx=(0, 8), sticky="n")
        right_col = tk.Frame(body, bg=BG)
        right_col.grid(row=0, column=1, padx=(8, 0), sticky="n")

        # ── Section Contrôle ──────────────────────────────────────────
        self._build_control_section(left_col)

        # ── Section Mode ──────────────────────────────────────────────
        self._build_mode_section(left_col)

        # ── Section Effets ────────────────────────────────────────────
        self._build_effects_section(left_col)

        # ── Section LEDs ──────────────────────────────────────────────
        self._build_leds_section(right_col)

        # ── Section Sound ─────────────────────────────────────────────
        self._build_sound_section(right_col)

        # ── Section Mouse Ambient ────────────────────────────────────
        self._build_mouse_section(right_col)

        # ── Bouton Sauvegarder ────────────────────────────────────────
        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=16)
        save_f = tk.Frame(root, bg=BG, pady=10, padx=16)
        save_f.pack(fill="x")
        tk.Button(
            save_f, text="💾  Sauvegarder la configuration",
            bg=PANEL2, fg=FG, font=("Helvetica", 10),
            relief="flat", cursor="hand2", padx=10, pady=7,
            activebackground=ACCENT, activeforeground="white",
            command=self._save,
        ).pack(fill="x")

        # ── Pied de page ──────────────────────────────────────────────
        tk.Label(
            root, text="Ambilight v2.0 · Screen & Sound Ambient",
            bg=BG, fg="#333355", font=("Helvetica", 9),
        ).pack(pady=(0, 8))

        # Mise à jour de la visibilité initiale
        self._on_mode_change()

    # ── Sections ──────────────────────────────────────────────────────

    def _section(self, parent, title, color=None):
        c = color or ACCENT
        frame = tk.LabelFrame(
            parent, text=f"  {title}  ",
            bg=PANEL, fg=c,
            font=("Helvetica", 10, "bold"),
            bd=1, relief="groove", padx=10, pady=8,
        )
        return frame

    def _label(self, parent, text, fg=None, **kw):
        return tk.Label(
            parent, text=text, bg=kw.pop("bg", PANEL),
            fg=fg or LABEL_FG, font=("Helvetica", 10), **kw,
        )

    def _slider_row(self, parent, display_name, key, lo, hi, res, fmt):
        """Crée une ligne label + slider + valeur."""
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        self._label(row, display_name).pack(anchor="w")
        inner = tk.Frame(row, bg=PANEL)
        inner.pack(fill="x")
        val_lbl = self._label(inner, fmt(self._vars[key].get()), fg=FG, width=8, anchor="e")
        val_lbl.pack(side="right")

        def cmd(v, lbl=val_lbl, f=fmt):
            lbl.config(text=f(int(float(v))))

        tk.Scale(
            inner, from_=lo, to=hi, orient="horizontal",
            variable=self._vars[key], showvalue=False, resolution=res,
            bg=PANEL, fg=LABEL_FG, troughcolor="#0f0f30",
            activebackground=ACCENT, highlightthickness=0,
            command=cmd,
        ).pack(side="left", fill="x", expand=True)

    def _build_control_section(self, parent):
        ctrl = self._section(parent, "Contrôle")
        ctrl.pack(fill="x", pady=4)

        self._btn_toggle = tk.Button(
            ctrl, text="▶  DÉMARRER",
            bg=ACCENT, fg=ACCENT2,
            font=("Helvetica", 11, "bold"), relief="flat",
            activebackground=ACCENT2, activeforeground=ACCENT,
            cursor="hand2", padx=20, pady=10,
            command=self._toggle,
        )
        self._btn_toggle.pack(fill="x", pady=(4, 6))

        self._lbl_status = self._label(ctrl, "⬤  Arrêté", fg="#555577")
        self._lbl_status.pack()
        self._lbl_fps = self._label(ctrl, "FPS : —")
        self._lbl_fps.pack(pady=(2, 0))

        # Port série
        ports = glob.glob("/dev/cu.usbmodem*")
        port = None
        if len(ports) > 0:
            port = ports[0]

        self._label(ctrl, "Port série").pack(anchor="w", pady=(8, 0))
        self._var_port = tk.StringVar(value=self._cfg.get("serial_port", port))
        tk.Entry(
            ctrl, textvariable=self._var_port,
            bg="#0a0a24", fg=FG, insertbackground=FG,
            relief="flat", font=("Helvetica", 10), width=26,
        ).pack(fill="x", pady=2)


    def _build_mode_section(self, parent):
        mode_f = self._section(parent, "Mode", color=ACCENT2)
        mode_f.pack(fill="x", pady=4)

        self._var_mode = tk.StringVar(value=self._cfg.get("mode", "screen"))

        btn_frame = tk.Frame(mode_f, bg=PANEL)
        btn_frame.pack(fill="x", pady=4)

        self._btn_screen = tk.Radiobutton(
            btn_frame, text="🖥",
            variable=self._var_mode, value="screen",
            bg=PANEL, fg=FG, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            font=("Helvetica", 20, "bold"),
            cursor="hand2",
            command=self._on_mode_change,
        )
        self._btn_screen.pack(side="left", expand=True, padx=4)

        self._btn_sound = tk.Radiobutton(
            btn_frame, text="🎵",
            variable=self._var_mode, value="sound",
            bg=PANEL, fg=FG, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            font=("Helvetica", 20, "bold"),
            cursor="hand2",
            command=self._on_mode_change,
        )
        self._btn_sound.pack(side="left", expand=True, padx=4)

        self._btn_responsive = tk.Radiobutton(
            btn_frame, text="💥",
            variable=self._var_mode, value="responsive",
            bg=PANEL, fg=FG, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            font=("Helvetica", 20, "bold"),
            cursor="hand2",
            command=self._on_mode_change,
        )
        self._btn_responsive.pack(side="left", expand=True, padx=4)

        # Choix du numéro d'écran
        self.l_screen = self._label(mode_f, "Numéro d'écran")
        self.l_screen.pack(anchor="w", pady=(4, 0))
        self._var_screen = tk.IntVar(value=self._cfg.get("screen_index", 0))
        self._w_screen = tk.Spinbox(
            mode_f, from_=0, to=8, textvariable=self._var_screen,
            bg="#0a0a24", fg=FG, buttonbackground="#0a0a24",
            relief="flat", width=5,
        )
        self._w_screen.pack(anchor="w", pady=2)

        # Section Spotify avec cover
        self._spotify_row = tk.Frame(mode_f, bg=PANEL)
        self._spotify_cover_frame = tk.Frame(self._spotify_row, bg=PANEL)
        self._spotify_cover_frame.pack(side="left", padx=(0, 6))

        self._info_col = tk.Frame(self._spotify_row, bg=PANEL)
        self._info_col.pack(side="left", fill="both", expand=True)

        self._lbl_spotify_cover = tk.Label(
            self._spotify_cover_frame, bg=PANEL, width=64, height=64
        )   
        self._lbl_spotify_cover.config(image="", width=0,height=0)
        self._lbl_spotify_cover.pack()

        self._lbl_track = self._label(self._info_col, "", fg=ACCENT2, wraplength=200, pady=22, padx=22)
        self._lbl_track.pack(anchor="w")

    def _build_effects_section(self, parent):
        effects = self._section(parent, "Effets visuels")
        effects.pack(fill="x", pady=4)

        self._vars: dict[str, tk.Variable] = {}
        self._vars["fps"] = tk.IntVar(value=int(self._cfg.get("fps", 30)))
        self._vars["brightness_pct"] = tk.IntVar(
            value=int(self._cfg.get("brightness", 1.0) * 100))
        self._vars["gamma_x10"] = tk.IntVar(
            value=int(self._cfg.get("gamma", 1.0) * 10))
        self._vars["sat_x10"] = tk.IntVar(
            value=int(self._cfg.get("saturation_boost", 1.2) * 10))
        self._vars["transition_x100"] = tk.IntVar(
            value=int(self._cfg.get("transition_speed", 0.5) * 100))

        sliders = [
            ("FPS cible",              "fps",              1,   60,  1,  lambda v: f"{v} fps"),
            ("Luminosité Globale (%)", "brightness_pct",   10, 200,  1,  lambda v: f"{v} %"),
            ("Gamma",                  "gamma_x10",         5,  30,  1,  lambda v: f"{v/10:.1f}"),
            ("Saturation boost",       "sat_x10",           5,  40,  1,  lambda v: f"{v/10:.1f}×"),
            ("Vitesse transition",     "transition_x100",   0, 100,  1,  lambda v: f"{v} %"),
        ]

        for display_name, key, lo, hi, res, fmt in sliders:
            self._slider_row(effects, display_name, key, lo, hi, res, fmt)

        # Indication vitesse de transition
        hint = self._label(
            effects,
            "0 % = instantané  ·  100 % = ultra lent",
            fg="#445566",
        )
        hint.pack(anchor="w")

    def _build_leds_section(self, parent):
        led_f = self._section(parent, "Configuration LEDs")
        led_f.pack(fill="x", pady=4)

        sides_cfg = self._cfg.get("led_sides", {})
        self._var_num_leds = tk.IntVar(value=self._cfg.get("num_leds", 113))
        self._var_depth = tk.IntVar(value=self._cfg.get("border_depth_px", 80))

        def spinrow(p, text, var, lo=0, hi=200):
            row = tk.Frame(p, bg=PANEL)
            row.pack(fill="x", pady=2)
            self._label(row, text, width=24, anchor="w").pack(side="left")
            tk.Spinbox(
                row, from_=lo, to=hi, textvariable=var,
                bg="#0a0a24", fg=FG, buttonbackground="#0a0a24",
                relief="flat", width=5,
            ).pack(side="right")

        spinrow(led_f, "Nombre total de LEDs", self._var_num_leds, 1, 200)
        spinrow(led_f, "Profondeur bord (px natif)", self._var_depth, 10, 500)

        tk.Frame(led_f, bg=ACCENT, height=1).pack(fill="x", pady=6)
        self._label(led_f, "LEDs par côté", fg=ACCENT).pack(anchor="w")

        self._var_bl    = tk.IntVar(value=sides_cfg.get("bottom_left_count", 15))
        self._var_right = tk.IntVar(value=sides_cfg.get("right_count", 28))
        self._var_top   = tk.IntVar(value=sides_cfg.get("top_count", 42))
        self._var_left  = tk.IntVar(value=sides_cfg.get("left_count", 28))
        self._var_br    = tk.IntVar(value=sides_cfg.get("bottom_right_count", 0))

        spinrow(led_f, "⬛ Bas gauche→droite", self._var_bl)
        spinrow(led_f, "▶ Droite bas→haut",    self._var_right)
        spinrow(led_f, "⬛ Haut droite→gauche", self._var_top)
        spinrow(led_f, "◀ Gauche haut→bas",    self._var_left)
        spinrow(led_f, "⬛ Bas fin (optionnel)", self._var_br)

        self._lbl_total = self._label(led_f, "", fg=ACCENT)
        self._lbl_total.pack(pady=(4, 0))
        for v in [self._var_bl, self._var_right, self._var_top,
                  self._var_left, self._var_br]:
            v.trace_add("write", lambda *_: self._update_total())
        self._update_total()

    def _build_sound_section(self, parent):
        self._sound_frame = self._section(parent, "Sound Ambient 🎵", color=GREEN)
        self._sound_frame.pack(fill="x", pady=4)

        # ── Source audio ───────────────────────────────────
        self._label(self._sound_frame, "Source audio").pack(anchor="w")

        audio_source_frame = tk.Frame(self._sound_frame, bg=PANEL)
        audio_source_frame.pack(fill="x", pady=(2, 6))

        self._var_audio_source = tk.StringVar(value=self._cfg.get("audio_source", "system"))

        tk.Radiobutton(
            audio_source_frame, text="🖥 Système",
            variable=self._var_audio_source, value="system",
            bg=PANEL, fg=FG, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            cursor="hand2"
        ).pack(side="left", expand=True)
        
        tk.Radiobutton(
            audio_source_frame, text="🎤 Micro",
            variable=self._var_audio_source, value="mic",
            bg=PANEL, fg=FG, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            cursor="hand2"
        ).pack(side="left", expand=True)

        # tk.Radiobutton(
        #     audio_source_frame, text="♫ Spotify",
        #     variable=self._var_audio_source, value="spotify",
        #     bg=PANEL, fg=FG, selectcolor=PANEL2,
        #     activebackground=PANEL, activeforeground=FG,
        #     cursor="hand2"
        # ).pack(side="left", expand=True)

        # ── Sélecteur de périphérique audio ───────────────
        self._label(self._sound_frame, "Périphérique d'entrée audio").pack(anchor="w", pady=(4, 0))

        self._audio_devices = []
        self._var_audio_device = tk.StringVar(value="Défaut système")

        self._combo_audio = ttk.Combobox(
            self._sound_frame,
            textvariable=self._var_audio_device,
            state="readonly",
            width=30,
        )
        self._combo_audio.pack(fill="x", pady=(2, 6))

        tk.Button(
            self._sound_frame,
            text="🔄 Rafraîchir les périphériques",
            bg=PANEL2, fg=FG, font=("Helvetica", 9),
            relief="flat", cursor="hand2", pady=4,
            activebackground=GREEN, activeforeground="white",
            command=self._refresh_audio_devices,
        ).pack(fill="x", pady=(0, 6))

        tk.Frame(self._sound_frame, bg=ACCENT2, height=1).pack(fill="x", pady=4)

        # ── Style d'effet ──────────────────────────────────
        self._label(self._sound_frame, "Style d'effet sonore").pack(anchor="w")
        self._var_effect = tk.StringVar(value=self._cfg.get("sound_effect", "ripples"))

        effect_frame = tk.Frame(self._sound_frame, bg=PANEL)
        effect_frame.pack(fill="x", pady=(2, 6))

        tk.Radiobutton(
            effect_frame, text="Ondes",
            variable=self._var_effect, value="ripples",
            bg=PANEL, fg=FG, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            cursor="hand2"
        ).pack(side="left", expand=True)

        tk.Radiobutton(
            effect_frame, text="Spectre",
            variable=self._var_effect, value="spectrum",
            bg=PANEL, fg=FG, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            cursor="hand2"
        ).pack(side="left", expand=True)

        # tk.Radiobutton(
        #     effect_frame, text="Barres",
        #     variable=self._var_effect, value="frequency_bars",
        #     bg=PANEL, fg=FG, selectcolor=PANEL2,
        #     activebackground=PANEL, activeforeground=FG,
        #     cursor="hand2"
        # ).pack(side="left", expand=True)

        # ── Sliders son ────────────────────────────────────
        if "sound_hue_x100" not in self._vars:
            self._vars = getattr(self, "_vars", {})

        self._vars["sound_hue_x100"] = tk.IntVar(
            value=int(self._cfg.get("sound_hue_speed", 0.05) * 100))
        self._vars["sound_smooth_x100"] = tk.IntVar(
            value=int(self._cfg.get("sound_smoothing", 0.3) * 100))
        self._vars["audio_intensity_x100"] = tk.IntVar(
            value=int(self._cfg.get("audio_intensity", 1.0) * 100))
        self._vars["realtime_brightness_x100"] = tk.IntVar(
            value=int(self._cfg.get("realtime_brightness", 1.0) * 100))

        tk.Frame(self._sound_frame, bg=ACCENT2, height=1).pack(fill="x", pady=4)

        def fmt_pct(v): return f"{v} %"

        self._slider_row(
            self._sound_frame,
            "Vitesse drift couleurs",
            "sound_hue_x100", 1, 30, 1, fmt_pct,
        )
        self._slider_row(
            self._sound_frame,
            "Lissage audio (réactivité)",
            "sound_smooth_x100", 5, 90, 1, fmt_pct,
        )
        self._slider_row(
            self._sound_frame,
            "Intensité audio 🔊",
            "audio_intensity_x100", 50, 200, 1, fmt_pct,
        )
        self._slider_row(
            self._sound_frame,
            "Intensité lumineuse 💡",
            "realtime_brightness_x100", 10, 200, 1, fmt_pct,
        )

        # ── Info Spotify ───────────────────────────────────
        # tk.Frame(self._sound_frame, bg=ACCENT2, height=1).pack(fill="x", pady=4)
        # self._label(self._sound_frame, "🎧 Spotify (auto-détection)", fg=GREEN).pack(anchor="w")
        # self._lbl_spotify = self._label(
        #     self._sound_frame,
        #     "Non détecté — lance Spotify pour activer",
        #     fg="#445566",
        #     wraplength=200,
        # )
        # self._lbl_spotify.pack(anchor="w", pady=(2, 0))

        # Charger les périphériques
        self._refresh_audio_devices()

    def _build_mouse_section(self, parent):
        mouse = self._section(parent, "Mouse Ambient", color=GREEN)
        mouse.pack(fill="x", pady=4)

        self._var_mouse_enabled = tk.BooleanVar(
            value=self._cfg.get("mouse_enabled", True)
        )
        tk.Checkbutton(
            mouse,
            text="Activer les LEDs de la souris",
            variable=self._var_mouse_enabled,
            bg=PANEL,
            fg=FG,
            selectcolor=PANEL2,
            activebackground=PANEL,
            activeforeground=FG,
        ).pack(anchor="w")

        self._var_mouse_radius = tk.IntVar(
            value=self._cfg.get("mouse_sample_radius", 180)
        )
        self._lbl_mouse_radius = self._label(
            mouse, f"Rayon d'echantillonnage : {self._var_mouse_radius.get()} px", fg=FG
        )
        self._lbl_mouse_radius.pack(anchor="w", pady=(4, 0))
        tk.Scale(
            mouse,
            from_=40,
            to=500,
            resolution=10,
            orient="horizontal",
            variable=self._var_mouse_radius,
            showvalue=False,
            bg=PANEL,
            fg=LABEL_FG,
            troughcolor="#0f0f30",
            activebackground=GREEN,
            highlightthickness=0,
            command=lambda value: self._lbl_mouse_radius.config(
                text=f"Rayon d'echantillonnage : {int(float(value))} px"
            ),
        ).pack(fill="x")

        self._lbl_mouse_cursor = self._label(mouse, "Curseur : en attente", fg=FG)
        self._lbl_mouse_cursor.pack(anchor="w", pady=(4, 0))
        self._lbl_mouse_rgb = self._label(
            mouse,
            "OpenRGB : en attente",
            wraplength=300,
            justify="left",
        )
        self._lbl_mouse_rgb.pack(anchor="w")

    # ------------------------------------------------------------------
    # Logique mode
    # ------------------------------------------------------------------

    def _on_mode_change(self):
        mode = self._var_mode.get()
        if mode == "screen":
            self._sound_frame.pack_forget()

            self._spotify_row.pack_forget()
            self.l_screen.pack(fill="x", pady=(4, 0))
            self._w_screen.pack(fill="x", pady=(6, 0))
        else:
            self._sound_frame.pack(fill="x", pady=4)

            self._spotify_row.pack(fill="x", pady=(6, 0))
            self.l_screen.pack_forget()
            self._w_screen.pack_forget()

    def _refresh_audio_devices(self):
        """Met à jour la liste des périphériques audio."""
        if not SOUND_OK:
            self._combo_audio["values"] = ["sounddevice non disponible"]
            return
        try:
            devices = SoundAmbient.list_audio_devices()
            self._audio_devices = devices
            names = ["Défaut système"] + [f"{d['index']}: {d['name']}" for d in devices]
            self._combo_audio["values"] = names

            # Pré-sélectionner le périphérique sauvegardé
            saved = self._cfg.get("sound_device", None)
            if saved is not None:
                for name in names:
                    if name.startswith(f"{saved}:"):
                        self._var_audio_device.set(name)
                        break
        except Exception as e:
            self._combo_audio["values"] = [f"Erreur : {e}"]

    def _get_audio_device_index(self) -> Optional[int]:
        """Retourne l'index du périphérique sélectionné, ou None."""
        val = self._var_audio_device.get()
        if val.startswith("Défaut") or ":" not in val:
            return None
        try:
            return int(val.split(":")[0])
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _update_total(self):
        total = (self._var_bl.get() + self._var_right.get() +
                 self._var_top.get() + self._var_left.get() +
                 self._var_br.get())
        target = self._var_num_leds.get()
        color = GREEN if total == target else ACCENT
        self._lbl_total.config(
            text=f"Total côtés : {total} / {target} LEDs", fg=color)

    def _build_cfg_from_ui(self) -> dict:
        cfg = dict(self._cfg)
        cfg["serial_port"]    = self._var_port.get().strip()
        cfg["screen_index"]   = self._var_screen.get()
        cfg["mouse_enabled"]  = self._var_mouse_enabled.get()
        cfg["mouse_sample_radius"] = self._var_mouse_radius.get()
        cfg["num_leds"]       = self._var_num_leds.get()
        cfg["fps"]            = self._vars["fps"].get()
        cfg["brightness"]     = round(self._vars["brightness_pct"].get() / 100.0, 2)
        cfg["gamma"]          = round(self._vars["gamma_x10"].get() / 10.0, 2)
        cfg["saturation_boost"] = round(self._vars["sat_x10"].get() / 10.0, 2)
        cfg["transition_speed"] = round(self._vars["transition_x100"].get() / 100.0, 2)
        cfg["border_depth_px"] = self._var_depth.get()
        cfg["mode"]           = self._var_mode.get()
        cfg["sound_device"]   = self._get_audio_device_index()
        cfg["sound_effect"]   = self._var_effect.get()
        cfg["sound_hue_speed"]   = round(self._vars["sound_hue_x100"].get() / 100.0, 3)
        cfg["sound_smoothing"]   = round(self._vars["sound_smooth_x100"].get() / 100.0, 2)
        cfg["audio_source"]      = self._var_audio_source.get()
        cfg["audio_intensity"]   = round(self._vars["audio_intensity_x100"].get() / 100.0, 2)
        cfg["realtime_brightness"] = round(self._vars["realtime_brightness_x100"].get() / 100.0, 2)
        cfg["led_sides"] = {
            "bottom_left_count":  self._var_bl.get(),
            "right_count":        self._var_right.get(),
            "top_count":          self._var_top.get(),
            "left_count":         self._var_left.get(),
            "bottom_right_count": self._var_br.get(),
        }
        return cfg

    def _toggle(self):
        if not self._running:
            cfg = self._build_cfg_from_ui()
            self._cfg.update(cfg)
            try:
                self._on_start(cfg)
                self._running = True
                self._btn_toggle.config(text="⏹  ARRÊTER", bg="#2a2a4a")
                mode = cfg.get("mode", "screen")
                icon = "🖥" if mode == "screen" else "🎵"
                self._lbl_status.config(
                    text=f"⬤  En cours… {icon}", fg=GREEN)
            except Exception as e:
                messagebox.showerror("Erreur de connexion", str(e))
        else:
            self._on_stop()
            self._running = False
            self._btn_toggle.config(text="▶  DÉMARRER", bg=ACCENT)
            self._lbl_status.config(text="⬤  Arrêté", fg="#555577")
            self._lbl_fps.config(text="FPS : —")

    def _save(self):
        cfg = self._build_cfg_from_ui()
        self._cfg.update(cfg)
        self._on_save(cfg)
        messagebox.showinfo("Sauvegardé", "Configuration enregistrée dans config.json ✓")

    # ------------------------------------------------------------------
    # API publique (appelée depuis le thread de capture)
    # ------------------------------------------------------------------

    def update_fps(self, fps_real: float):
        self.root.after(0, lambda: self._lbl_fps.config(
            text=f"FPS : {fps_real:.1f}"))

    def update_mouse_status(
        self,
        position: tuple[float | None, float | None],
        openrgb_status: str,
    ):
        x, y = position
        if x is None or y is None:
            cursor_text = "Curseur : absent de l'ecran selectionne"
        else:
            cursor_text = f"Curseur detecte : ({x:.0f}, {y:.0f})"

        def _do():
            self._lbl_mouse_cursor.config(text=cursor_text)
            self._lbl_mouse_rgb.config(text=f"OpenRGB : {openrgb_status}")

        self.root.after(0, _do)

    def update_track(self, track: Optional[str], cover_url: Optional[str] = None):
        """Mets à jour le texte et la cover Spotify."""
        def _do():
            if self._lbl_track:
                if track:
                    self._lbl_track.config(text=f"🎵 {track.strip()}")
                    if cover_url:
                        self._load_cover(cover_url)
                else:
                    self._lbl_track.config(text="")
                    self._lbl_spotify_cover.config(image="", width=0,height=0)
                    self._current_cover_image = None
        self.root.after(0, _do)

    def update_track_cover(self, cover_url: Optional[str] = None):
        """Mets à jour seulement la cover."""
        def _do():
            if cover_url:
                self._load_cover(cover_url)
            else:
                self._lbl_spotify_cover.config(image="", width=0,height=0)
                self._current_cover_image = None
        self.root.after(0, _do)

    def _load_cover(self, url: str):
        """Charge et affiche la cover depuis une URL."""
        if not PIL_OK:
            return
        try:
            import requests as req
            r = req.get(url, timeout=3)
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            img = img.resize((64, 64), Image.Resampling.LANCZOS)
            self._spotify_cover_photo = ImageTk.PhotoImage(img)
            self._lbl_spotify_cover.config(image=self._spotify_cover_photo, width=64,height=64)
            self._current_cover_image = img
        except Exception:
            pass

    def set_error(self, msg: str):
        def _do():
            self._running = False
            self._btn_toggle.config(text="▶  DÉMARRER", bg=ACCENT)
            self._lbl_status.config(text="⬤  Erreur", fg=ACCENT)
            messagebox.showerror("Erreur Ambilight", msg)
        self.root.after(0, _do)

    def run(self):
        self.root.mainloop()
