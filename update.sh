#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Ambilight – installation / mise à jour en une commande
#
#    ./update.sh              met à jour ce qui a changé et relance l'app
#    ./update.sh --flash      force le reflash de l'Arduino
#    ./update.sh --rebuild    force la reconstruction de Ambilight.app
#    ./update.sh --no-autostart   ne pas lancer Ambilight à l'ouverture de session
#
#  Ce qui est fait (seulement si nécessaire) :
#    1. environnement Python + dépendances (requirements.txt)
#    2. firmware Arduino compilé et flashé (sources modifiées)
#    3. ~/Applications/Ambilight.app reconstruite (lanceur / icône modifiés)
#    4. lancement automatique à l'ouverture de session
#    5. redémarrage de l'app (icône dans la barre de menus)
#
#  Pendant que l'app tourne, les modifications du code Python et de
#  l'interface web, des dépendances et du firmware sont de toute façon
#  appliquées automatiquement. Ce script sert surtout à la 1re installation
#  et quand le lanceur macOS change.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$ROOT/client"
STATE="$HOME/.ambilight"
APP="$HOME/Applications/Ambilight.app"
URL="http://127.0.0.1:8787"
mkdir -p "$STATE"

FORCE_FLASH=0; FORCE_BUILD=0; AUTOSTART=1
for a in "$@"; do
  case "$a" in
    --flash) FORCE_FLASH=1 ;;
    --rebuild) FORCE_BUILD=1 ;;
    --no-autostart) AUTOSTART=0 ;;
    *) echo "option inconnue : $a"; exit 1 ;;
  esac
done

step() { printf "\n\033[1;35m▸ %s\033[0m\n" "$1"; }
hash_of() { cat "$@" 2>/dev/null | shasum | cut -c1-40; }

LAUNCHER="Ambilight.app/Contents/MacOS/Ambilight"
stop_server() {
  if curl -s -m 1 "$URL/api/state" >/dev/null 2>&1; then
    echo "  arrêt d'Ambilight…"
    curl -s -m 2 -X POST "$URL/api/quit" >/dev/null 2>&1 || true
  fi
  # Attendre la vraie fin des processus (sinon macOS « réactive » l'instance
  # qui s'arrête au lieu d'en lancer une nouvelle).
  for _ in $(seq 1 60); do
    pgrep -f "$LAUNCHER" >/dev/null || pgrep -f "$CLIENT/server.py" >/dev/null || return 0
    sleep 0.1
  done
  pkill -f "$CLIENT/server.py" 2>/dev/null || true
  pkill -f "$LAUNCHER" 2>/dev/null || true
  sleep 0.5
}

# 1 ── Python ─────────────────────────────────────────────────────────────────
step "Environnement Python"
if [ ! -x "$CLIENT/.venv/bin/python" ]; then
  PY=python3
  [ -x /Library/Frameworks/Python.framework/Versions/Current/bin/python3 ] && PY=/Library/Frameworks/Python.framework/Versions/Current/bin/python3
  echo "  création du venv avec $PY"
  "$PY" -m venv "$CLIENT/.venv"
fi
REQ_HASH="$(hash_of "$CLIENT/requirements.txt")"
if [ "$REQ_HASH" != "$(cat "$STATE/requirements.hash" 2>/dev/null || true)" ]; then
  "$CLIENT/.venv/bin/python" -m pip install -q --upgrade pip
  "$CLIENT/.venv/bin/python" -m pip install -q -r "$CLIENT/requirements.txt"
  echo "$REQ_HASH" > "$STATE/requirements.hash"
  echo "  dépendances installées ✓"
else
  echo "  à jour"
fi

# 2 ── Firmware ───────────────────────────────────────────────────────────────
step "Firmware Arduino"
cd "$CLIENT"
if [ $FORCE_FLASH = 1 ] || .venv/bin/python -c "import sys; from core.updater import firmware_outdated; sys.exit(0 if firmware_outdated() else 1)"; then
  stop_server
  .venv/bin/python -m core.updater flash --force
else
  echo "  à jour"
fi

# 3 ── App macOS ──────────────────────────────────────────────────────────────
step "Ambilight.app"
APP_HASH="$(hash_of "$CLIENT/macos/launcher.c" "$CLIENT/macos/Info.plist" "$CLIENT/macos/build_app.sh" "$CLIENT/Icon.png"; echo "$CLIENT")"
APP_HASH="$(echo "$APP_HASH" | shasum | cut -c1-40)"
if [ $FORCE_BUILD = 1 ] || [ ! -d "$APP" ] || [ "$APP_HASH" != "$(cat "$STATE/app.hash" 2>/dev/null || true)" ]; then
  stop_server
  "$CLIENT/macos/build_app.sh"
  echo "$APP_HASH" > "$STATE/app.hash"
  echo "  (si macOS redemande les autorisations micro / écran / entrées, accepte-les pour « Ambilight »)"
else
  echo "  à jour"
fi

# 4 ── Démarrage automatique ──────────────────────────────────────────────────
step "Lancement à l'ouverture de session"
if [ $AUTOSTART = 1 ]; then
  .venv/bin/python -c "from core import autostart; autostart.enable()" && echo "  activé ✓"
else
  .venv/bin/python -c "from core import autostart; autostart.disable()" && echo "  désactivé"
fi

# 5 ── Relance ────────────────────────────────────────────────────────────────
step "Relance d'Ambilight"
stop_server
open -g -a "$APP" --args --no-browser
for _ in $(seq 1 60); do
  curl -s -m 0.3 "$URL/api/state" >/dev/null 2>&1 && break
  sleep 0.1
done
if curl -s -m 1 "$URL/api/state" >/dev/null 2>&1; then
  echo "  ✓ Ambilight tourne (icône dans la barre de menus) → $URL"
else
  echo "  ✗ l'app ne répond pas, voir ~/Library/Logs/Ambilight/server.log"
  exit 1
fi
