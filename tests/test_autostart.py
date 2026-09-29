"""LaunchAgent za automatsko pokretanje, bez izmene korisničkog sistema."""

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dictate import autostart


class Autostart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name, value in (
            ("AGENT", root / "LaunchAgents" / "diktat.plist"),
            ("APP", root / "Diktat.app"),
            ("INSTALLED_ROOT", root / "app"),
        ):
            patcher = mock.patch.object(autostart, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root_patch = mock.patch.object(autostart.config, "ROOT", autostart.INSTALLED_ROOT)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        autostart.APP.mkdir()

    def test_ukljuci_i_iskljuci(self):
        autostart.sync(True)
        data = plistlib.loads(autostart.AGENT.read_bytes())
        self.assertEqual(data["ProgramArguments"], ["/usr/bin/open", "-a", str(autostart.APP)])
        self.assertTrue(data["RunAtLoad"])
        with mock.patch.object(autostart.subprocess, "run") as run:
            autostart.sync(False)
        self.assertFalse(autostart.AGENT.exists())
        self.assertEqual(run.call_count, 1)

    def test_razvojna_kopija_ne_menja_launchagent(self):
        with mock.patch.object(autostart.config, "ROOT", Path(self.tmp.name)):
            autostart.sync(True)
        self.assertFalse(autostart.AGENT.exists())


if __name__ == "__main__":
    unittest.main()
