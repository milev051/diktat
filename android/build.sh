#!/bin/bash
# Napravi i instaliraj probnu aplikaciju.
#   ./build.sh          samo napravi APK
#   ./build.sh install  napravi i posalji na povezan telefon
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f local.properties ]; then
  echo "sdk.dir=$HOME/Library/Android/sdk" > local.properties
fi

./gradlew assembleDebug
APK=app/build/outputs/apk/debug/app-debug.apk
echo
echo "APK: $APK  ($(du -h "$APK" | cut -f1))"

if [ "${1:-}" = "install" ]; then
  if [ -z "$(adb devices | sed '1d' | grep -w device || true)" ]; then
    echo
    echo "Nema povezanog telefona. Ukljuci USB debugging pa:"
    echo "  adb devices"
    exit 1
  fi
  adb install -r "$APK"
  adb shell monkey -p studio.room211.diktatproba -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  echo "Instalirano i pokrenuto."
fi
