#!/bin/bash
# Instalacija ili azuriranje Diktata dvoklikom iz Findera.
#
# Prvi put: pravi /Applications/Diktat.app. Posle toga menja samo kod
# instalirane aplikacije i pokrece je iznova, pa dozvole za Mikrofon i
# Accessibility ostaju. Punu instalaciju radi samo kad se promeni pokretac
# (vidi make_app.sh, `azuriraj`).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Nema .venv, pokrecem jednokratnu instalaciju..."
  ./setup.sh
fi

# Na kraju sam pokrene Diktat (ili ga pokrene iznova, ako vec radi).
./make_app.sh azuriraj
