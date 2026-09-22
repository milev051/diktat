#!/bin/bash
# Pokretanje Diktata dvoklikom iz Findera.
#
# Ako postoji Diktat.app, pokrece nju, jer se dozvole za mikrofon i
# Accessibility vezuju za aplikaciju i ne pucaju. Ako je nema, radi kao
# ./run.sh u ovom prozoru terminala.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Nema .venv, pokrecem jednokratnu instalaciju..."
  ./setup.sh
fi

if [ -d Diktat.app ]; then
  open Diktat.app
  echo "Diktat je pokrenut. Ikonica je u traci menija."
  exit 0
fi

exec ./run.sh
