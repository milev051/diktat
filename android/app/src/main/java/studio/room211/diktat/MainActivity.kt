package studio.room211.diktat

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.color.DynamicColors
import studio.room211.diktat.Ui.body
import studio.room211.diktat.Ui.button
import studio.room211.diktat.Ui.card
import studio.room211.diktat.Ui.dp
import studio.room211.diktat.Ui.field
import studio.room211.diktat.Ui.switch

class MainActivity : AppCompatActivity() {

    private lateinit var cfg: Config
    private lateinit var statusLine: TextView
    private lateinit var trafficLine: TextView
    private lateinit var pendingLine: TextView
    private lateinit var polishLine: TextView
    private lateinit var previewOut: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        // Boje se preuzimaju sa pozadine telefona (Material You).
        DynamicColors.applyToActivityIfAvailable(this)
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        cfg = Config(this)
        askForPermissions()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val side = dp(16)
            setPadding(side, dp(8), side, dp(32))
        }

        root.addView(TextView(this).apply {
            text = "Diktat"
            setTextAppearance(
                com.google.android.material.R.style.TextAppearance_Material3_HeadlineMedium
            )
            setPadding(dp(4), dp(16), 0, 0)
        })
        root.addView(TextView(this).apply {
            text = "verzija ${versionName()}"
            setTextAppearance(
                com.google.android.material.R.style.TextAppearance_Material3_BodySmall
            )
            alpha = 0.6f
            setPadding(dp(4), 0, 0, dp(16))
        })

        root.addView(dozvole())
        root.addView(rezim())
        root.addView(formalni())
        root.addView(tastatura())
        root.addView(ponasanje())
        root.addView(obrada())
        root.addView(jezik())
        root.addView(skracenice())
        root.addView(neuspeli())
        root.addView(potrosnja())
        root.addView(proba())

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(root)
        }
        setContentView(scroll)

        // Sadrzaj ide ispod statusne trake, pa se razmak dodaje rucno. Visina
        // tastature se mora dodati na dno: bez toga tastatura prekrije polje u
        // koje se kuca i ne vidi se sta pises.
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            view.setPadding(0, bars.top, 0, maxOf(bars.bottom, ime.bottom))
            insets
        }
    }

    override fun onResume() {
        super.onResume()
        statusLine.text = if (InsertService.isRunning) {
            "Pristupačnost je uključena — tekst se upisuje gde je kursor."
        } else {
            "Pristupačnost nije uključena — tekst će završiti u clipboard-u."
        }
        showTraffic()
        showPending()
        polishLine.text = "Poziva modelu danas: ${cfg.polishCountToday}"
    }

    // ------------------------------------------------------------ kartice

    private fun dozvole(): ViewGroup {
        val (card, box) = card(this, "Dozvole")
        statusLine = body(this, "")
        box.addView(statusLine)
        box.addView(button(this, "Postavi kao digitalnog asistenta") {
            openAny(
                "android.settings.VOICE_INPUT_SETTINGS",
                Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS, Settings.ACTION_SETTINGS,
            )
        })
        box.addView(button(this, "Prikaz preko drugih aplikacija") {
            runCatching {
                startActivity(
                    Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:$packageName"),
                    )
                )
            }
        })
        box.addView(button(this, "Unos teksta (Pristupačnost)") {
            openAny(Settings.ACTION_ACCESSIBILITY_SETTINGS)
        })
        return card
    }

    private fun rezim(): ViewGroup {
        val (card, box) = card(this, "Režim snimanja")
        box.addView(switch(this, "Neprekidno", cfg.continuous) { cfg.continuous = it })
        box.addView(
            body(
                this,
                "Bez vremenskog ograničenja. Seče na svakoj pauzi — makar celina " +
                    "bila od dve reči — i šalje delove dok snimanje teče dalje, " +
                    "pa tekst stiže usput. Ostatak ide kad ručno zaustaviš.\n\n" +
                    "Isključeno: jedan snimak do 30s, pa obrada.",
            )
        )
        return card
    }

    private fun formalni(): ViewGroup {
        val (card, box) = card(this, "AI obrada teksta")
        box.addView(switch(this, "Uključi AI obradu", cfg.polish) { cfg.polish = it })
        box.addView(
            body(
                this,
                "Ceo diktat se sačeka, pa se jednim pozivom pošalje modelu. Dok " +
                    "se čeka odgovor, pokazivač pokazuje AI.\n\n" +
                    "Alati ispod su nezavisni — možeš tražiti samo kraći tekst ili " +
                    "samo pasuse, a da model interpunkciju i kvačice ne dira. Ako " +
                    "nijedan nije izabran, poziva nema.\n\n" +
                    "Radi samo uz API ključ (Google AI Studio). Ključ ostaje " +
                    "sačuvan i posle nadogradnje aplikacije.",
            )
        )
        box.addView(switch(this, "Sredi tekst (interpunkcija, kvačice)", cfg.polishTidy) {
            cfg.polishTidy = it
        })
        box.addView(switch(this, "…i ispravi očigledne greške", cfg.polishCorrect) {
            cfg.polishCorrect = it
        })
        box.addView(
            body(
                this,
                "Ispravlja reči koje se gramatički ne slažu — „sa kolega\" → " +
                    "„sa kolegom\". Reč koja je gramatički ispravna a značenjski " +
                    "pogrešna se ne može ispraviti; tu rečenica nema greške. " +
                    "Radi samo uz sređivanje.",
            )
        )
        box.addView(switch(this, "Podeli na pasuse", cfg.polishParagraphs) {
            cfg.polishParagraphs = it
        })
        box.addView(switch(this, "Skrati i pojednostavi", cfg.polishConcise) {
            cfg.polishConcise = it
        })
        box.addView(
            body(
                this,
                "Izbacuje poštapalice i ponavljanja, duge rečenice deli na kraće. " +
                    "Činjenice, brojevi i imena ostaju.",
            )
        )
        box.addView(switch(this, "Emotikon na kraju pasusa", cfg.polishEmoji) {
            cfg.polishEmoji = it
        })
        polishLine = body(this, "")
        box.addView(polishLine)
        val (kljuc, _) = field(this, "API ključ", cfg.polishApiKey) { cfg.polishApiKey = it }
        box.addView(kljuc)
        val (model, _) = field(this, "Model (prazno = ${Polish.DEFAULT_MODEL})", cfg.polishModel) {
            cfg.polishModel = it
        }
        box.addView(model)
        return card
    }

    private fun tastatura(): ViewGroup {
        val (card, box) = card(this, "Mikrofon na tastaturi")
        box.addView(
            body(
                this,
                "Umesto bočnog tastera možeš izabrati Diktat kao Voice input; " +
                    "tada mikrofon na tastaturi radi isto, bez Pristupačnosti.",
            )
        )
        box.addView(button(this, "Otvori Voice input") {
            openAny(Settings.ACTION_VOICE_INPUT_SETTINGS, Settings.ACTION_INPUT_METHOD_SETTINGS)
        })
        return card
    }

    private fun ponasanje(): ViewGroup {
        val (card, box) = card(this, "Ponašanje")
        box.addView(switch(this, "Snimaj samo kad ima polja za unos", cfg.requireInputField) {
            cfg.requireInputField = it
        })
        box.addView(switch(this, "Ne ostavljaj tekst u clipboard-u", cfg.restoreClipboard) {
            cfg.restoreClipboard = it
        })
        box.addView(
            body(
                this,
                "Clipboard se posle upisa vrati kakav je bio. Ako upis ne prođe, " +
                    "tekst ipak ostane — bolje nego da se izgubi.",
            )
        )
        return card
    }

    private fun obrada(): ViewGroup {
        val (card, box) = card(this, "Obrada teksta")
        box.addView(switch(this, "Sve malim slovima", cfg.lowercase) { cfg.lowercase = it })
        box.addView(switch(this, "Bez interpunkcije", cfg.stripPunctuation) {
            cfg.stripPunctuation = it
        })
        box.addView(switch(this, "Spoji hiljade (5.000 → 5000)", cfg.joinThousands) {
            cfg.joinThousands = it
        })
        box.addView(switch(this, "Razmak na kraju", cfg.trailingSpace) { cfg.trailingSpace = it })
        // Prekidac je obrnut od podesavanja: ukljucen znaci pFilter=0, sto je i
        // podrazumevano. Da pise "maskiraj", jedini bi stajao iskljucen.
        box.addView(switch(this, "Ne maskiraj psovke zvezdicama", !cfg.profanityFilter) {
            cfg.profanityFilter = !it
        })
        box.addView(switch(this, "Bez kvačica (č ć ž š đ → c c z s dj)", cfg.asciiDiacritics) {
            cfg.asciiDiacritics = it
        })
        return card
    }

    private fun jezik(): ViewGroup {
        val (card, box) = card(this, "Jezik")
        val (layout, _) = field(this, "Kod jezika", cfg.language) {
            cfg.language = it.trim().ifBlank { "sr-RS" }
        }
        box.addView(layout)
        box.addView(body(this, "sr-RS, en-US, hr-HR…"))
        return card
    }

    private fun skracenice(): ViewGroup {
        val (card, box) = card(this, "Skraćenice")
        box.addView(switch(this, "Skraćuj česte fraze", cfg.abbreviations) {
            cfg.abbreviations = it
        })
        box.addView(
            body(
                this,
                "Jedno pravilo po redu:  fraza=skraćenica\n" +
                    "Znak  <  pojede i razmak ispred:  minuta=<min\n" +
                    "Red sa  ~  je regularni izraz, {1} je uhvaćena grupa.",
            )
        )
        val (rules, _) = field(
            this, "Pravila", cfg.abbreviationRules, lines = 8, mono = true,
        ) { cfg.abbreviationRules = it }
        box.addView(rules)

        previewOut = body(this, "")
        val (preview, _) = field(this, "Proba pravila") { text ->
            previewOut.text = "→  " + TextPolish.apply(text, cfg).trim()
        }
        box.addView(preview)
        box.addView(previewOut)
        box.addView(button(this, "Vrati podrazumevane skraćenice") {
            cfg.abbreviationRules = Abbreviations.defaultText()
            recreate()
        })
        return card
    }

    private fun neuspeli(): ViewGroup {
        val (card, box) = card(this, "Neuspeli diktati")
        pendingLine = body(this, "")
        box.addView(pendingLine)
        box.addView(button(this, "Pošalji ponovo") { retryPending() })
        return card
    }

    private fun potrosnja(): ViewGroup {
        val (card, box) = card(this, "Potrošnja podataka")
        trafficLine = body(this, "")
        box.addView(trafficLine)
        box.addView(switch(this, "Šalji sažeto (FLAC, ~40% manje)", cfg.compressAudio) {
            cfg.compressAudio = it
        })
        box.addView(
            body(this, "Ako sažimanje ne uspe, šalje se kao pre. Traži Android 10 ili noviji.")
        )
        box.addView(button(this, "Poništi brojač") {
            cfg.resetTraffic()
            showTraffic()
        })
        return card
    }

    private fun proba(): ViewGroup {
        val (card, box) = card(this, "Proba diktata")
        val (test, _) = field(this, "Ovde probaj diktat", lines = 6)
        box.addView(test)
        return card
    }

    // ------------------------------------------------------------ podaci

    private fun showTraffic() {
        val sent = cfg.bytesSent
        val received = cfg.bytesReceived
        val count = cfg.dictationCount
        trafficLine.text = if (count == 0) {
            "Još nije poslat nijedan diktat."
        } else {
            "%d diktata, %d s govora\n↑ %s poslato   ↓ %s primljeno\nprosečno %s po diktatu"
                .format(
                    count, cfg.secondsSpoken, human(sent), human(received),
                    human((sent + received) / count),
                )
        }
    }

    private fun showPending() {
        val n = PendingStore(this).count()
        pendingLine.text = if (n == 0) {
            "Nema neuspelih snimaka."
        } else {
            "$n snimak(a) nije prepoznato — pošalji ponovo da se ne izgube."
        }
    }

    private fun retryPending() {
        val store = PendingStore(this)
        val files = store.list()
        if (files.isEmpty()) return
        pendingLine.text = "Šaljem ${files.size}…"
        Thread {
            var ubaceno = 0
            for (file in files) {
                val text = runCatching {
                    TextPolish.apply(WebStt.recognize(store.load(file), cfg), cfg)
                }.getOrNull() ?: break
                store.remove(file)
                if (text.isNotBlank() && InsertService.insert(text, cfg.restoreClipboard)) {
                    ubaceno++
                }
            }
            runOnUiThread {
                showPending()
                Toast.makeText(
                    this,
                    if (ubaceno > 0) "Ubačeno: $ubaceno" else "Tekst je u clipboard-u",
                    Toast.LENGTH_LONG,
                ).show()
            }
        }.start()
    }

    private fun human(bytes: Long): String = when {
        bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
        bytes >= 1024 -> "%.0f KB".format(bytes / 1024.0)
        else -> "$bytes B"
    }

    private fun versionName(): String = runCatching {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
    }.getOrDefault("?")

    private fun askForPermissions() {
        val missing = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) missing += Manifest.permission.RECORD_AUDIO
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) missing += Manifest.permission.POST_NOTIFICATIONS
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)
    }

    private fun openAny(vararg actions: String) {
        for (action in actions) {
            runCatching { startActivity(Intent(action)); return }
        }
        Toast.makeText(this, "Ne mogu da otvorim taj ekran — potraži ručno.", Toast.LENGTH_LONG)
            .show()
    }
}
