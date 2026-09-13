#!/bin/bash
# Pokretanje aplikacije:   ./run.sh
# Provera podesavanja:     ./run.sh doctor
# Snimi i prepisi 5s:      ./run.sh test 5
# Pusti postojeci WAV:     ./run.sh replay ~/snimak.wav
# Testovi logike:          ./run.sh tests
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Nema .venv — pokreni prvo ./setup.sh"
  exit 1
fi

if [ "${1:-}" = "doctor" ]; then
  exec .venv/bin/python doctor.py
fi

if [ "${1:-}" = "tests" ]; then
  # Bez mikrofona i bez mreze — cista logika, za proveru posle izmene.
  exec .venv/bin/python -m unittest discover -s tests "${@:2}"
fi

if [ "${1:-}" = "test" ]; then
  shift
  exec .venv/bin/python selftest.py "$@"
fi

# Pusti postojeci WAV kroz izabrani izvor, bez ponovnog diktiranja.
if [ "${1:-}" = "replay" ]; then
  exec .venv/bin/python selftest.py "$@"
fi

exec .venv/bin/python run.py
