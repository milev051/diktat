#!/bin/bash
# Pokretanje aplikacije:   ./run.sh
# Provera podesavanja:     ./run.sh doctor
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Nema .venv — pokreni prvo ./setup.sh"
  exit 1
fi

if [ "${1:-}" = "doctor" ]; then
  exec .venv/bin/python doctor.py
fi

if [ "${1:-}" = "test" ]; then
  shift
  exec .venv/bin/python selftest.py "$@"
fi

exec .venv/bin/python run.py
