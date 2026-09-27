package studio.room211.diktat

/**
 * Doterivanje prepoznatog teksta — isto sto radi i macOS verzija.
 */
object TextPolish {

    /**
     * Tacka, zarez i dvotacka se brisu samo kad NISU izmedju cifara: endpoint
     * ih vraca kao decimalni separator ("3,5") i kao satnicu ("10:00"), pa bi
     * ih slepo brisanje spojilo u 35 i 1000. Crtica i simboli se uklanjaju,
     * osim brojčanih separatora (1/2, 10-20).
     */
    // `%` NIJE u spiskovima ispod: endpoint ga vrati za izgovoreno „procenata"
    // (izmereno: „popust je dvadeset procenata" -> „popusti je 20%"), pa bi
    // brisanje pojelo jedini trag jedinice. Isto vazi za `$` i `€`.
    private val PUNCT = Regex(
        // Znaci su pisani kao \uXXXX namerno: krivi navodnici i crte se lako
        // izgube pri kopiranju izmedju alata, a onda pravilo tiho oslabi.
        """(?<!\d)[.,:]""" +                                 // tacka/zarez/dvotacka bez cifre ispred
            """|[.,:](?!\d)""" +                             // ili bez cifre iza
            // Apostrof (' i \u2019) NIJE ovde: on je deo reci, vidi `bezNavodnika`.
            """|[!?;\u2026\u00AB\u00BB\u201E\u201C\u201D"\u2018\u201A\u2039\u203A()\[\]{}]""" +
            """|(?<!\w)[-\u2013\u2014/]|[-\u2013\u2014/](?!\w)""" +
            """|[#&*+<=>@\\^_`|~]"""
    )

    /** Isto uklanjanje, ali običan zarez ostaje radi opcije „samo zarezi“. */
    private val PUNCT_EXCEPT_COMMA = Regex(
        """(?<!\d)[.:]""" +
            """|[.:](?!\d)""" +
            """|[!?;\u2026\u00AB\u00BB\u201E\u201C\u201D\"\u2018\u201A\u2039\u203A()\[\]{}]""" +
            """|(?<!\w)[-\u2013\u2014/]|[-\u2013\u2014/](?!\w)""" +
            """|[#&*+<=>@\\^_`|~]"""
    )

    private val COMMA_BEFORE_I = Regex("""(?iu),[ \t]+(?=i\b)""")
    private val COMMA_AFTER_I = Regex("""(?iu)\b(i)[ \t]*,[ \t]*""")
    private val COMMA_AT_END = Regex(""",[ \t]*$""")

    private val DIACRITICS = mapOf(
        'č' to "c", 'ć' to "c", 'ž' to "z", 'š' to "s", 'đ' to "dj",
        'Č' to "C", 'Ć' to "C", 'Ž' to "Z", 'Š' to "S", 'Đ' to "Dj",
    )

    /**
     * Tacka je separator hiljada samo ako je prate TACNO tri cifre i tu se broj
     * zavrsava: "5.000" -> "5000", ali "verzija 2.0" i "android 4.4" ostaju celi.
     * Zarez se ne dira — on je decimalni.
     */
    private val THOUSANDS = Regex("""(?<=\d)\.(?=\d{3}(?!\d))""")

    fun joinThousands(text: String): String {
        var out = text
        var previous: String
        do {                       // "1.500.000" ima vise tacaka
            previous = out
            out = THOUSANDS.replace(out, "")
        } while (out != previous)
        return out
    }

    // Znak koji stoji IZMEDJU DVA SLOVA, bez razmaka, drzi dve reci razdvojene:
    // brisanje bi ih slepilo („gotovo je.sada" -> „gotovo jesada"). Zato prvo
    // postaje razmak, pa se tek onda ostatak brise. Apostrof i navodnici
    // namerno NISU ovde: „ć'š" mora da ostane jedna rec, ne „ć š".
    // Isto pravilo kao `_LEPAK` u dictate/webstt.py.
    private val GLUE = Regex("""(?<=\p{L})[.:;!?\u2026]+(?=\p{L})""")
    // Zarez ide zasebno: uz „zadrzi zareze" slepljeno „rec,rec" treba da postane
    // „rec, rec", a ne „rec rec".
    private val GLUE_COMMA = Regex("""(?<=\p{L}),+(?=\p{L})""")

    // Apostrof je deo reci („je l'", „ć'š", „'ajde") i ostaje. Brisu se samo
    // jednostruki navodnici u paru oko reci („'ovako'", „‘ovako’") i apostrof
    // koji stoji sam. Slovo je napisano kao \p{L}\p{N}, jer `\w` na JVM-u ne
    // vidi „ć". Isto kao `_bez_navodnika` u dictate/webstt.py.
    private const val REC = """[\p{L}\p{N}_]"""
    private val NAVODNICI = Regex(
        """(?<!$REC)['\u2018\u201A](?=$REC)([^'\u2018\u2019\u201A]*?$REC)['\u2019](?!$REC)"""
    )
    private val SAM_APOSTROF = Regex("""(?<!$REC)['\u2019](?!$REC)""")

    private fun bezNavodnika(text: String): String =
        SAM_APOSTROF.replace(NAVODNICI.replace(text, "$1"), "")

    fun stripPunctuation(text: String, keepCommas: Boolean = false): String {
        var razdvojen = GLUE.replace(bezNavodnika(text), " ")
        razdvojen = GLUE_COMMA.replace(razdvojen, if (keepCommas) ", " else " ")
        var cleaned = (if (keepCommas) PUNCT_EXCEPT_COMMA else PUNCT).replace(razdvojen, "")
        if (keepCommas) {
            // Model ponekad napiše „..., i ...“ ili „i, ...“. Za željeni
            // razgovorni stil veznik „i“ ostaje bez zareza sa obe strane.
            cleaned = COMMA_BEFORE_I.replace(cleaned, " ")
            cleaned = COMMA_AFTER_I.replace(cleaned) { match ->
                match.groupValues[1] + " "
            }
            cleaned = COMMA_AT_END.replace(cleaned, "")
        }
        return cleaned
            .split(Regex("\\s+"))
            .filter { it.isNotEmpty() }
            .joinToString(" ")
    }

    // Znakovi koji zavrsavaju misao, pa razmak ili kraj teksta. Tacka i
    // dvotacka IZMEDJU cifara („10:30", „2.0") se ovde ne vide. Isto kao
    // `samo_zarezi` u dictate/webstt.py; menja se na oba mesta.
    private val KRAJ_MISLI = Regex("""(\S*?)([.!?;:\u2026]+)(?=\s|$)""")
    // Isto, ali slepljeno uz sledecu rec: „idem.Sutra", „idem?sutra".
    private val SLEPLJEN_KRAJ = Regex("""(?<=\p{L})([.!?;:\u2026]+)(?=\p{L})""")
    // Navodnici, zagrade, crte i simboli nestaju isto kao uz „bez interpunkcije".
    private val OSTALO = Regex(
        """[\u00AB\u00BB\u201E\u201C\u201D"\u2018\u201A\u2039\u203A()\[\]{}]""" +
            """|(?<!\w)[-\u2013\u2014/]|[-\u2013\u2014/](?!\w)""" +
            """|[#&*+<=>@\\^_`|~]"""
    )

    /**
     * Tacke postaju zarezi, a ostaju samo zarezi i upitnici.
     *
     * Za pisanje malim slovima: tacka usred teksta tu izgleda cudno, a granica
     * misli ipak treba da se vidi. Na samom kraju ne ostaje ni tacka ni zarez,
     * samo upitnik.
     */
    fun samoZarezi(text: String): String {
        if (text.isEmpty()) return text
        val cist = bezNavodnika(text)
        var out = SLEPLJEN_KRAJ.replace(cist) { m ->
            val znakovi = m.groupValues[1]
            val sledece = cist[m.range.last + 1]
            when {
                '?' in znakovi -> "? "
                // Tacka ispred malog slova je domen ili ime fajla („google.com").
                znakovi.all { it == '.' } && !sledece.isUpperCase() -> znakovi
                else -> ", "
            }
        }
        out = GLUE_COMMA.replace(out, ", ")
        out = OSTALO.replace(out, "").split(Regex("\\s+")).filter { it.isNotEmpty() }
            .joinToString(" ")
        val izvor = out
        out = KRAJ_MISLI.replace(izvor) { m ->
            val (rec, znakovi) = m.destructured
            if ('?' in znakovi) return@replace "$rec?"
            // „2026. godine", „5. mesto", „npr." nisu kraj recenice. Broj ipak
            // zavrsava recenicu kad iza njega krece nova, velikim slovom.
            if (znakovi.all { it == '.' } && rec.isNotEmpty() && !endsSentence(rec, ".")) {
                val dalje = izvor.substring(m.range.last + 1).trimStart()
                if (!(rec.last().isDigit() && dalje.firstOrNull()?.isUpperCase() == true)) {
                    return@replace m.value
                }
            }
            "$rec,"
        }
        return out
            .replace(Regex("""\s+(?=[,?])"""), "")
            .replace(Regex(""",(?:\s*,)+"""), ",")
            .replace(Regex(""",\s*\?"""), "?")
            .replace(Regex("""\?\s*,"""), "?")
            .replace(Regex("""\?(?=\p{L})"""), "? ")
            .replace(Regex("""^[,\s]+"""), "")
            .replace(Regex("""[.,\s]+$"""), "")
    }

    // Glasovne komande: izgovoreno „novi red" i „novi pasus" postaje prelom.
    // Isto kao `glasovne_komande` u dictate/webstt.py; menja se na oba mesta.
    private val KOMANDA = Regex(
        """\s*,?\s*(?<![\p{L}\p{N}_])(?:novi|nov)\s+(red|pasus)(?![\p{L}\p{N}_])[.,;:!]?[ \t]*""",
        RegexOption.IGNORE_CASE,
    )

    /**
     * „novi red" -> nov red, „novi pasus" -> prazan red.
     *
     * Radi se tek pri upisu i u istoriji, ne u pravilima: pravila i AI obrada
     * rade red po red i skupljaju razmake, pa bi prelom izgubili.
     */
    fun glasovneKomande(text: String): String =
        KOMANDA.replace(text) { if (it.groupValues[1].lowercase() == "pasus") "\n\n" else "\n" }

    /** č ć ž š đ -> c c z s dj. Opciono; podrazumevano iskljuceno. */
    // Reci koje se zavrsavaju tackom a NE zavrsavaju recenicu. Isti spisak kao
    // u dictate/webstt.py; menja se na oba mesta.
    private val SKRACENICE = setOf(
        "br", "cca", "dr", "god", "inz", "inž", "isl", "itd", "mr", "npr",
        "odn", "prof", "sl", "str", "tel", "tzv", "tj", "ul",
    )

    // Slepljena granica: ".Cetvrta" umesto ". Cetvrta". Posle tacke se trazi
    // VELIKO slovo, jer malo slovo tu je po pravilu domen ili ime fajla
    // ("config.json", "google.com") koje ne sme da se raskine. Upitnik i
    // uzvicnik u njima ne postoje, pa posle njih razmak ide bez tog uslova.
    private val GLUED = Regex("""([.!?])(?=[\p{L}])""")

    // Granica recenice sa razmakom: rec, znak, razmak, pa slovo koje se podize.
    private val BOUNDARY = Regex("""([^\s.!?]*)([.!?])([ \t]+)([\p{L}])""")

    /** Da li `znak` posle reci `rec` zaista zavrsava recenicu. */
    private fun endsSentence(rec: String, znak: String): Boolean {
        if (znak != ".") return true          // upitnik i uzvicnik uvek zavrsavaju
        if (rec.isEmpty()) return true
        if (rec.last().isDigit()) return false        // godina, redni broj, verzija
        if (rec.length == 1) return false             // inicijal
        return rec.lowercase() !in SKRACENICE
    }

    /**
     * Razmak i veliko slovo posle tacke, upitnika i uzvicnika.
     *
     * Radi samo uz pisani stil: uz „izgovoreno" se interpunkcija ionako brise,
     * pa granice recenice nema. Prvo slovo komada se NE dira — diktat se secka
     * na pauzama, pa sledeci komad ume da bude nastavak recenice.
     */
    fun capitalizeSentences(text: String): String {
        if (text.isEmpty()) return text
        var out = GLUED.replace(text) { m ->
            val znak = m.groupValues[1]
            val slovo = text[m.range.last + 1]
            if (znak == "." && !slovo.isUpperCase()) znak else "$znak "
        }
        out = BOUNDARY.replace(out) { m ->
            val (rec, znak, razmak, slovo) = m.destructured
            if (!endsSentence(rec, znak)) m.value
            else rec + znak + razmak + slovo.uppercase()
        }
        return out
    }

    fun toAscii(text: String): String = buildString {
        for (ch in text) append(DIACRITICS[ch] ?: ch)
    }

    /**
     * Ista pravila, ali PRELOM REDOVA prezivljava.
     *
     * `stripPunctuation` skuplja sve razmake u jedan, pa bi nad celim tekstom
     * spojio i pasuse i tacke spiska u jedan red — a crtica, koja se tada nadje
     * izmedju dva razmaka, i sama nestane. Zato red po red.
     */
    fun applyBlocks(raw: String, cfg: Config): String =
        raw.split("\n").joinToString("\n") { line ->
            val marker = if (line.startsWith("- ")) "- " else ""
            marker + apply(line.removePrefix(marker), cfg, trailing = false)
        }

    /**
     * Zavrsna obrada nad tekstom koji je model vec sredio.
     *
     * Tekst mu ide nedirnut, pa se lokalne opcije primenjuju ovde, posle modela.
     * Tako korisnik moze nezavisno da zadrzi ili ukloni interpunkciju i velika
     * slova, cak i kada je ukljuceno AI sredjivanje.
     */
    fun afterModel(text: String, cfg: Config): String {
        if (text.isBlank()) return text
        return applyBlocks(text, cfg)
    }

    fun apply(raw: String, cfg: Config, trailing: Boolean = true): String {
        var text = raw.trim()
        if (text.isEmpty()) return text
        // „Kako sam izgovorio" znaci mala slova i bez interpunkcije; „sirovo"
        // ostavlja ono sto Google vrati; „sredjeno" je posao modela, pa se ovde
        // ne dira.
        if (cfg.joinThousands) text = joinThousands(text)
        // „Ukloni interpunkciju" pobedjuje „samo zareze".
        if (cfg.stripPunctuation) {
            text = stripPunctuation(text, keepCommas = cfg.polishCommas)
        } else if (cfg.samoZarezi) {
            text = samoZarezi(text)
        }
        if (cfg.lowercase) {
            text = text.lowercase()
        } else {
            // Pisani stil znaci i veliko slovo na pocetku recenice: model ga
            // ume propustiti, a granica ume da ostane i bez razmaka.
            text = capitalizeSentences(text)
        }
        text = Abbreviations.apply(
            text,
            if (cfg.abbreviations) Abbreviations.parse(cfg.abbreviationRules) else emptyList(),
        )
        if (cfg.asciiDiacritics) text = toAscii(text)
        if (trailing && cfg.trailingSpace) text = "$text "
        return text
    }
}
