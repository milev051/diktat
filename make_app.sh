#!/bin/bash
# Pravi Diktat.app, tanak omotac oko Python-a iz .venv-a.
#
#   ./make_app.sh           napravi Diktat.app u ovom folderu (za razvoj)
#   ./make_app.sh install   instaliraj u /Applications, za dvoklik bez terminala
#
# Zasto uopste bundle: kad se pokrece iz terminala, macOS dozvole (Mikrofon,
# Accessibility) se vezuju za Terminal, pa pucaju cim promenis terminal ili ga
# apdejtujes. Sa svojim bundle-om i potpisom, dozvole se vezuju za samu
# aplikaciju i drze.
#
# Zasto instalacija kopira kod: macOS aplikaciji pokrenutoj iz Launchpad-a
# TIHO zabranjuje citanje ~/Desktop, ~/Documents i ~/Downloads. Projekat je na
# Desktopu, pa je aplikacija pucala na prvom redu, bez ijednog pitanja
# korisniku (mereno: PermissionError na .venv/pyvenv.cfg). Zato `install`
# prepisuje kod i okruzenje u ~/Library/Application Support/Diktat, gde te
# zabrane ne vaze, a ovaj folder ostaje mesto gde se radi.

set -euo pipefail
cd "$(dirname "$0")"
IZVOR="$(pwd)"
# Svaki build nosi svoj broj: dva bundle-a sa istim sadrzajem imaju isti
# potpis, pa macOS ume da na novi primeni staru odluku o starom.
GRADNJA="$(date +%Y%m%d%H%M%S)"
DOM="$HOME/Library/Application Support/Diktat"
CILJ="/Applications/Diktat.app"

if [ ! -x "$IZVOR/.venv/bin/python" ]; then
  echo "Nema .venv — pokreni prvo ./setup.sh"
  exit 1
fi

# --------------------------------------------------------------- ikona
# Crta se iz koda, pa u repozitorijumu ne stoji binarni fajl.
IKONA=""
RADNI="$(mktemp -d)"
IKONSET="$RADNI/Diktat.iconset"
mkdir -p "$IKONSET"
if "$IZVOR/.venv/bin/python" "$IZVOR/ikona.py" "$RADNI/ikona-1024.png" >/dev/null 2>&1; then
  for velicina in 16 32 64 128 256 512; do
    dupla=$((velicina * 2))
    sips -z $velicina $velicina "$RADNI/ikona-1024.png" \
      --out "$IKONSET/icon_${velicina}x${velicina}.png" >/dev/null 2>&1
    sips -z $dupla $dupla "$RADNI/ikona-1024.png" \
      --out "$IKONSET/icon_${velicina}x${velicina}@2x.png" >/dev/null 2>&1
  done
  if iconutil -c icns "$IKONSET" -o "$RADNI/Diktat.icns" 2>/dev/null; then
    IKONA="$RADNI/Diktat.icns"
    echo "Ikona napravljena."
  fi
fi
[ -n "$IKONA" ] || echo "Upozorenje: ikona nije napravljena, ostaje sistemska."

# --------------------------------------------------------------- pokretac
# Glavni izvrsni fajl bundle-a je mali Swift program, ne bash skripta. Kad je
# aplikacija vec pokrenuta, macOS na novi klik ne pokrece nista iznova, nego
# samo posalje dogadjaj "ponovo otvori" procesu koji je pokrenuo. Bash taj
# dogadjaj ne ume da primi, pa se zaglavljena instanca nikako nije gasila
# klikom na ikonicu (mereno: posle `open -a Diktat` u logu nijedna nova
# linija). Swift pokretac primi dogadjaj i pokrene diktat.sh iznova, a ta
# skripta zaustavi staru instancu. Python ostaje njegovo dete, pa dozvole za
# mikrofon i Accessibility i dalje idu na Diktat.
POKRETAC=""
cat > "$RADNI/pokretac.swift" <<'SWIFT'
import AppKit

final class Pokretac: NSObject, NSApplicationDelegate {
    let skripta = Bundle.main.path(forResource: "diktat", ofType: "sh")!
    var tekuci: Process?

    func pokreni() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/bash")
        p.arguments = [skripta]
        p.terminationHandler = { zavrsen in
            DispatchQueue.main.async {
                // Staru skriptu ubija nova, to nije kraj aplikacije.
                if self.tekuci === zavrsen { NSApp.terminate(nil) }
            }
        }
        tekuci = p
        do { try p.run() } catch { NSApp.terminate(nil) }
    }

    func applicationDidFinishLaunching(_ n: Notification) { pokreni() }

    func applicationShouldHandleReopen(_ a: NSApplication, hasVisibleWindows f: Bool) -> Bool {
        pokreni()
        return false
    }
}

let app = NSApplication.shared
let pokretac = Pokretac()
app.delegate = pokretac
app.run()
SWIFT
if swiftc -O -o "$RADNI/Diktat" "$RADNI/pokretac.swift" >/dev/null 2>&1; then
  POKRETAC="$RADNI/Diktat"
  echo "Pokretac preveden."
else
  echo "Upozorenje: swiftc nije uspeo (xcode-select --install), ponovni klik nece gasiti staru instancu."
fi

# --------------------------------------------------------------- bundle
# $1 = gde se pravi, $2 = folder sa kodom, $3 = python koji ga pokrece
napravi_app() {
  local app="$1" root="$2" py="$3"
  rm -rf "$app"
  mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

  cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Diktat</string>
  <key>CFBundleDisplayName</key><string>Diktat</string>
  <key>CFBundleExecutable</key><string>Diktat</string>
  <key>CFBundleIconFile</key><string>Diktat</string>
  <key>CFBundleIdentifier</key><string>studio.room211.diktat</string>
  <key>CFBundleVersion</key><string>$GRADNJA</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Diktat snima govor dok drzis hotkey i pretvara ga u tekst.</string>
  <key>NSDesktopFolderUsageDescription</key>
  <string>Diktat pokrece svoj kod iz foldera projekta.</string>
  <key>NSDocumentsFolderUsageDescription</key>
  <string>Diktat pokrece svoj kod iz foldera projekta.</string>
</dict>
PLIST
  echo "</plist>" >> "$app/Contents/Info.plist"

  # Kad se klikne iz Launchpad-a nema terminala da primi gresku, pa sve ide u
  # log, a ono sto korisnik mora da vidi ide u prozorcic.
  cat > "$app/Contents/Resources/diktat.sh" <<LAUNCHER
#!/bin/bash
ROOT="$root"
PY="$py"
IZVOR="$IZVOR"
LOG="\$HOME/Library/Logs/Diktat.log"

javi() {
  osascript -e "display dialog \"\$1\" buttons {\"U redu\"} default button 1 with title \"Diktat\" with icon caution" >/dev/null 2>&1
}

if [ ! -x "\$PY" ]; then
  javi "Diktat ne nalazi svoje Python okruzenje:\n\n\$PY\n\nPokreni ponovo ./make_app.sh install iz foldera projekta."
  exit 1
fi

# Drugo pokretanje prvo zaustavlja staru instancu, da nikad ne ostanu dva
# hotkey-a i dve ikonice u traci menija. Proces se prepoznaje po radnoj
# putanji, jer run.py u komandnoj liniji ume da bude i relativan. Gleda se i
# instalirana kopija i folder projekta.
for pid in \$(pgrep -f "run\\\\.py" 2>/dev/null); do
  # Mora da bude bas Python. Svaka druga komanda kojoj se "run.py" nadje u
  # komandnoj liniji (grep, pgrep, editor) inace prodje kao pokrenut Diktat,
  # pa aplikacija tiho odustane od pokretanja.
  case "\$(ps -o comm= -p "\$pid" 2>/dev/null)" in
    *[Pp]ython*) ;;
    *) continue ;;
  esac
  putanja="\$(lsof -a -d cwd -p "\$pid" -Fn 2>/dev/null | sed -n 's/^n//p')"
  if [ "\$putanja" = "\$ROOT" ] || [ "\$putanja" = "\$IZVOR" ]; then
    stari_launcher=""
    roditelj="\$(ps -o ppid= -p "\$pid" 2>/dev/null | tr -d ' ')"
    case "\$(ps -o command= -p "\$roditelj" 2>/dev/null)" in
      *"/Diktat.app/Contents/"*) stari_launcher="\$roditelj" ;;
    esac
    echo "Zaustavljam prethodnu instancu (PID \$pid)." >> "\$LOG"
    kill -TERM "\$pid" 2>/dev/null || true
    # Zatvori i njen shell-omotac; inace bi mogao da ceka izlazni kod i
    # prikaze lazni prozor greske za namerno zaustavljanje.
    [ -z "\$stari_launcher" ] || kill -TERM "\$stari_launcher" 2>/dev/null || true
    for cekanje in {1..20}; do
      kill -0 "\$pid" 2>/dev/null || break
      sleep 0.1
    done
    # Ako se aplikacija zaglavila u pozivu biblioteke, ne dozvoli da nova
    # instanca ostane bez mikrofona ili hotkey-a.
    if kill -0 "\$pid" 2>/dev/null; then
      kill -KILL "\$pid" 2>/dev/null || true
    fi
  fi
done

cd "\$ROOT"
mkdir -p "\$HOME/Library/Logs"
echo "--- \$(date '+%Y-%m-%d %H:%M:%S') pokretanje: \$ROOT ---" >> "\$LOG"
"\$PY" "\$ROOT/run.py" >> "\$LOG" 2>&1
kod=\$?
if [ \$kod -ne 0 ] && [ \$kod -ne 143 ] && [ \$kod -ne 137 ]; then
  javi "Diktat se ugasio sa greskom (\$kod).\n\nPoslednje linije su u:\n\$LOG"
fi
exit \$kod
LAUNCHER
  chmod +x "$app/Contents/Resources/diktat.sh"
  if [ -n "$POKRETAC" ]; then
    cp "$POKRETAC" "$app/Contents/MacOS/Diktat"
  else
    cp "$app/Contents/Resources/diktat.sh" "$app/Contents/MacOS/Diktat"
  fi
  chmod +x "$app/Contents/MacOS/Diktat"

  [ -n "$IKONA" ] && cp "$IKONA" "$app/Contents/Resources/Diktat.icns"

  # Ad-hoc potpis daje bundle-u stabilan identitet za TCC bazu dozvola.
  codesign --force --sign - "$app" >/dev/null 2>&1 \
    && echo "Potpisano (ad-hoc): $app" \
    || echo "Upozorenje: codesign nije uspeo za $app, dozvole mozda nece biti trajne."
}

napravi_app "$IZVOR/Diktat.app" "$IZVOR" "$IZVOR/.venv/bin/python"
echo "Napravljeno: $IZVOR/Diktat.app"

# --------------------------------------------------------------- instalacija
if [ "${1:-}" = "install" ]; then
  mkdir -p "$DOM"

  # Podesavanja i kljucevi prezivljavaju svaku ponovnu instalaciju.
  CUVANI=""
  if [ -f "$DOM/app/config.json" ]; then
    CUVANI="$RADNI/config.json"
    cp "$DOM/app/config.json" "$CUVANI"
  fi

  rm -rf "$DOM/app"
  mkdir -p "$DOM/app"
  cp -R dictate run.py doctor.py selftest.py requirements.txt config.example.json "$DOM/app/"
  find "$DOM/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

  # Oznaka poslednjeg izdanja u ovom kodu. Po njoj aplikacija zna da li na
  # GitHub-u postoji novija verzija (Podesavanja > Verzija i azuriranje).
  # Izdanja se prave na GitHub-u (gh release create), pa oznaka lokalno ume
  # da fali dok se ne povuce.
  git -C "$IZVOR" fetch --tags --quiet 2>/dev/null || true
  VERZIJA="$(git -C "$IZVOR" describe --tags --abbrev=0 2>/dev/null || true)"
  if [ -n "$VERZIJA" ]; then
    echo "$VERZIJA" > "$DOM/app/VERZIJA"
    echo "Verzija: $VERZIJA"
  fi

  if [ -n "$CUVANI" ]; then
    cp "$CUVANI" "$DOM/app/config.json"
  elif [ -f config.json ]; then
    cp config.json "$DOM/app/config.json"
    echo "Preuzeta postojeca podesavanja iz config.json."
  fi

  # Okruzenje se prepisuje pri svakoj instalaciji, da ne zaostane iza
  # requirements.txt. Venv nosi apsolutne putanje samo u skriptama koje ne
  # koristimo; `venv/bin/python` racuna prefiks iz svoje putanje.
  rm -rf "$DOM/venv"
  cp -R "$IZVOR/.venv" "$DOM/venv"

  napravi_app "$CILJ" "$DOM/app" "$DOM/venv/bin/python"
  # Bundle se posle potpisa NE dira. `touch` nad njim obara potpis, a macOS
  # tada ubije Python koji aplikacija pokrene, bez ijedne linije u logu.
  #
  # Kad se bundle na istoj putanji zameni, Launch Services zadrzi stari zapis:
  # `open -a Diktat` tada vrati 0 i ne pokrene nista, a isti pokretac pozvan
  # direktno radi. Zato se zapis prvo ponisti pa upise iznova.
  LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  if [ -x "$LSREG" ]; then
    "$LSREG" -u "$CILJ" >/dev/null 2>&1 || true
    "$LSREG" -f "$CILJ" >/dev/null 2>&1 || true
  fi
  echo "Instalirano: $CILJ"
  echo "Kod i okruzenje: $DOM"
  echo
  echo "Otvara se iz Launchpad-a, Spotlight-a (cmd+razmak pa 'Diktat') ili iz"
  echo "Finder-a, folder Applications. Terminal vise nije potreban."
  echo
  echo "Posle izmene koda u ovom folderu, pokreni ponovo:  ./make_app.sh install"
else
  echo
  echo "Za ikonu u Launchpad-u i Spotlight-u:  ./make_app.sh install"
fi

rm -rf "$RADNI"

echo
echo "Prvi put odobri:"
echo "  System Settings > Privacy & Security > Microphone     -> Diktat"
echo "  System Settings > Privacy & Security > Accessibility  -> Diktat"
echo
echo "Za autostart: System Settings > General > Login Items > '+' > Diktat.app"
