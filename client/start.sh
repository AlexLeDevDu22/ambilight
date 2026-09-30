#!/bin/bash
# Lance le serveur Ambilight et ouvre l'interface (http://127.0.0.1:8787).
cd "$(dirname "$0")"
exec ./.venv/bin/python -u server.py "$@"
