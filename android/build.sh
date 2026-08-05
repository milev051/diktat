#!/bin/bash
# Napravi i instaliraj aplikaciju.
#   ./build.sh          napravi APK (skupljen, ~1.6 MB)
#   ./build.sh install  napravi i posalji na povezan telefon
#   ./build.sh debug    brzi build bez skupljanja (~6 MB)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f local.properties ]; then
  echo "sdk.dir=$HOME/Library/Android/sdk" > local.properties
fi

if [ "${1:-}" = "debug" ]; then
  ./gradlew assembleDebug
  APK=app/build/outputs/apk/debug/app-debug.apk
else
  # Release je skupljen R8-om: bez toga Material biblioteka nadme APK na 6.4 MB.
  # Potpisuje se debug kljucem, pa se instalira preko postojece instalacije.
  ./gradlew assembleRelease
  APK=app/build/outputs/apk/release/app-release.apk
fi

echo
echo "APK: $APK  ($(du -h "$APK" | cut -f1))"

if [ "${1:-}" = "install" ]; then
  if [ -z "$(adb devices | sed '1d' | grep -w device || true)" ]; then
    echo
    echo "Nema povezanog telefona. Ukljuci USB debugging pa:  adb devices"
    exit 1
  fi
  adb install -r "$APK"
  echo "Instalirano."
fi
