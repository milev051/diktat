"""OpenAI GPT Transcribe: ceo snimak ide posle Stop-a, jednim zahtevom.
"""

from . import openai


class OpenAiTok:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _recognize_openai(self, pcm: bytes) -> str:
        return openai.post_process(openai.recognize(pcm, self.cfg), self.cfg)

    def _transcribe_whole(self, recorder, oznaka="ceo"):
        """Snimi CEO diktat u privremeni fajl i posalji ga tek posle Stop-a.

        Model tako vidi celinu umesto krhotina odsecenih na pauzama, isto kao
        sto AI obrada zove model jednom, na kraju. (Gemini ima svoj tok koji
        salje zvuk dok snimas, tok_gemini.py.)

        Privremeni disk sprecava da dugacak neprekidan diktat sve vreme raste u
        memoriji; sat vremena je preko 100 MB.
        """
        import tempfile

        session = self._dump.session() if self._dump else None
        if session is not None:
            self._debug_sessions[recorder.session] = session

        with tempfile.NamedTemporaryFile(prefix="diktat-ceo-", suffix=".pcm") as fh:
            for chunk in self._tracked(recorder):
                fh.write(chunk)
            fh.flush()
            fh.seek(0)
            pcm = fh.read()

        if recorder.cancelled:
            return ""
        self._settle_phase()
        text = self._recognize_or_keep(pcm)
        if session is not None:
            session.segment(session.next_index(), pcm, text, kind=oznaka)
            session.finish(pcm, text)
        return text

    def _openai_long_recording(self) -> bool:
        return (
            self.cfg.get("transcription_provider", "google") == "openai"
            and bool(self.cfg.get("openai_long_recording", True))
        )
