"""Gemini 3.5 Transcribe Live — oblik setup poruke i citanje odgovora.

Bez mreze: proverava se sta se salje i kako se cita ono sto stigne. Endpoint se
ne moze pozvati u testu, pa je ovo jedina odbrana od tihe greske u imenu polja.
"""

import unittest

from dictate import config, geministt


BAZA = {
    "sample_rate": 16000,
    "language": "sr-RS",
    "polish_api_key": "kljuc",
    "vocabulary": "AI, API, Gemini",
    "lowercase": True,
    "strip_punctuation": True,
    "abbreviations": False,
    "ascii_diacritics": False,
}


def cfg(**kw):
    c = dict(BAZA)
    c.update(kw)
    return c


class LazniWs:
    """Nosi samo ono sto `_zatvoreno` i `_prolazno` gledaju."""

    def __init__(self, code=None, reason=""):
        self.close_code = code
        self.close_reason = reason


class Izbor(unittest.TestCase):
    def test_prepoznaje_svoj_izvor(self):
        self.assertTrue(geministt.enabled(cfg(transcription_provider="gemini_live")))

    def test_ostali_izvori_ga_ne_ukljucuju(self):
        self.assertFalse(geministt.enabled(cfg(transcription_provider="google")))
        self.assertFalse(geministt.enabled(cfg(transcription_provider="openai")))
        self.assertFalse(geministt.enabled(cfg()))

    def test_obicni_transcribe_je_uklonjen(self):
        # 25 zahteva dnevno na besplatnom nivou ne znaci nista za svakodnevni
        # rad. Zatecena vrednost mora da padne na Google, ne da tiho ostane
        # izbor koji vise ne postoji.
        self.assertNotIn("gemini", config.PROVIDERS)
        self.assertFalse(geministt.enabled(cfg(transcription_provider="gemini")))
        pao = config._migrate(dict(config.DEFAULTS, transcription_provider="gemini"))
        self.assertEqual(pao["transcription_provider"], "google")

    def test_model_je_live(self):
        self.assertEqual(geministt.model_for(), geministt.LIVE_MODEL)


class Recnik(unittest.TestCase):
    def test_deli_po_zarezu_i_novom_redu(self):
        self.assertEqual(
            geministt.vocabulary(cfg(vocabulary="AI, API\nGemini")),
            ["AI", "API", "Gemini"],
        )

    def test_izbacuje_duple_i_prazne(self):
        self.assertEqual(
            geministt.vocabulary(cfg(vocabulary="AI, , AI,API,")), ["AI", "API"]
        )

    def test_postuje_granicu_od_1000(self):
        spisak = ",".join(f"p{i}" for i in range(1200))
        self.assertEqual(len(geministt.vocabulary(cfg(vocabulary=spisak))), 1000)

    def test_prazno_polje_daje_prazan_spisak(self):
        self.assertEqual(geministt.vocabulary(cfg(vocabulary="")), [])


class Setup(unittest.TestCase):
    def test_trazi_tekst_i_prepis(self):
        setup = geministt._live_setup(cfg())["setup"]
        self.assertEqual(setup["model"], f"models/{geministt.LIVE_MODEL}")
        self.assertEqual(setup["generationConfig"]["responseModalities"], ["TEXT"])
        self.assertEqual(setup["inputAudioTranscription"]["languageCodes"], ["sr-RS"])

    def test_prazan_jezik_pada_na_podrazumevani(self):
        # Prazan spisak bi znacio "sam prepoznaj jezik" — model tada ume da
        # odluta na hrvatski ili bosanski, pa uvek ide nagovestaj.
        setup = geministt._live_setup(cfg(language=""))["setup"]
        self.assertEqual(
            setup["inputAudioTranscription"]["languageCodes"], ["sr-RS"]
        )

    def test_serijalizuje_se_kao_json(self):
        import json
        json.dumps(geministt._live_setup(cfg()))


class Odgovor(unittest.TestCase):
    def test_cita_konacan_prepis(self):
        poruka = {"serverContent": {"inputTranscription": {"text": "zdravo"}}}
        self.assertEqual(geministt._live_text(poruka), "zdravo")

    def test_cita_i_snake_case(self):
        poruka = {"server_content": {"input_transcription": {"text": "zdravo"}}}
        self.assertEqual(geministt._live_text(poruka), "zdravo")

    def test_medjurezultat_nije_konacan_prepis(self):
        poruka = {"serverContent": {"interimInputTranscription": {"text": "zdra"}}}
        self.assertEqual(geministt._live_text(poruka), "")
        self.assertEqual(geministt._live_interim(poruka), "zdra")

    def test_medjurezultat_i_snake_case(self):
        poruka = {"server_content": {"interim_input_transcription": {"text": "zdra"}}}
        self.assertEqual(geministt._live_interim(poruka), "zdra")

    def test_prazna_poruka(self):
        self.assertEqual(geministt._live_text({}), "")
        self.assertEqual(geministt._live_interim({}), "")

    def test_kraj_celine_nije_kraj_diktata(self):
        """`generationComplete` stize posle SVAKE izgovorene celine.

        Izmereno na snimku od 19s sa dve pauze: stigao je tri puta. Prekid na
        njemu je odbacivao sve posle prve pauze — to je bio bug zbog kog je od
        17 sekundi govora stizala samo prva recenica. Zato ta zastavica vise
        nema svoju funkciju: citanje se zavrsava tisinom, ne njome.
        """
        self.assertFalse(hasattr(geministt, "_live_done"))


class RazlogZatvaranja(unittest.TestCase):
    """CLOSE okvir je JEDINI trag zasto je sesija pala.

    Izmereno na zivom endpointu 28.08.2026: mrtav kljuc se javlja kao
    `CLOSE 1007: API key not valid`. Bez citanja tog razloga korisnik vidi samo
    „veza zatvorena" i nema pojma da je problem u kljucu.
    """

    def test_razlog_ulazi_u_poruku(self):
        ws = LazniWs(1007, "API key not valid. Please pass a valid API key.")
        self.assertIn("API key not valid", geministt._zatvoreno(ws))

    def test_bez_razloga_ostaje_kod(self):
        self.assertIn("1011", geministt._zatvoreno(LazniWs(1011, "")))

    def test_bez_ijednog_traga(self):
        self.assertIn("bez odgovora", geministt._zatvoreno(LazniWs()))

    def test_mrtav_kljuc_se_ne_ponavlja(self):
        self.assertFalse(geministt._prolazno(LazniWs(1007, "API key not valid.")))

    def test_prolazan_otkaz_se_ponavlja(self):
        self.assertTrue(geministt._prolazno(LazniWs(1011, "internal error")))
        self.assertTrue(geministt._prolazno(LazniWs(1006, "")))


class Strimovanje(unittest.TestCase):
    """Zvuk ide DOK snimanje traje — 0.0s cekanja umesto 15.6s na 64.7s zvuka.

    Komadi sa mikrofona ne padaju na granicu od 100ms, pa se ostatak nosi u
    sledeci prolaz; slanje krnjih okvira razbija prepoznavanje po sredini reci.
    """

    def posalji(self, komadi, rate=16000):
        """Presretni okvire umesto da se ide na mrezu."""
        poslato = []

        class LazniWs:
            close_code = close_reason = None

            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
            def send_json(self_, poruka):
                ulaz = (poruka.get("realtimeInput") or {})
                if "audio" in ulaz:
                    import base64
                    poslato.append(base64.b64decode(ulaz["audio"]["data"]))
            def recv_json(self_):
                if not hasattr(self_, "_dat"):
                    self_._dat = True
                    return {"setupComplete": {}}
                return None
            def set_timeout(self_, s): pass

        stari = geministt.WebSocket
        geministt.WebSocket = lambda *a, **k: LazniWs()
        try:
            geministt.recognize_stream(komadi, cfg(sample_rate=rate))
        except geministt.GeminiSttError:
            pass                     # nema prepisa; nas zanima samo sta je poslato
        finally:
            geministt.WebSocket = stari
        return poslato

    def test_ceo_zvuk_stigne_plus_rep_tisine(self):
        rate = 16000
        komad = b"\x01\x02" * 800        # 100ms
        poslato = self.posalji([komad] * 3, rate)
        rep = int(rate * geministt.LIVE_TAIL_SILENCE) * 2
        self.assertEqual(len(b"".join(poslato)), len(komad) * 3 + rep)

    def test_krnji_komadi_se_spajaju(self):
        # 250 bajtova nije pun okvir od 100ms; ne sme da ode sam.
        rate = 16000
        korak = (rate // 1000) * geministt.LIVE_CHUNK_MS * 2
        poslato = self.posalji([b"\x01" * 250] * 40, rate)
        rep = int(rate * geministt.LIVE_TAIL_SILENCE) * 2
        self.assertEqual(len(b"".join(poslato)), 250 * 40 + rep)
        # Svi okviri osim poslednjeg su pune velicine.
        for okvir in poslato[:-1]:
            self.assertEqual(len(okvir), korak)

    def test_prazni_komadi_se_preskacu(self):
        poslato = self.posalji([b"", b"\x01\x02" * 800, b""])
        self.assertTrue(poslato)


class DveStrpljivosti(unittest.TestCase):
    """Kratka pauza kad je celina gotova, duga kad je jos u letu.

    Izmereno: posle Stop-a server je gotov za 0.5s bez obzira na duzinu
    diktata, pa je sve preko toga bila nasa tempirana pauza. Ali ako je celina
    zapoceta a nije finalizovana, kratak prekid bi je odsekao — zato dva roka.
    """

    def odigraj(self, poruke):
        """Pusti niz poruka; `None` glumi istek roka (tisinu)."""
        redosled = list(poruke)
        rokovi = []

        class LazniWs:
            close_code = close_reason = None

            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
            def send_json(self_, poruka): pass
            def set_timeout(self_, s): rokovi.append(s)

            def recv_json(self_):
                if not redosled:
                    raise geministt.WebSocketError("tisina")
                sledeca = redosled.pop(0)
                if sledeca is None:
                    raise geministt.WebSocketError("tisina")
                return sledeca

        stari = geministt.WebSocket
        geministt.WebSocket = lambda *a, **k: LazniWs()
        try:
            tekst = geministt.recognize_stream([b"\x01\x02" * 800], cfg())
        finally:
            geministt.WebSocket = stari
        return tekst, rokovi

    def test_posle_finala_kratak_rok(self):
        tekst, rokovi = self.odigraj([
            {"setupComplete": {}},
            {"serverContent": {"inputTranscription": {"text": "gotovo"}}},
            None,
        ])
        self.assertEqual(tekst, "gotovo")
        # Posle svakog finala se rok vraca na kratak.
        self.assertEqual(rokovi[-1], geministt.LIVE_QUIET_SECONDS)

    def test_celina_u_letu_dobija_pun_rok(self):
        # Medjurezultat bez finala, pa tisina: mora da se produzi jednom i
        # sacekamo finale, umesto da se odsece.
        tekst, rokovi = self.odigraj([
            {"setupComplete": {}},
            {"serverContent": {"interimInputTranscription": {"text": "poce"}}},
            None,                                   # kratka tisina
            {"serverContent": {"inputTranscription": {"text": "pocetak i kraj"}}},
            None,
        ])
        self.assertEqual(tekst, "pocetak i kraj")
        self.assertIn(geministt.LIVE_IDLE_SECONDS, rokovi)

    def test_produzava_se_samo_jednom(self):
        # Ako ni posle punog roka nista ne stigne, uzima se medjurezultat —
        # pola prepisa je bolje nego nista.
        tekst, _ = self.odigraj([
            {"setupComplete": {}},
            {"serverContent": {"interimInputTranscription": {"text": "pola"}}},
            None,
            None,
        ])
        self.assertEqual(tekst, "pola")

    def test_kratak_rok_je_kraci_od_punog(self):
        self.assertLess(geministt.LIVE_QUIET_SECONDS, geministt.LIVE_IDLE_SECONDS)


class Greske(unittest.TestCase):
    def test_bez_kljuca_ne_zove_mrezu(self):
        with self.assertRaises(geministt.GeminiSttError) as ctx:
            geministt.recognize(b"\x00\x01" * 5000, cfg(polish_api_key=""))
        self.assertFalse(ctx.exception.retryable)

    def test_prekratak_snimak_se_ne_salje(self):
        with self.assertRaises(geministt.GeminiSttError) as ctx:
            geministt.recognize(b"\x00" * 100, cfg())
        self.assertFalse(ctx.exception.retryable)

    def test_prazan_snimak_vraca_prazno(self):
        self.assertEqual(geministt.recognize(b"", cfg()), "")

    def _broji_pokusaje(self, retryable):
        pokusaji = []

        def puca(pcm, cfg_, timeout=180):
            pokusaji.append(1)
            raise geministt.GeminiSttError("otkaz", retryable=retryable)

        stari, geministt.recognize_live = geministt.recognize_live, puca
        stara_pauza, geministt.RETRY_WAIT = geministt.RETRY_WAIT, 0
        try:
            with self.assertRaises(geministt.GeminiSttError):
                geministt.recognize(
                    b"\x00\x01" * 5000, cfg(transcription_provider="gemini_live")
                )
        finally:
            geministt.recognize_live = stari
            geministt.RETRY_WAIT = stara_pauza
        return len(pokusaji)

    def test_prolazna_greska_se_ponavlja_jednom(self):
        self.assertEqual(self._broji_pokusaje(True), geministt.MAX_RETRIES)

    def test_trajna_greska_se_ne_ponavlja(self):
        self.assertEqual(self._broji_pokusaje(False), 1)


class LokalnaPravila(unittest.TestCase):
    def test_stil_izgovoreno_skida_znake_i_velika_slova(self):
        self.assertEqual(
            geministt.post_process("Zdravo, kako si?", cfg()), "zdravo kako si"
        )

    def test_stil_sredjeno_ne_dira_tekst(self):
        c = cfg(lowercase=False, strip_punctuation=False)
        self.assertEqual(
            geministt.post_process("Zdravo, kako si?", c), "Zdravo, kako si?"
        )

    def test_brojevi_ostaju_citavi(self):
        c = cfg(lowercase=False, strip_punctuation=True)
        self.assertEqual(geministt.post_process("u 10:30 je 3,5", c), "u 10:30 je 3,5")

    def test_prazan_tekst(self):
        self.assertEqual(geministt.post_process("", cfg()), "")


if __name__ == "__main__":
    unittest.main()
