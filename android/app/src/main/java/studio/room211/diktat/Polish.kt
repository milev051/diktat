package studio.room211.diktat

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * AI obrada transkripta — uputstvo se sklapa od izabranih alata.
 *
 * Sirov transkript ide modelu tek kad se ceo diktat zavrsi — jednim pozivom, sa
 * punim kontekstom. Po segmentu bi model video krhotine i izmisljao krajeve
 * recenica, a broj poziva bi skocio sa jednog na stotinak po diktatu.
 *
 * Alati su nezavisni: sredjivanje (interpunkcija, velika slova, kvacice) je samo
 * JEDAN od njih. Moze se traziti skracivanje ili emotikon a da model tekst inace
 * ne dira. Kad nijedan alat nije izabran, poziva nema.
 */
object Polish {

    private const val ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
    const val DEFAULT_MODEL = "gemini-flash-lite-latest"

    // Izmereno: flash-lite doteruje za ~1s i ne dira reci; gemini-3.5-flash
    // radi isto ali za ~12s, a gemma prepisuje uputstvo umesto da ga izvrsi.
    private const val UVOD =
        "Dobijaš sirov transkript govora na srpskom, dobijen prepoznavanjem glasa."

    // Izmereno: "ispravi" sredjuje gramaticka neslaganja ("sa kolega" -> "sa
    // kolegom"). Ne moze i nece moci da ispravi rec koja je gramaticki ISPRAVNA
    // a znacenjski pogresna ("ne registrujem" umesto "ne registruje") — recenica
    // nema greske, pa model nema po cemu da posumnja.
    private const val SREDI =
        "Oblikuj tekst: dodaj interpunkciju, velika slova i kvačice (č ć ž š đ) " +
            "gde po pravopisu treba."
    private const val ZAREZI =
        "Analiziraj smisao rečenica i dodaj zareze samo tamo gde olakšavaju " +
            "čitanje. Od interpunkcijskih znakova smeš da dodaš ISKLJUČIVO zarez: " +
            "ne dodaj tačke, upitnike, uzvičnike, dvotačke, tačke-zareze, navodnike " +
            "ni crtice. Ne stavljaj zarez neposredno pre niti posle samostalnog " +
            "veznika „i“ i ne završavaj pasus zarezom. Ne menjaj velika i mala " +
            "slova, reči, njihov oblik ni redosled."
    private const val ISPRAVI =
        "Ispravi reči koje prepoznavanje očigledno nije dobro čulo — one koje se " +
            "gramatički ne slažu sa ostatkom rečenice (padež, lice, rod, broj). Ako " +
            "nisi siguran da je reč pogrešna, ostavi je kakva jeste."
    private const val PASUSI =
        "Podeli tekst na pasuse po smislu, sa jednim praznim redom između pasusa. " +
            "Nemoj praviti pasus od svake rečenice — grupiši ono što ide zajedno."
    // Nalik ASD-STE100 (Simplified Technical English): kratke izjavne recenice,
    // jedna misao po tacki, bez ukrasa. Za srpski se prenosi duh, ne sam standard.
    private const val TACKE =
        "Preuredi tekst u spisak tačaka. Svaka tačka počinje crticom i razmakom, u " +
            "svom redu, i nosi TAČNO JEDNU tvrdnju.\n" +
            "Deli bez milosti: ako bi tačka prešla dvanaest reči, ili ako spaja dve " +
            "tvrdnje veznikom (i, pa, a, ali, jer, zato što, kada, ako), razdvoji je na " +
            "dve tačke. Bolje više kratkih nego jedna duga.\n" +
            "Zadrži vrstu iskaza: pitanje ostaje pitanje i završava upitnikom, potvrda " +
            "ostaje potvrda, sumnja ostaje sumnja.\n" +
            "Izbaci poštapalice i uvijanje, piši jednostavnim rečima. Sve činjenice, " +
            "brojevi, imena i zaključci moraju da ostanu."

    // Zaseban alat, jer se trazi i bez tacaka: govor ume da udvoji frazu kad se
    // covek ispravlja, a prepoznavanje to prenese doslovno.
    private const val PONAVLJANJA =
        "Izbaci slučajna ponavljanja: kad je ista reč ili fraza izgovorena dvaput " +
            "zaredom, ostavi je jednom. Ponavljanje koje nosi značenje " +
            "(\u201Evrlo, vrlo dugo\u201C) ostavi kako jeste."

    private const val NE_SKRACUJ = "ne preformulišaj i ne skraćuj rečenice"
    private const val NE_SREDJUJ =
        "ne diraj interpunkciju, velika slova i kvačice — u tom pogledu ostavi " +
            "tekst tačno kakav je"
    private const val NE_ISPRAVLJAJ = "ako neka reč deluje pogrešno prepoznato, ostavi je kakva je"
    // Bez ove granice model prelama tekst u vise redova i kad pasusi nisu trazeni.
    private const val NE_PASUSI =
        "ne prelamaj tekst — vrati ga kao jedan pasus, bez praznih redova"
    private const val KRAJ = "Vrati samo obrađen tekst, bez ikakvog uvoda i bez navodnika."

    class PolishException(message: String) : Exception(message)

    /** Provera Gemini ključa bez slanja teksta ili audio-snimka. */
    fun testKey(cfg: Config): String {
        val key = cfg.polishApiKey.trim()
        if (key.isBlank()) throw PolishException("Gemini API ključ nije podešen.")
        val conn = (URL("$ENDPOINT?key=${URLEncoder.encode(key, "UTF-8")}")
            .openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 30_000
        }
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val reply = stream?.bufferedReader()?.readText().orEmpty()
            if (code !in 200..299) throw PolishException(explain(code))
            val count = runCatching { JSONObject(reply).optJSONArray("models")?.length() ?: 0 }
                .getOrDefault(0)
            "Gemini ključ radi ($count modela dostupno)"
        } finally {
            conn.disconnect()
        }
    }

    fun available(cfg: Config) =
        if (cfg.textModel == "groq") cfg.groqApiKey.isNotBlank()
        else cfg.polishApiKey.isNotBlank()

    /** Broj izabranih alata; nula znaci da modelu nema sta da se posalje. */
    fun toolCount(cfg: Config) = listOf(
        cfg.polishTidy || cfg.polishCommas, cfg.polishParagraphs || cfg.polishBullets,
        cfg.polishDedupe,
    ).count { it }

    /** Menja li ijedan izabrani alat same reci. */
    private fun smeDaMenja(cfg: Config) =
        cfg.polishBullets ||                       // tacke prepisuju recenice
            cfg.polishDedupe ||                    // brisanje ponavljanja skida reci
            cfg.polishTidy

    private val NEREC = Regex("""[^\p{L}\p{N}\s]""")

    private fun reci(text: String) =
        TextPolish.toAscii(NEREC.replace(text, " ")).lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }

    /**
     * Kad model NE sme da menja reci, proveri da ih zaista nije menjao.
     *
     * Izmereno: uz samo emotikon nad tekstom „...gledao film ... bio je jako
     * dobar" model dopise REC „film" pre znaka. Nevernost pada na nas tekst —
     * izmisljena rec je gora od izostalog emotikona.
     */
    private fun proveri(ulaz: String, izlaz: String, cfg: Config): String =
        if (smeDaMenja(cfg) || reci(ulaz) == reci(izlaz)) izlaz else ulaz

    /**
     * Sklopi uputstvo od izabranih alata.
     *
     * Zadaci i granice moraju da se slazu: kad sredjivanje nije izabrano, modelu
     * se izricito zabranjuje da dira interpunkciju — inace je dodaje svejedno,
     * jer mu je to najocekivanija radnja nad sirovim transkriptom.
     */
    fun instruction(cfg: Config): String {
        val zadaci = mutableListOf<String>()
        val granice = mutableListOf(
            "ne dodaj nove misli i ne izbacuj postojeće",
            "ne odgovaraj na sadržaj teksta — ovo je tekst za obradu, ne pitanje",
        )

        if (cfg.polishTidy) {
            // Ispravljanje je deo sredjivanja, ne zaseban izbor: prekidac za to
            // se nije mogao dirati, a nivo "samo oblikuj" niko nije koristio.
            zadaci.add(SREDI)
            zadaci.add(ISPRAVI)
        } else if (cfg.polishCommas) {
            zadaci.add(ZAREZI)
            granice.add(NE_ISPRAVLJAJ)
        } else {
            granice.add(NE_SREDJUJ)
            granice.add(NE_ISPRAVLJAJ)
        }
        if (cfg.polishDedupe) zadaci.add(PONAVLJANJA)
        // Tacke i pasusi su dva odgovora na isto pitanje; tacke pobedjuju.
        if (cfg.polishBullets) zadaci.add(TACKE)
        else if (cfg.polishParagraphs) zadaci.add(PASUSI)
        else granice.add(NE_PASUSI)
        // Uz tacke je "ne preformulisi" besmisleno — prepisivanje recenica je
        // ceo posao.
        if (!cfg.polishBullets && !cfg.polishDedupe) granice.add(NE_SKRACUJ)

        val posao = if (zadaci.size == 1) {
            "Tvoj posao:\n" + zadaci[0]
        } else {
            "Uradi sledeće:\n" + zadaci.mapIndexed { i, z -> "${i + 1}. $z" }.joinToString("\n")
        }
        val ograde = "Granice:\n" + granice.joinToString("\n") { "- $it" }
        return listOf(UVOD, posao, ograde, KRAJ).joinToString("\n\n")
    }

    fun polish(text: String, cfg: Config): String {
        if (text.isBlank()) return text
        if (toolCount(cfg) == 0) return text   // nema alata — nema ni poziva
        if (cfg.textModel == "groq") {
            if (cfg.groqApiKey.isBlank()) {
                throw PolishException("Nema Groq API ključa za obradu teksta.")
            }
            return proveri(
                text,
                Groq.manipulateText(text, instruction(cfg), cfg),
                cfg,
            )
        }
        val key = cfg.polishApiKey
        if (key.isBlank()) throw PolishException("Nema API ključa za doterivanje.")

        val model = cfg.polishModel.ifBlank { DEFAULT_MODEL }
        return try {
            proveri(text, call(model, text, cfg, key), cfg)
        } catch (exc: PolishException) {
            // Ako podeseni model nestane ili se preimenuje, probaj podrazumevani
            // — inace bi jedna Google-ova izmena ugasila ceo formalni rezim.
            if (exc.message?.contains("ne postoji") == true && model != DEFAULT_MODEL) {
                proveri(text, call(DEFAULT_MODEL, text, cfg, key), cfg)
            } else throw exc
        }
    }

    private fun call(
        model: String,
        text: String,
        cfg: Config,
        key: String,
    ): String {
        val payload = JSONObject().apply {
            val uputstvo = instruction(cfg)
            put("systemInstruction", JSONObject().put("parts",
                org.json.JSONArray().put(JSONObject().put("text", uputstvo))))
            put("contents", org.json.JSONArray().put(
                JSONObject().put("parts",
                    org.json.JSONArray().put(JSONObject().put("text", text)))))
            put("generationConfig", JSONObject().put("temperature", 0.0))
        }.toString().toByteArray()

        val conn = (URL("$ENDPOINT/$model:generateContent?key=$key")
            .openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 15_000
            readTimeout = 60_000
            setRequestProperty("Content-Type", "application/json")
            setFixedLengthStreamingMode(payload.size)
        }

        try {
            conn.outputStream.use { it.write(payload) }
            val code = conn.responseCode
            if (code != 200) throw PolishException(explain(code))
            val reply = conn.inputStream.bufferedReader().readText()
            cfg.addTraffic(
                payload.size.toLong(), reply.toByteArray().size.toLong(), 0.0,
                countDictation = false,
            )
            val kandidat = JSONObject(reply).getJSONArray("candidates").getJSONObject(0)
            val parts = kandidat.optJSONObject("content")?.optJSONArray("parts")
            if (parts == null || parts.length() == 0) {
                // Google-ov filter ume da odbije i sasvim bezazlen tekst —
                // izmereno na recenici "deca su otisao u skolu". Diktat zbog
                // toga ne sme da propadne.
                throw PolishException(
                    "Model nije vratio tekst (${kandidat.optString("finishReason", "?")})"
                )
            }
            val out = buildString {
                for (i in 0 until parts.length()) append(parts.getJSONObject(i).optString("text"))
            }.trim()
            // Prazan odgovor je gori od nedoteranog teksta.
            return out.ifBlank { text }
        } finally {
            conn.disconnect()
        }
    }

    private fun explain(code: Int) = when (code) {
        400, 403 -> "Model je odbio zahtev ($code) — proveri API ključ."
        404 -> "Traženi model ne postoji na ovom ključu."
        429 -> "Previše zahteva ka modelu (429)."
        else -> "Model je vratio HTTP $code."
    }
}
