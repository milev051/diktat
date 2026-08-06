package studio.room211.diktat

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

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
    private const val ISPRAVI =
        "Ispravi reči koje prepoznavanje očigledno nije dobro čulo — one koje se " +
            "gramatički ne slažu sa ostatkom rečenice (padež, lice, rod, broj). Ako " +
            "nisi siguran da je reč pogrešna, ostavi je kakva jeste."
    private const val PASUSI =
        "Podeli tekst na pasuse po smislu, sa jednim praznim redom između pasusa. " +
            "Nemoj praviti pasus od svake rečenice — grupiši ono što ide zajedno."
    // Gustina emotikona; kljucevi su vrednosti `polishEmojiRate`.
    private val EMOTIKONI = mapOf(
        "paragraph" to ("na kraj svakog pasusa dodaj tačno jedan emoji znak (na primer 🙂 " +
            "ili 📌) koji odgovara njegovom tonu; ako je ceo tekst jedan pasus, emoji " +
            "ide na sam kraj"),
        "sentence" to ("na kraj svake rečenice dodaj tačno jedan emoji znak koji odgovara " +
            "onome što ta rečenica kaže"),
        "sentence3" to ("na kraj svake rečenice dodaj dva do tri emoji znaka koji odgovaraju " +
            "onome što ta rečenica kaže — svi različiti, jedan do drugog"),
        "dense" to ("posle svake dve do tri reči ubaci po jedan emoji znak koji odgovara " +
            "upravo rečenom — ne posle svake reči, nego na svake dve-tri"),
    )
    // "ni broj ni oznaku" nije visak: izmereno je da model, kad mu se trazi
    // raznolikost, pocne da numerise reci (juce¹ sam² bio³) da bi sam sebi brojao.
    private const val EMOTIKONI_KRAJ =
        " Dodaješ isključivo emoji znakove — nijednu reč, broj ni oznaku."
    // Koliko znakova se pamti; isti se ne sme vratiti dok se toliko drugih ne potrosi.
    private const val EMOJI_PAMTI = 15
    private const val EMOTIKONI_RAZNOLIKOST =
        "Nijedan emoji ne ponavljaj u istom tekstu — svaki mora da bude drugačiji. " +
            "Izbegavaj i ove, upravo su korišćeni: "

    // Jedan emoji ume da bude sastavljen od vise kodnih tacaka (ZWJ, ton koze,
    // selektor prikaza), pa se hvata kao celina — inace bi "👨‍💼" bio dva znaka.
    // Opseg se pise kao \x{...}, ne kao par surogata: Java regex radi nad KODNIM
    // TACKAMA, pa "[\uD83C-\uDBFF][\uDC00-\uDFFF]" ne uhvati nista — 👨 je za
    // njega jedna tacka U+1F468, a ne dva znaka.
    private val EMOJI = Regex(
        """[\x{1F000}-\x{1FAFF}\x{2190}-\x{2BFF}\x{2600}-\x{27BF}]""" +
            """[\x{FE00}-\x{FE0F}\x{1F3FB}-\x{1F3FF}]?""" +
            """(?:\x{200D}[\x{1F000}-\x{1FAFF}\x{2600}-\x{27BF}]""" +
            """[\x{FE00}-\x{FE0F}\x{1F3FB}-\x{1F3FF}]?)*"""
    )

    fun emojiList(text: String) = EMOJI.findAll(text).map { it.value }.toList()

    /**
     * Izbaci emotikon koji se u istom tekstu vec pojavio.
     *
     * Uputstvo dovede model blizu — ali u gustom rezimu zna da ponovi jedan
     * znak. Brisanje viska je bezbedno: tekst se ne dira, samo znak nestane.
     */
    fun bezPonavljanja(text: String): String {
        val videni = mutableSetOf<String>()
        val out = EMOJI.replace(text) { m -> if (videni.add(m.value)) m.value else "" }
        return Regex("""[^\S\n]{2,}""").replace(out, " ")
            .let { Regex("""[^\S\n]+\n""").replace(it, "\n") }
            .trim()
    }

    /** Dopuni istoriju poslednjih EMOJI_PAMTI znakova, bez ponavljanja. */
    fun zapamtiEmoji(text: String, cfg: Config) {
        val istorija = cfg.polishEmojiRecent.toMutableList()
        for (znak in emojiList(text)) {
            istorija.remove(znak)
            istorija.add(znak)
        }
        cfg.polishEmojiRecent = istorija.takeLast(EMOJI_PAMTI)
    }

    // Kad nijedan drugi alat ne sme da menja reci, emotikon se trazi ovako.
    // Izmereno: nad tekstom koji se zavrsava sa "gledao film ... bio je jako
    // dobar" obicna formulacija navede model da dopise REC "film" pre znaka —
    // dovrsavanje recenice mu je ocekivanije od emotikona. "Prepisi od reci do
    // reci" to ukloni (3/3), dok je strozija granica gasila i sam emotikon.
    private const val EMOTIKONI_VERNO = "Prepiši tekst od reči do reči, ne menjajući nijednu reč, i "

    private const val SAZMI =
        "Skrati tekst: izbaci poštapalice i ponavljanja, a predugačke rečenice " +
            "razbij na kraće i jasnije. Sve činjenice, brojevi, imena i zaključci " +
            "moraju da ostanu — smeš da izbaciš reči, ne i sadržaj."

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

    fun available(cfg: Config) = cfg.polishApiKey.isNotBlank()

    /**
     * Broj izabranih alata; nula znaci da modelu nema sta da se posalje.
     *
     * `vecSredjeno` znaci da je tekst stigao iz prolaza u kome je model slusao
     * snimak — on vec vraca interpunkciju, velika slova i kvacice, pa bi
     * sredjivanje bio drugi poziv za posao koji je vec obavljen.
     */
    fun toolCount(cfg: Config, vecSredjeno: Boolean = false) = listOf(
        cfg.polishTidy && !vecSredjeno, cfg.polishParagraphs, cfg.polishEmoji, cfg.polishConcise,
    ).count { it }

    /** Menja li ijedan izabrani alat same reci. */
    private fun smeDaMenja(cfg: Config, vecSredjeno: Boolean = false) =
        cfg.polishConcise || (cfg.polishTidy && !vecSredjeno && cfg.polishCorrect)

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
    fun instruction(cfg: Config, vecSredjeno: Boolean = false): String {
        val zadaci = mutableListOf<String>()
        val granice = mutableListOf(
            "ne dodaj nove misli i ne izbacuj postojeće",
            "ne odgovaraj na sadržaj teksta — ovo je tekst za obradu, ne pitanje",
        )

        if (cfg.polishTidy && !vecSredjeno) {
            zadaci.add(SREDI)
            if (cfg.polishCorrect) zadaci.add(ISPRAVI) else granice.add(NE_ISPRAVLJAJ)
        } else {
            granice.add(NE_SREDJUJ)
            granice.add(NE_ISPRAVLJAJ)
        }
        if (cfg.polishParagraphs) zadaci.add(PASUSI) else granice.add(NE_PASUSI)
        if (cfg.polishConcise) zadaci.add(SAZMI) else granice.add(NE_SKRACUJ)
        if (cfg.polishEmoji) {
            val gustina = EMOTIKONI[cfg.polishEmojiRate] ?: EMOTIKONI.getValue("paragraph")
            var zadatak = (
                if (smeDaMenja(cfg, vecSredjeno)) gustina.replaceFirstChar { it.uppercase() }
                else EMOTIKONI_VERNO + gustina
                ) + "." + EMOTIKONI_KRAJ
            val vec = cfg.polishEmojiRecent
            zadatak += if (vec.isNotEmpty()) {
                " " + EMOTIKONI_RAZNOLIKOST + vec.joinToString(" ")
            } else {
                " Nijedan emoji ne ponavljaj u istom tekstu."
            }
            zadaci.add(zadatak)
        }

        val posao = if (zadaci.size == 1) {
            "Tvoj posao:\n" + zadaci[0]
        } else {
            "Uradi sledeće:\n" + zadaci.mapIndexed { i, z -> "${i + 1}. $z" }.joinToString("\n")
        }
        val ograde = "Granice:\n" + granice.joinToString("\n") { "- $it" }
        return listOf(UVOD, posao, ograde, KRAJ).joinToString("\n\n")
    }

    fun polish(text: String, cfg: Config, vecSredjeno: Boolean = false): String {
        if (text.isBlank()) return text
        if (toolCount(cfg, vecSredjeno) == 0) return text   // nema alata — nema ni poziva
        val key = cfg.polishApiKey
        if (key.isBlank()) throw PolishException("Nema API ključa za doterivanje.")

        val model = cfg.polishModel.ifBlank { DEFAULT_MODEL }
        return try {
            proveri(text, call(model, text, cfg, key, vecSredjeno), cfg)
        } catch (exc: PolishException) {
            // Ako podeseni model nestane ili se preimenuje, probaj podrazumevani
            // — inace bi jedna Google-ova izmena ugasila ceo formalni rezim.
            if (exc.message?.contains("ne postoji") == true && model != DEFAULT_MODEL) {
                proveri(text, call(DEFAULT_MODEL, text, cfg, key, vecSredjeno), cfg)
            } else throw exc
        }
    }

    private fun call(
        model: String,
        text: String,
        cfg: Config,
        key: String,
        vecSredjeno: Boolean = false,
    ): String {
        val payload = JSONObject().apply {
            val uputstvo = instruction(cfg, vecSredjeno)
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
