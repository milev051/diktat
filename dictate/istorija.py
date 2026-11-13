"""Trajna istorija i nezavisni dnevnik svake verzije prikazanog prepisa.

Lični tekst se čuva lokalno, van repozitorijuma. Dnevnik se samo dopisuje:
kasniji prazan ili kraći rezultat ne može obrisati prethodnu verziju.
"""

import json
import os
import time
import uuid
from pathlib import Path

FOLDER = Path.home() / "Library" / "Application Support" / "Diktat" / "prepisi"
# Isto na telefonu (Config.historyLimit). Prozor pokazuje pet, ostalo se skroluje.
NAJVISE_PREPISKA = 100


class Arhiva:
    def __init__(self, folder=FOLDER):
        self.folder = Path(folder)
        self.stavke = {}
        self._ucitaj()

    def _prihvati(self, item):
        if not isinstance(item, dict):
            return
        key, text, stamp = item.get("id"), item.get("text"), item.get("time")
        if not (isinstance(key, str) and isinstance(text, str) and text.strip()
                and isinstance(stamp, int)):
            return
        if stamp >= self.stavke.get(key, {}).get("time", 0):
            self.stavke[key] = item

    def _ucitaj(self):
        try:
            for item in json.loads((self.folder / "istorija.json").read_text(encoding="utf-8")):
                self._prihvati(item)
        except (OSError, ValueError, TypeError):
            pass
        # Svaka linija je samostalna; prekinut poslednji upis ne gubi ranije.
        for path in self.folder.glob("*.jsonl"):
            try:
                with path.open(encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        try:
                            self._prihvati(json.loads(line))
                        except ValueError:
                            pass
            except OSError:
                continue

    def istorija(self, limit=NAJVISE_PREPISKA):
        texts = []
        for item in sorted(self.stavke.values(), key=lambda x: x["time"], reverse=True):
            if item["text"] not in texts:
                texts.append(item["text"])
            if len(texts) >= limit:
                break
        return texts

    def sacuvaj(self, text, key=None):
        key = key or uuid.uuid4().hex
        item = {"id": key, "text": text, "time": time.time_ns()}
        self.stavke[key] = item
        journal_ok = snapshot_ok = False
        try:
            self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Filename is generated here; arbitrary session names never become paths.
            name = uuid.uuid5(uuid.NAMESPACE_OID, key).hex + ".jsonl"
            fd = os.open(self.folder / name, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                # Leading newline separates a partially written record after a crash.
                handle.write("\n" + json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            journal_ok = True
        except OSError:
            pass
        temp = self.folder / (".istorija-" + uuid.uuid4().hex)
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(list(self.stavke.values()), handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.folder / "istorija.json")
            snapshot_ok = True
        except OSError:
            pass
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return journal_ok or snapshot_ok
