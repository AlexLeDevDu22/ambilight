# Ambilight – client

Serveur local + interface web pour le ruban LED Arduino et la souris Cougar Revenger ST,
empaqueté en app macOS avec une icône dans la barre de menus.

## Installation / mise à jour

```bash
./update.sh        # à la racine du dépôt
```

Le script fait seulement ce qui est nécessaire :
1. venv Python + dépendances ;
2. compilation et flash du firmware Arduino (si ses sources ont changé) ;
3. construction de `~/Applications/Ambilight.app` ;
4. lancement automatique à l'ouverture de session ;
5. (re)lancement de l'app.

Options : `--flash` (forcer le flash), `--rebuild` (forcer l'app), `--no-autostart`.

## Utilisation

- **Icône ampoule** dans la barre de menus : allumer/éteindre le ruban et la souris, changer de mode,
  *Ouvrir l'interface…* (http://127.0.0.1:8787), activer/désactiver le lancement à l'ouverture de session,
  *Quitter Ambilight* (arrête tout, LEDs éteintes).
- Après avoir quitté : relancer **Ambilight** depuis le Launchpad, Spotlight ou `~/Applications`.
- Dans la page : `L` = ruban on/off, `M` = souris on/off.
- Développement : `client/start.sh` lance le serveur dans le terminal (s'il tourne déjà, ouvre juste la page).

## Mises à jour automatiques (app lancée)

| Modifié | Effet |
|---|---|
| `client/server.py`, `client/core/*.py` | l'app se relance toute seule (seulement si le code compile) |
| `client/web/*` | la page se recharge toute seule |
| `client/requirements.txt` | `pip install` puis relance |
| `arduino-ambilight/src/*`, `platformio.ini` | compilation + flash de l'Arduino, les LEDs reprennent ensuite |
| `client/macos/*`, `Icon.png` | lancer `./update.sh` (reconstruit l'app) |

Journal : `~/Library/Logs/Ambilight/server.log`.

## Modes

| Ruban LED | Souris |
|---|---|
| **Écran** – ambilight classique (ScreenCaptureKit, très léger), bandes noires des films ignorées | **Son › Pulse** – le contour monte et descend avec les basses, la couleur glisse dans le dégradé |
| **Son** – Pulse (effet enceinte), Ondes, Spectre, Strobe | **Son › Rotation** – dégradé multicolore qui tourne autour (vitesse = énergie, sens inversé sur les drops) |
| **Ambiance** – Aurore, Flow, Respiration, Arc-en-ciel | **Flow** – vague de couleur de l'avant vers l'arrière · **Respiration** · **Aurore** |
| **Couleur** – dégradé bas/haut au choix | **Couleur** – contour, molette et logo au choix |
| | **Ruban** – synchro : contour = bas du ruban, molette = côté gauche, logo = haut |

En mode Son, le logo explose sur les kicks et la molette sur les snares.
Ruban : à chaque changement de mode, d'effet, de palette ou de couleur, le nouveau look monte du bas vers le haut des deux côtés, avec un liseré de LEDs blanches (~0,5 s).
Souris : même principe, un flash blanc balaie la souris de l'avant vers l'arrière (molette → contour → logo, ~0,6 s).
Extinction (bouton, télécommande, quitter) : l'inverse — la lumière blanche descend du haut vers le bas du ruban
(et de l'arrière vers l'avant de la souris) en laissant le noir derrière elle.
Le morceau Spotify en cours s'affiche en grand en haut de l'interface (pochette, fond flouté, égaliseur
qui suit le vrai son quand un mode Son tourne), avec une animation à chaque changement de morceau.
Palettes : **Cover** (couleurs de la pochette Spotify en cours, fondu de 2 s au changement de morceau ; Sunset si rien ne joue) ou presets.
**Réactif** (souris) : clic gauche ↺, clic droit ↻, molette haut/bas, clic milieu → tout pulse.

**Sortie audio automatique** : quand un mode Son démarre, la sortie macOS passe sur « Ambilight » (sortie multiple enceintes + BlackHole) ;
elle revient à la précédente quand plus aucun mode Son ne tourne. Si la musique joue mais que rien n'est capté, l'interface dit pourquoi.

**Films** (mode Écran) : les bandes noires (film large ou vidéo 4:3) sont détectées et ignorées, seulement si
c'est sûr — bandes parfaitement noires, symétriques, image plus large (ou plus étroite) que l'écran, contenu
visible au centre et situation stable ~1,5 s. Désactivable dans la carte du ruban.

**Strobe** : flash franc sur chaque kick, au plus 4 par seconde (confort visuel) ; gros kick = tout le ruban
avec un cœur blanc, kick léger = une moitié, en alternant gauche / droite.

## Télécommande

Serveur lancé : l'Arduino transmet les touches au serveur (il sait que le serveur est là grâce à un ping
chaque seconde). Serveur arrêté : ses modes intégrés reprennent la main après 3 s.

| Touche | Action |
|---|---|
| POWER | tout allumer / tout éteindre |
| ▶︎ · ST | ruban on/off · souris on/off |
| VOL+ / VOL− | luminosité (maintenir pour aller vite) |
| FUNC · EQ | mode ruban suivant · mode souris suivant |
| \|◀◀ / ▶▶\| | effet précédent / suivant (Son, Ambiance) — palette sinon |
| ↑ / ↓ | palette suivante / précédente (ruban + souris) |
| 1 · 2 · 3 · 4 | ruban : Écran · Son · Ambiance · Couleur |
| 5 · 6 · 7 · 8 · 9 · 0 | souris : Son · Flow · Respiration · Aurore · Couleur · Ruban |

L'interface affiche une petite bulle à chaque touche et se met à jour toute seule.

**Veille intelligente** (activée par défaut, réglages avancés) : écran verrouillé, écran éteint ou Mac en veille
→ le ruban et la souris s'éteignent ; au déverrouillage, ce qui était allumé se rallume tout seul.

Les réglages sont enregistrés à chaque changement dans `config.json`, ainsi que ce qui était allumé (relancé au démarrage).

## Accès depuis l'app iPhone (réseau local)

Le serveur écoute aussi sur le Wi-Fi (désactivable : Réglages avancés › *Accès depuis le réseau local*) et s'annonce en
Bonjour (`_ambilight._tcp`, port 8787). Un appareil s'appaire une fois avec un **code à 4 chiffres** affiché sur le Mac,
puis utilise un jeton (`Authorization: Bearer …`). Les appareils appairés se retirent dans les réglages avancés.
L'interface web reste réservée au Mac.

- API complète, flux temps réel (SSE `/api/events?lite=1`), envoi du son de l'app (WebSocket `/api/audio`, PCM 16 bits mono)
  et du morceau en cours (`/api/nowplaying`, prioritaire sur Spotify) : voir [docs/app-integration-prompt.md](docs/app-integration-prompt.md).

## Permissions macOS (pour « Ambilight », Réglages › Confidentialité et sécurité)

- **Surveillance de l'entrée** → LEDs de la souris et option Réactif
- **Enregistrement de l'écran** → mode Écran
- **Micro** → capture BlackHole (modes Son)

Après une reconstruction de l'app (`--rebuild` ou lanceur modifié), macOS peut les redemander :
retirer Ambilight de la liste avec « − », le rajouter depuis `~/Applications`, puis relancer l'app.

## Architecture

```
server.py               HTTP + API JSON + flux temps réel (SSE) + WebSocket audio, accès réseau, Bonjour
core/serial_link.py     liaison Arduino persistante à 500 kbauds (repli 115200), 1 trame à la fois, attend le "OK",
                        ping chaque seconde, lit les touches de télécommande ("IR:<TOUCHE>")
core/mouse_device.py    HID direct Revenger ST (plus besoin d'OpenRGB)
core/audio.py           analyse audio partagée (basses / kicks / snares / spectre)
core/audio_output.py    bascule de la sortie macOS vers « Ambilight » (CoreAudio)
core/sck_capture.py     capture d'écran ScreenCaptureKit (repli : CGWindowList)
core/palette.py         presets + palette de la cover Spotify
core/strip_*.py         moteur et effets du ruban
core/mouse_engine.py    modes souris + réactivité
core/input_events.py    écoute des clics / molette
core/remote.py          télécommande IR → actions
core/sleep.py           veille intelligente (verrouillage, écran éteint, veille du Mac)
core/menubar.py         icône et menu dans la barre de menus
core/autostart.py       LaunchAgent (lancement à l'ouverture de session)
core/updater.py         mises à jour automatiques (code, web, dépendances, firmware)
core/permissions.py     demande des autorisations macOS
core/auth.py            appairage des appareils du réseau (code à 4 chiffres → jeton)
macos/                  lanceur natif (Python embarqué), Info.plist, build_app.sh
web/                    interface
```

Notes matériel (souris) :
- hidapi est forcé en ouverture **non exclusive** : en exclusif (défaut sur macOS) le curseur se fige.
- En mode Direct le contour (côtés + arrière) n'a qu'une couleur ; le multicolore qui tourne passe par l'effet
  matériel « Flow ». Chaque relance de cet effet fait scintiller quelques LEDs (firmware) : Rotation le relance le moins possible.
