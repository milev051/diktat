#!/bin/bash
# Jednokratna instalacija.
set -euo pipefail
cd "$(dirname "$0")"

PY=/opt/homebrew/bin/python3.13
if [ ! -x "$PY" ]; then
  echo "Nedostaje Python 3.13. Instaliraj sa:  brew install python@3.13"
  exit 1
fi

if ! brew list portaudio >/dev/null 2>&1; then
  echo "Instaliram portaudio..."
  brew install portaudio
fi

echo "Pravim .venv..."
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/pip install --quiet -r requirements.txt

if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Napravljen config.json — upisi putanju do Google kljuca."
fi

echo
echo "Gotovo. Sledeci korak:  ./run.sh doctor"
