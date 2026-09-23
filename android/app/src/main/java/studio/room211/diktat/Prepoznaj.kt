package studio.room211.diktat

/**
 * Ceo snimak kroz izabran servis, sa istim pravilima kao ostatak aplikacije.
 *
 * Koriste ga oba puta preko tastature: `SttService` (sistemski servis za
 * prepoznavanje) i `GlasovnaTastatura` (glasovna tastatura, kao Google Voice
 * Typing). Jedno mesto, da se dva puta ne raziđu.
 */
object Prepoznaj {
    fun tekst(pcm: ByteArray, cfg: Config): String = when {
        GeminiStt.enabled(cfg) -> GeminiStt.postProcess(GeminiStt.recognize(pcm, cfg), cfg)
        cfg.transcriptionProvider == "openai" ->
            OpenAiTranscription.postProcess(OpenAiTranscription.recognize(pcm, cfg), cfg)
        else -> TextPolish.apply(WebStt.recognize(pcm, cfg), cfg)
    }

    /** Ista granica kao kod bočnog tastera (`Granica.sekundi`). */
    fun granica(cfg: Config): Int = Granica.sekundi(
        provider = cfg.transcriptionProvider,
        dugoSnimanje = cfg.longRecording,
        geminiLive = cfg.geminiLiveMaxSeconds,
        openAi = cfg.openAiMaxSeconds,
        neprekidno = cfg.continuousMaxSeconds,
        kratko = cfg.maxSeconds,
    )
}
