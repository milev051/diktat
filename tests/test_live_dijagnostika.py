"""Dijagnostika razdvaja zastoj slanja, odgovor servera i red upisa."""

import tempfile
import time
import unittest
from pathlib import Path

from dictate.dijagnostika import LiveTrace


class Trace(unittest.TestCase):
    def test_zastoj_slanja_i_citanja_bez_sadrzaja_govora(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "live.log"
            trace = LiveTrace(7, path)
            trace.mark("send_start")
            trace.sending_since = time.monotonic() - 2
            self.assertIn("Slanje zvuka stoji", trace.snapshot())
            trace.mark("send_done", 3200)
            trace.first_audio = time.monotonic() - 4
            self.assertIn("Gemini nema novog prepisa", trace.snapshot())
            trace.mark("interim", 14)
            trace.mark("field_skip", "polje ne dozvoljava Accessibility upis")
            self.assertIn("Upis u polje preskočen", path.read_text())
            self.assertNotIn("izgovorene reči", path.read_text())


if __name__ == "__main__":
    unittest.main()
