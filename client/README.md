# Ambilight – client

Serveur local + interface web pour le ruban LED Arduino et la souris Cougar Revenger ST.

```bash
./start.sh            # lance le serveur et ouvre http://127.0.0.1:8787
```

Relancer `./start.sh` alors qu'il tourne déjà ouvre simplement l'interface. `Ctrl+C` éteint tout proprement.
Raccourcis dans la page : `L` = ruban on/off, `M` = souris on/off.

## Modes

| Ruban LED | Souris |
|---|---|
| **Écran** – ambilight classique (ScreenCaptureKit, très léger) | **Son › Pulse** – le contour monte et descend avec les basses, la couleur glisse dans le dégradé |
| **Son** – Pulse (effet enceinte), Ondes, Spectre | **Son › Rotation** – dégradé multicolore qui tourne autour (vitesse = énergie, sens inversé sur les drops) |
| **Ambiance** – Aurore, Flow, Respiration, Arc-en-ciel | **Flow** – vague de couleur de l'avant vers l'arrière · **Respiration** · **Aurore** |
| **Couleur** – dégradé bas/haut au choix | **Couleur** – contour, molette et logo au choix |

En mode Son, le logo explose sur les kicks et la molette sur les snares.
Ruban : à chaque changement de mode, d'effet, de palette ou de couleur, le nouveau look monte du bas vers le haut des deux côtés, avec un liseré de LEDs blanches (~0,5 s).
Souris : même principe, un flash blanc balaie la souris de l'avant vers l'arrière (molette → contour → logo, ~0,6 s).
Palettes : **Cover** (couleurs de la pochette Spotify en cours, fondu de 2 s au changement de morceau ; Sunset si rien ne joue) ou presets.
**Réactif** (souris) : clic gauche ↺, clic droit ↻, molette haut/bas, clic milieu → tout pulse.

**Sortie audio automatique** : quand un mode Son démarre, la sortie macOS passe sur « Ambilight » (sortie multiple enceintes + BlackHole) ;
elle revient à la précédente quand plus aucun mode Son ne tourne. Si la musique joue mais que rien n'est capté, l'interface dit pourquoi.

Les réglages sont enregistrés à chaque changement dans `config.json`, ainsi que ce qui était allumé (relancé au démarrage).

## Permissions macOS (pour l'app qui lance `start.sh`, ex. Terminal)

- **Enregistrement de l'écran** → mode Écran
- **Micro** → capture BlackHole (modes Son)
- **Surveillance de l'entrée** → option Réactif

## Architecture

```
server.py               HTTP + API JSON + flux temps réel (SSE)
core/serial_link.py     liaison Arduino persistante (1 trame à la fois, attend le "OK")
core/mouse_device.py    HID direct Revenger ST (plus besoin d'OpenRGB)
core/audio.py           analyse audio partagée (basses / kicks / snares / spectre)
core/audio_output.py    bascule de la sortie macOS vers « Ambilight » (CoreAudio)
core/sck_capture.py     capture d'écran ScreenCaptureKit (repli : CGWindowList)
core/palette.py         presets + palette de la cover Spotify
core/strip_*.py         moteur et effets du ruban
core/mouse_engine.py    modes souris + réactivité
core/input_events.py    écoute des clics / molette
web/                    interface
```

Notes matériel (souris) :
- hidapi est forcé en ouverture **non exclusive** : en exclusif (défaut sur macOS) le curseur se fige.
- En mode Direct le contour (côtés + arrière) n'a qu'une couleur ; le multicolore qui tourne passe par l'effet
  matériel « Flow ». Chaque relance de cet effet fait scintiller quelques LEDs (firmware) : Rotation le relance le moins possible.
