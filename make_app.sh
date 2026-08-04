#!/bin/bash
# Pravi Diktat.app — tanak omotac oko .venv/bin/python.
#
# Zasto: kad se pokrece iz terminala, macOS dozvole (Mikrofon, Accessibility)
# se vezuju za Terminal, pa pucaju cim promenis terminal ili ga apdejtujes.
# Sa svojim bundle-om i potpisom, dozvole se vezuju za samu aplikaciju i drze.

set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
APP="$ROOT/Diktat.app"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Nema .venv — pokreni prvo ./setup.sh"
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Diktat</string>
  <key>CFBundleDisplayName</key><string>Diktat</string>
  <key>CFBundleExecutable</key><string>Diktat</string>
  <key>CFBundleIdentifier</key><string>studio.room211.diktat</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Diktat snima govor dok drzis hotkey i pretvara ga u tekst.</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Diktat" <<LAUNCHER
#!/bin/bash
cd "$ROOT"
exec "$ROOT/.venv/bin/python" "$ROOT/run.py"
LAUNCHER

chmod +x "$APP/Contents/MacOS/Diktat"

# Ad-hoc potpis daje bundle-u stabilan identitet za TCC bazu dozvola.
codesign --force --sign - "$APP" >/dev/null 2>&1 \
  && echo "Potpisano (ad-hoc)." \
  || echo "Upozorenje: codesign nije uspeo — dozvole mozda nece biti trajne."

echo "Napravljeno: $APP"
echo
echo "Pokreni ga jednom dvoklikom, pa odobri:"
echo "  System Settings > Privacy & Security > Microphone     -> Diktat"
echo "  System Settings > Privacy & Security > Accessibility  -> Diktat"
echo
echo "Za autostart: System Settings > General > Login Items > '+' > Diktat.app"
