"""Pokretanje instaliranog Diktata pri prijavi korisnika na macOS."""

import os
import plistlib
import subprocess
from pathlib import Path

from . import config

LABEL = "studio.room211.diktat.autostart"
AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
APP = Path("/Applications/Diktat.app")
INSTALLED_ROOT = Path.home() / "Library" / "Application Support" / "Diktat" / "app"


def sync(enabled: bool) -> None:
    """Uskladi LaunchAgent sa izborom korisnika, samo iz instalirane kopije."""
    if config.ROOT != INSTALLED_ROOT:
        return
    if enabled:
        if not APP.is_dir():
            raise FileNotFoundError(f"Nije pronađena aplikacija: {APP}")
        data = plistlib.dumps({
            "Label": LABEL,
            "ProgramArguments": ["/usr/bin/open", "-a", str(APP)],
            "RunAtLoad": True,
        })
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        if not AGENT.exists() or AGENT.read_bytes() != data:
            AGENT.write_bytes(data)
    elif AGENT.exists():
        # Ukloni i već učitan posao, da ga launchd ne vrati pri sledećoj prijavi.
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
            capture_output=True, check=False,
        )
        AGENT.unlink()
