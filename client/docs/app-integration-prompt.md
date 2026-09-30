# Prompt – intégrer Ambilight dans l'app iOS (Jellyfin)

> À copier tel quel à l'assistant qui développe l'app Swift.

---

Tu vas ajouter à l'app une page **« Lumières »** qui pilote mon installation **Ambilight**, qui tourne sur mon Mac :
- un ruban LED autour de l'écran (Arduino) ;
- une souris Cougar Revenger ST rétroéclairée.

Le Mac expose une **API HTTP locale** (JSON), un **flux temps réel** (Server-Sent Events) et une **WebSocket audio**. Le Mac et l'iPhone sont sur le **même réseau Wi-Fi**. Tout est décrit ci-dessous : pas besoin d'autre info. Le serveur est déjà fait et testé : tu ne codes que le client iOS.

Objectif : une page **bien plus simple** que l'interface web du Mac, dans le style de l'app (structure et esthétique Apple Music), avec deux choses essentielles :
1. **« Lumières sur la musique »** : les LEDs réagissent à la musique que *l'app* joue. L'app envoie le son qu'elle joue au Mac et le serveur fait toute l'analyse (basses, kicks…).
2. Allumer/éteindre, changer de mode, d'effet, de palette et de luminosité en quelques touches.

---

## 1. Connexion au Mac

### 1.1 Découverte automatique (Bonjour)
Le Mac s'annonce en Bonjour :
- type de service : `_ambilight._tcp` (domaine `local.`) ;
- nom d'instance : `Ambilight (<nom du Mac>)`, par ex. `Ambilight (MacBook Air de Alex)` ;
- port : **8787** ;
- TXT : `api=1`, `path=/api`.

Utilise `NWBrowser(for: .bonjour(type: "_ambilight._tcp", domain: nil), using: .tcp)`. Pour obtenir l'IP et le port, ouvre une `NWConnection` vers l'endpoint trouvé, puis lis `connection.currentPath?.remoteEndpoint` (`.hostPort`). Garde l'IPv4 si possible, puis construis `http://<ip>:8787`.

**Repli manuel :** un champ « Adresse du Mac » (ex. `192.168.1.25:8787`). L'adresse est affichée sur le Mac dans l'interface web › Réglages avancés › *Appareils connectés*.

Vérifie un hôte avec `GET /api/info` (sans jeton) :
```json
{"name": "Ambilight", "api_version": 1, "computer": "MacBook Air de Alex", "paired": false, "devices": {"leds": true, "mouse": true}}
```
`paired` vaut `true` si le jeton envoyé (header ci-dessous) est valide.

### 1.2 Info.plist (obligatoire)
- `NSLocalNetworkUsageDescription` : « Pour piloter les lumières Ambilight de ton Mac. »
- `NSBonjourServices` : `["_ambilight._tcp"]`
- `NSAppTransportSecurity` → `NSAllowsLocalNetworking = YES` (le serveur est en `http://` sur le réseau local).
- L'app joue déjà de l'audio en arrière-plan (`UIBackgroundModes: audio`) : l'envoi du son continue quand elle est en arrière-plan.

### 1.3 Appairage (une seule fois)
Toutes les routes sauf `/api/info`, `/api/pair` et `/api/pair/confirm` exigent un **jeton**.

1. `POST /api/pair` avec `{"device": "<UIDevice.current.name>"}` → `{"pairing_id": "cf6c7540f57bf9fd", "expires_in": 120}`. Le Mac affiche alors un **code à 4 chiffres**, en grand dans son interface web et dans une notification macOS.
2. L'app affiche un écran « Tape le code affiché sur ton Mac » (4 cases, clavier numérique).
3. `POST /api/pair/confirm` avec `{"pairing_id": "...", "code": "1234"}` :
   - si le code est bon : `{"token": "...", "info": {...}}` ;
   - sinon : **403** `{"error": "code invalide ou expiré"}`, au plus 5 essais.
4. Stocke le **jeton + l'adresse** dans le **Keychain**. Ensuite, chaque requête porte l'en-tête `Authorization: Bearer <token>`. Pour les URL d'images et partout où un header n'est pas possible : `?token=<token>`.
5. Si une réponse est **401** `{"error": "unauthorized"}`, le jeton a été révoqué depuis le Mac : relance l'appairage.

---

## 2. Référence de l'API

Base : `http://<ip>:8787`. Tout est en JSON UTF-8. Les libellés viennent du serveur et sont en français.

### 2.1 Lecture
| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/info` | identité du serveur (public) |
| GET | `/api/state` | **tout** : `config`, `presets`, `catalog`, `live` |
| GET | `/api/catalog` | modes, effets et palettes disponibles, avec leurs libellés |
| GET | `/api/events?lite=1` | **flux temps réel SSE** (~15 messages/s) |
| GET | `/api/nowplaying/artwork?token=…` | pochette du morceau envoyé par l'app (JPEG/PNG) |

**`catalog`** (ne code pas les listes en dur, construis l'UI avec) :
```json
{
  "leds": {
    "modes": [{"id":"screen","label":"Écran"},{"id":"sound","label":"Son"},{"id":"ambient","label":"Ambiance"},{"id":"color","label":"Couleur"}],
    "sound_effects": [{"id":"pulse","label":"Pulse"},{"id":"ripples","label":"Ondes"},{"id":"spectrum","label":"Spectre"},{"id":"strobe","label":"Strobe"}],
    "ambient_effects": [{"id":"aurora","label":"Aurore"},{"id":"flow","label":"Flow"},{"id":"breathe","label":"Respiration"},{"id":"rainbow","label":"Arc-en-ciel"}]
  },
  "mouse": {
    "modes": [{"id":"sound","label":"Son"},{"id":"flow","label":"Flow"},{"id":"breathe","label":"Respiration"},{"id":"aurora","label":"Aurore"},{"id":"color","label":"Couleur"},{"id":"sync","label":"Ruban"}],
    "sound_effects": [{"id":"pulse","label":"Pulse"},{"id":"spin","label":"Rotation"}]
  },
  "palettes": [
    {"id":"cover","label":"Pochette","colors":null},
    {"id":"sunset","label":"Sunset","colors":["#ff4e50","#ff8a4c","#ffc05c","#e0457b","#8a3ffc"]},
    {"id":"ocean","label":"Océan","colors":["…"]}
  ]
}
```
Les palettes existantes sont `cover`, `sunset`, `ocean`, `aurora`, `neon`, `forest`, `candy` et `fire`. `cover` reprend les couleurs de la pochette du morceau en cours ; la couleur réelle affichée est dans `live.leds.palette`.

**`config`** (réglages actuels) :
```json
{
  "leds":  {"mode":"sound","sound_effect":"pulse","ambient_effect":"aurora","palette":"cover",
            "brightness":1.0,"sensitivity":1.0,"speed":0.5,"smoothing":0.5,"letterbox":true,
            "colors":["#ff4d6d","#7b5cff"]},
  "mouse": {"mode":"sound","sound_effect":"pulse","palette":"cover","brightness":1.0,
            "sensitivity":1.0,"speed":0.5,"responsive":true,
            "colors":{"ring":"#7b5cff","wheel":"#ff4d6d","logo":"#00d4ff"}},
  "general": {"smart_sleep":true,"lan":true},
  "hardware": {"…": "réglages techniques, ne pas exposer dans l'app"}
}
```
Bornes : `brightness` 0.05–1 · `sensitivity` 0.3–2.5 (réactivité au son) · `speed` 0–1 (modes Ambiance) · `smoothing` 0–0.95 (mode Écran). `colors` : couleurs `#rrggbb` du mode Couleur (ruban : `[bas, haut]` ; souris : contour, molette, logo).

**Flux temps réel `GET /api/events?lite=1`.** C'est un flux SSE : chaque message est une ligne `data: {json}` suivie d'une ligne vide. Lis-le avec `URLSession.bytes(for:)` et `for try await line in bytes.lines`. Ne l'ouvre que lorsque la page est visible, et reconnecte-toi automatiquement en cas de coupure. Un message ressemble à ceci :
```json
{
  "leds":  {"running":true,"mode":"sound","status":"son · BlackHole 2ch","fps":51.0,
            "preview":"ff2d55ff2d55…","palette":["#d99d57","#fff600","#ff1f00"]},
  "mouse": {"running":true,"mode":"sound","status":"Cougar Revenger ST connectée",
            "preview":{"ring":{"type":"direct","color":"#b4589d"},"wheel":"#a03a46","logo":"#483c23"},
            "palette":["…"]},
  "nowplaying": {"playing":true,"track":"WpointM","artist":"Tiakola","album":"BDLM",
                 "cover":"/api/nowplaying/artwork?v=1","colors":["#d99d57","#fff600","#ff1f00"],"source":"Jellyfin"},
  "audio": {"source":"network","network_client":"iPhone de Alex"},
  "levels": [0.52,0.12,0.31,0.45,0.33,0.26,0.64],
  "serial": {"status":"connecté (usbmodem1201 · 500k)","connected":true},
  "remote": {"id":3,"text":"Palette Néon","t":1790000000.0},
  "sleep": {"on":false,"reason":""},
  "cfg": 42
}
```
- `leds.preview` : **32 couleurs** RGB à la suite, en hexadécimal (6 caractères chacune), réparties le long du ruban en partant du bas à gauche, dans le sens inverse des aiguilles d'une montre. Sers-t'en pour un aperçu lumineux vivant.
- `mouse.preview.ring` vaut `{"type":"direct","color":…}` (une couleur) ou `{"type":"flow","colors":[7 couleurs],"speed":0-15,"cw":bool}` (dégradé qui tourne ; `speed` 0 = rapide, 15 = lent).
- `levels` : 7 barres d'égaliseur (0–1) calculées par le serveur. Le tableau est vide si aucun son n'est analysé.
- `audio.source` : `"network"` (l'app envoie le son), `"blackhole"` (le son du Mac) ou `"none"`.
- `cfg` : numéro de version des réglages. **Quand il change, recharge `GET /api/state`** : les réglages ont été modifiés ailleurs (Mac, télécommande…).
- `remote` : quand `id` change, une touche de la télécommande IR vient d'être utilisée (`text` décrit l'action). Tu peux l'afficher en petite bannière (optionnel).
- `sleep.on` : le Mac est verrouillé ou en veille et les lumières sont éteintes automatiquement. Affiche « En veille » (elles se rallumeront toutes seules).

### 2.2 Actions
| Méthode | Route | Corps | Effet |
|---|---|---|---|
| POST | `/api/power` | `{"on": true}` | allume (ou éteint) **ruban + souris** |
| POST | `/api/leds/toggle` | – | ruban on/off (aussi `/start`, `/stop`) |
| POST | `/api/mouse/toggle` | – | souris on/off (aussi `/start`, `/stop`) |
| POST | `/api/config` | patch partiel | change des réglages, appliqués **à chaud** et enregistrés |
| POST | `/api/nowplaying` | voir §3.2 | morceau en cours et pochette |
| WS | `/api/audio?sample_rate=48000&name=<nom>` | PCM binaire | son joué par l'app (§3.1) |

`/api/power`, `/toggle`, `/start` et `/stop` répondent `{"live": {...}}` (même format que le flux). `/api/config` répond `{"config": {...}}` avec la config validée.

**`POST /api/config`** : envoie **uniquement ce qui change**. C'est une fusion profonde, et le serveur borne et valide tout. Exemples :
```json
{"leds": {"mode": "ambient", "ambient_effect": "aurora"}}
{"leds": {"brightness": 0.6}, "mouse": {"brightness": 0.6}}
{"leds": {"palette": "neon"}, "mouse": {"palette": "neon"}}
{"leds": {"mode": "color", "colors": ["#ff0000", "#0000ff"]}}
```
Pour un slider : mets à jour l'UI tout de suite, et envoie au plus **une requête toutes les ~100 ms** (debounce/throttle) plus la valeur finale au relâchement. Les changements de mode ou d'effet déclenchent une petite animation sur les LEDs côté Mac ; c'est normal.

---

## 3. « Lumières sur la musique »

Quand l'utilisateur active ce mode (et tant que la musique joue dans l'app) :
1. `POST /api/config` avec `{"leds":{"mode":"sound","palette":"cover"},"mouse":{"mode":"sound","palette":"cover"}}`, puis `POST /api/power {"on":true}` si c'était éteint.
2. Ouvre la **WebSocket audio** et envoie le son en continu (§3.1).
3. Envoie le **morceau en cours** avec sa pochette (§3.2), à chaque changement de morceau, de lecture ou de pause, et toutes les 20 s pendant la lecture.

Quand on désactive le mode ou que la lecture s'arrête, ferme la WebSocket. Le serveur repasse de lui-même sur l'audio du Mac au bout d'environ 0,6 s sans données.

### 3.1 WebSocket audio `ws://<ip>:8787/api/audio?sample_rate=<Hz>&name=<nom>`
- Pour l'authentification, mets l'en-tête `Authorization: Bearer <token>` sur la `URLRequest` (ou ajoute `&token=<token>` dans l'URL).
- **Format :** PCM **16 bits signé, little-endian, mono**, à la fréquence indiquée par `sample_rate` (8 000–96 000 ; idéalement celle du flux, 44 100 ou 48 000).
- **Envoi :** messages **binaires**, un bloc de **~10 à 20 ms** par message (ex. 480 à 960 échantillons à 48 kHz, soit 960 à 1 920 octets). Aucun en-tête : juste les échantillons.
- **Changer de fréquence en cours de route :** message texte `{"sample_rate": 44100}`. Le serveur ne renvoie rien (hors pong WebSocket).
- **Mono :** moyenne des canaux gauche et droit. Convertis les Float32 en Int16 : `Int16(max(-1, min(1, x)) * 32767)`.
- **Capture du son joué :**
  - si la lecture passe par **AVAudioEngine** : `installTap(onBus:0, bufferSize:1024, format:nil)` sur `mainMixerNode` ;
  - si c'est **AVPlayer** : un `MTAudioProcessingTap` via un `AVMutableAudioMix` sur l'`AVPlayerItem`, ce qui marche pour les flux progressifs HTTP (le cas des streams Jellyfin « direct play » ou transcodés en mp3/aac, pas HLS). Si la lecture passe par HLS, préfère AVAudioEngine ou un flux Jellyfin non-HLS pour ce mode.
  - Capture après le volume de l'app si possible (sinon ce n'est pas grave : le serveur normalise le niveau tout seul).
- **Synchronisation :** le son capturé passe *avant* la sortie audio. Pour que les lumières tombent pile avec ce qu'on entend, **retarde l'envoi** de `AVAudioSession.sharedInstance().outputLatency + ioBufferDuration` (~10–30 ms sur haut-parleur, **~150–250 ms en Bluetooth/AirPods**). Garde les blocs dans une petite file d'attente et envoie-les avec ce décalage.
- Si la WebSocket tombe, reconnecte-la en silence (attente progressive : 0,5 s, 1 s, 2 s…).

### 3.2 Morceau en cours `POST /api/nowplaying`
```json
{
  "title": "WpointM",
  "artist": "Tiakola",
  "album": "BDLM",
  "playing": true,
  "source": "Jellyfin",
  "artwork": "<JPEG en base64, ~300×300 px>"
}
```
- **Pochette :** envoie `artwork` quand le morceau change (inutile de la renvoyer ensuite). Le Mac en extrait la palette, et la palette `cover` des LEDs prend ces couleurs avec un fondu de 2 s. Réduis l'image à ~300 px de côté, en JPEG qualité 0,8 (la taille maximale acceptée est ~3 Mo).
- **Pause :** envoie `"playing": false` ; le Mac revient alors au morceau Spotify éventuel.
- **Priorité :** ce morceau passe **avant Spotify** tant qu'il joue. Renvoie-le toutes les ≤ 20 s pendant la lecture, sinon il expire au bout de 45 s.
- Réponse : `{"ok": true, "spotify": {…}}` (le morceau effectivement retenu par le serveur).

---

## 4. La page « Lumières » (design)

Même langage visuel que le reste de l'app (Apple Music) : fonds sombres, grandes cartes arrondies, SF Symbols, typographie système, animations douces. **Peu de réglages visibles.**

- **Accès :** un onglet ou une entrée « Lumières » (icône SF Symbol `lightbulb.led.fill`, ou `sparkles`). Si l'app a un mini-lecteur, ajoute aussi un petit bouton ampoule sur l'écran « En lecture » pour activer « Lumières sur la musique » en un geste.
- **En-tête :** grand titre « Lumières » et, à droite, une pastille de connexion (point vert et nom du Mac ; orange « Reconnexion… » ; gris « Hors ligne », cliquable pour relancer la recherche).
- **Carte héro** (grande, arrondie, fond presque noir) :
  - un **aperçu vivant du ruban** : un rectangle arrondi façon écran, entouré de 32 points lumineux colorés avec `leds.preview` et un léger halo (évite les flous coûteux ; des cercles avec opacité suffisent) ;
  - à côté ou dessous, une **mini-souris** (silhouette) dont le contour, la molette et le logo prennent les couleurs de `mouse.preview` ;
  - un **gros bouton marche/arrêt** rond qui appelle `/api/power` ; allumé, il est rempli d'un dégradé aux couleurs de `leds.palette`.
- **Interrupteur « Lumières sur la musique »** (bien visible, juste sous la carte) : active ou désactive tout le §3. En dessous, une ligne discrète « Synchronisé avec *WpointM* – Tiakola » avec la mini-pochette et un petit égaliseur de 7 barres piloté par `levels`.
- **Ruban :**
  - un sélecteur segmenté des modes, avec les libellés de `catalog.leds.modes`. Le mode `sound` peut s'afficher « Musique » ;
  - une rangée de puces d'effets qui défile horizontalement : `sound_effects` si le mode est `sound`, `ambient_effects` si c'est `ambient`, rien en Écran ;
  - en mode Couleur : deux `ColorPicker` (« Bas » et « Haut ») ;
  - une rangée de **palettes** : des pastilles rondes en dégradé, dont « Pochette » en premier avec la mini-pochette. La sélection est cerclée. Pas de palette en mode Écran ni en mode Couleur ;
  - un **slider de luminosité** (icônes `sun.min` et `sun.max`), qui règle ruban et souris ensemble.
- **Souris** (carte repliable, plus discrète) : interrupteur (`/api/mouse/toggle`) et un `Menu` (Picker) avec `catalog.mouse.modes`. Si le mode est Son, ajoute un petit choix Pulse / Rotation.
- **Réglages** (feuille modale, via une icône engrenage) : « Sensibilité à la musique » (`leds.sensitivity` et `mouse.sensitivity`), « Vitesse des ambiances » (`leds.speed`), le Mac connecté, « Oublier ce Mac » (supprime le jeton) et « Se connecter à un autre Mac ».
- **États :**
  - **Recherche :** animation de recherche, puis liste des Macs trouvés, puis appairage ;
  - **Appairage :** 4 grandes cases de chiffres, avec l'explication « Un code vient de s'afficher sur ton Mac » ;
  - **Mac hors ligne :** carte grisée et bouton « Réessayer » ;
  - **`sleep.on` :** bandeau « Ton Mac est en veille — les lumières reviendront toutes seules ».
- **Réactivité :** toute action met à jour l'UI immédiatement (état optimiste), puis se recale sur le flux temps réel. Haptique légère (`.selection`) sur les changements de mode, d'effet et de palette, et moyenne (`.medium`) sur le bouton marche/arrêt.
- **Performance :** n'écoute `/api/events` que lorsque la page est à l'écran. L'envoi audio, lui, continue en arrière-plan tant que « Lumières sur la musique » est actif et que la musique joue. Limite le rafraîchissement de l'aperçu à 15 images/s.

## 5. Architecture suggérée (Swift / SwiftUI)
- `AmbilightDiscovery` : NWBrowser, résolution de l'IP, repli manuel.
- `AmbilightClient` (`@Observable` / `ObservableObject`, `@MainActor` pour l'état exposé) :
  - l'hôte et le jeton (Keychain) ;
  - l'appairage ;
  - `state`, `catalog` et `live` décodés en `Codable` (champs optionnels partout pour la robustesse) ;
  - `send(config patch)` avec debounce ;
  - la boucle SSE avec reconnexion ;
  - la détection des 401 pour relancer l'appairage.
- `AmbilightAudioStreamer` :
  - capture (tap), conversion en Int16 mono et file d'attente avec le délai de sortie ;
  - `URLSessionWebSocketTask` qui envoie des `.data(...)` ;
  - démarre et s'arrête avec la lecture et l'interrupteur.
- `AmbilightNowPlayingReporter` : écoute le lecteur de l'app (changement de morceau, lecture, pause) et envoie `/api/nowplaying` (pochette redimensionnée en base64), plus un rappel toutes les 20 s.
- `LightsView` (la page) et ses sous-vues : `LEDStripPreview`, `MousePreview`, `PaletteRow`, `EffectChips`, `PairingView`, `DiscoveryView`.

## 6. Tests rapides
1. **Découverte et appairage :** l'app trouve « Ambilight (MacBook Air de Alex) », le code s'affiche sur le Mac, et après saisie l'app montre l'aperçu vivant des LEDs.
2. **Commandes :** le bouton marche/arrêt éteint puis rallume tout, avec une animation sur les LEDs ; les modes, effets, palettes et la luminosité changent en direct.
3. **Musique :** active « Lumières sur la musique » et lance un morceau. `live.audio.source` doit passer à `"network"`, et `levels` bouger au rythme de la musique. Les LEDs réagissent aux basses et prennent les couleurs de la pochette. En pause, le Mac reprend la main tout seul.
4. **Autre point de contrôle :** si tu modifies un réglage sur le Mac (interface web ou télécommande IR), l'app se met à jour toute seule grâce à `cfg`.
