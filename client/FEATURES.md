# 🎨 Ambilight v2.5+ - Nouvelles Fonctionnalités

## 🔊 Capture Audio Multi-Source

### Sources disponibles
- **🎤 Micro** : Capture via microphone système (sounddevice)
- **🖥 Système** : Capture du son généré par votre Mac via ffmpeg
- **♫ Spotify** : Détection automatique avec palette couleur extraite de la cover (AppleScript)

### Comment ça fonctionne
1. Dans la section "Sound Ambient", choisissez votre source audio
2. Pour **Système Mac** : Utilise ffmpeg pour capturer l'audio système
   - Sur Mac avec Soundflower/BlackHole installé : détection automatique
   - Sinon : utilise l'entrée audio par défaut
3. Pour **Spotify** : Détecte automatiquement quand vous lancez Spotify et extrait les couleurs dominantes de la cover pour teinter les LEDs

---

## 🎨 Visualiseurs Améliorés (Multicolore)

### 3 Effets Disponibles

**1. Spectre** (par défaut)
- Chaque zone des LEDs correspond à une bande de fréquence
- Basses (rouge/chaud) → Médiums (vert) → Aigus (bleu/froid)
- Mapping spatial : Bas de l'écran = basses, haut = aigus

**2. Ondes** (Ripples)
- Ondes colorées déclenchées par les beats des basses
- Propage depuis les extrémités vers le centre
- Palette Spotify si disponible, sinon dégradé dynamique

**3. Barres** (Frequency Bars) ✨ NOUVEAU
- Chaque LED = bande de fréquence distincte
- Hauteur = intensité, couleur = fréquence
- Ressemble à un visualiseur audio classique mais circulaire

---

## 🎚️ Curseurs Temps Réel

### Intensité Audio 🔊
- **Range** : 50% - 200%
- Augmentez pour amplifier la réactivité aux sons faibles
- Diminuez pour éviter la saturation sur musique forte
- *Appliqué en temps réel pendant la lecture*

### Intensité Lumineuse 💡
- **Range** : 10% - 200%
- Contrôle indépendant de la luminosité des LEDs
- Utile pour adapter à l'ambiance de la pièce
- Différent du slider "Luminosité Globale" (celui-ci est toujours appliqué)
- *Appliqué en temps réel pendant la lecture*

---

## 🎯 Gestion Avancée des Couleurs

- **Palette Spotify** : Si Spotify joue, les couleurs dominantes de la cover teignent automatiquement le visualiseur
- **Dégradé Fréquence** : Chaque fréquence a sa propre teinte
- **Lissage Temporel** : Les couleurs transitionent en douceur entre les frames
- **Saturation Boost** : Renforcez la vivacité des couleurs

---

## ⚙️ Configuration (config.json)

Nouveaux paramètres :
```json
{
  "audio_source": "mic",              // "mic", "system", ou "spotify"
  "audio_intensity": 1.0,             // 0.5 - 2.0
  "realtime_brightness": 1.0,        // 0.1 - 2.0
  "sound_effect": "spectrum",         // "spectrum", "ripples", ou "frequency_bars"
  "sound_hue_speed": 0.05,           // Vitesse drift couleurs
  "sound_smoothing": 0.3             // Réactivité audio
}
```

---

## 💡 Tips d'Utilisation

### Pour une meilleure expérience :

1. **Avec Spotify** :
   - Lancez Spotify avant de démarrer Ambilight
   - Les couleurs des LEDs s'adapteront automatiquement à chaque morceau
   - L'intensité audio: ~120% pour la plupart des chansons

2. **Avec l'Audio Système** :
   - Parfait pour regarder des films/streams
   - Intensité lumineuse: 150% pour plus d'impact
   - Effet "Barres" pour une visualisation type equalizer

3. **Avec le Micro** :
   - Idéal pour DJ/live performance
   - Requiert un microphone de bonne qualité
   - Intensité audio: 80-120% selon le gain du micro

4. **Ajustement du Lissage Audio** :
   - **Bas (5-20%)** = Très réactif, saccadé
   - **Moyen (30-50%)** = Recommandé pour la plupart
   - **Haut (60-90%)** = Lisse mais moins réactif

---

## 🐛 Troubleshooting

### "Audio système ne fonctionne pas"
- Sur Mac, assurez-vous que ffmpeg est installé : `brew install ffmpeg`
- Vérifiez les permissions d'accès audio dans Paramètres Système
- Fallback : Utilisez le micro avec speaker à proximité

### "Spotify non détecté"
- Lancez Spotify AVANT de démarrer Sound Ambient
- Vérifiez que Spotify est en lecture
- Acceptez les permissions AppleScript quand demandé

### "Couleurs trop ternes/flashy"
- Ajustez "Intensité lumineuse" et "Saturation boost"
- Vérifiez "Luminosité Globale" aussi
- Essayez un autre effet (Spectre vs Barres vs Ondes)

---

## 🚀 Prochaines Améliorations Possibles

- [ ] Support du son système sur Windows/Linux
- [ ] Détection de beats plus avancée
- [ ] Presets de couleurs personnalisés
- [ ] Micro-equalizer pour ajustement fréquence par fréquence
- [ ] Enregistrement/playback de patterns
