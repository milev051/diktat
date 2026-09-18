package studio.room211.diktat

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Rect
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.button.MaterialButton
import com.google.android.material.color.DynamicColors
import com.google.android.material.progressindicator.LinearProgressIndicator
import studio.room211.diktat.Ui.body
import studio.room211.diktat.Ui.button
import studio.room211.diktat.Ui.card
import studio.room211.diktat.Ui.choice
import studio.room211.diktat.Ui.indent
import studio.room211.diktat.Ui.setBranchEnabled
import studio.room211.diktat.Ui.dp
import studio.room211.diktat.Ui.field
import studio.room211.diktat.Ui.switch
import java.io.File

class MainActivity : AppCompatActivity() {

    private companion object {
        /** Zelena je ista u svetloj i tamnoj temi; Material You je ovde ne dira. */
        val ZELENA = 0xFF2E7D32.toInt()
    }

    private lateinit var cfg: Config
    private lateinit var statusLine: TextView
    private lateinit var trafficLine: TextView
    private lateinit var polishLine: TextView
    private lateinit var previewOut: TextView
    private lateinit var historyRows: LinearLayout
    private lateinit var updateLine: TextView
    private lateinit var updateButton: MaterialButton
    private var updateButtonBackground: ColorStateList? = null
    private var updateButtonStroke: ColorStateList? = null
    private var updateButtonText: ColorStateList? = null
    private var updateLineColor: ColorStateList? = null
    private var novoIzdanje: Azuriranje.Izdanje? = null
    private var proveraUToku = false

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
            text = "verzija ${versionName()}"
            setTextAppearance(
                com.google.android.material.R.style.TextAppearance_Material3_BodySmall
            )
            alpha = 0.6f
            setPadding(dp(4), dp(12), 0, dp(16))
        })

        root.addView(azuriranje())
        root.addView(istorija())
        // Grupisano po pitanju na koje odgovaras: snimanje glasa, ispravka
        // teksta i osnovni izgled teksta su odvojene celine.
        root.addView(dozvole())
        root.addView(glasovniUnos())
        root.addView(ispravkaTeksta())
        root.addView(apiKeys())
        root.addView(tekst())
        root.addView(potrosnja())
        root.addView(proba())

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(root)
        }
        setContentView(scroll)

        // Tiha provera: nista ne iskace, dugme samo pozeleni ako ima nove verzije.
        if (cfg.updateCheckOnStart) proveriAzuriranje(tiho = true)

        // Sadrzaj ide ispod statusne trake, pa se razmak dodaje rucno. Visina
        // tastature se mora dodati na dno: bez toga tastatura prekrije polje u
        // koje se kuca i ne vidi se sta pises.
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            view.setPadding(0, bars.top, 0, maxOf(bars.bottom, ime.bottom))
            // Kad tastatura izadje, polje u koje se kuca mora samo da dodje u
            // vidno polje — inace se do njega skroluje rukom svaki put.
            if (ime.bottom > 0) {
                view.post {
                    currentFocus?.let { fokus ->
                        fokus.requestRectangleOnScreen(
                            Rect(0, 0, fokus.width, fokus.height + dp(24)), false
                        )
                    }
                }
            }
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
        showHistory()
        polishLine.text = "Poziva modelu danas: ${cfg.polishCountToday}"
    }

    // ------------------------------------------------------------ kartice

    /**
     * Verzija i azuriranje sa GitHub izdanja.
     *
     * Aplikacija nije na Google Play-u, pa niko ne javlja da je izasla nova
     * verzija. Dugme je zeleno samo kada nova verzija stvarno postoji: tako se
     * stanje vidi sa vrha ekrana, bez otvaranja bilo cega.
     */
    private fun azuriranje(): ViewGroup {
        val (card, box) = card(this, "Verzija i ažuriranje")
        box.addView(
            body(
                this,
                "Instalirana verzija ${versionName()}. Aplikacija nije na Google Play-u, " +
                    "pa nova verzija stiže sa GitHub izdanja i instalira se kao i svaki " +
                    "drugi APK.",
            )
        )
        updateLine = body(this, "")
        updateLineColor = updateLine.textColors
        box.addView(updateLine)

        updateButton = button(this, "Proveri ažuriranje") {
            val spremno = novoIzdanje
            if (spremno != null) preuzmiIzdanje(spremno) else proveriAzuriranje(tiho = false)
        }
        updateButtonBackground = updateButton.backgroundTintList
        updateButtonStroke = updateButton.strokeColor
        updateButtonText = updateButton.textColors
        box.addView(updateButton)

        box.addView(
            switch(this, "Proveri ažuriranje pri pokretanju", cfg.updateCheckOnStart) {
                cfg.updateCheckOnStart = it
            }
        )
        prikaziStanje(
            if (cfg.updateCheckOnStart) "Proveravam GitHub izdanja\u2026" else "Još nije provereno.",
            null,
        )
        return card
    }

    /** Jedno mesto koje crta stanje provere; zeleno znaci „ima nova verzija". */
    private fun prikaziStanje(poruka: String, izdanje: Azuriranje.Izdanje?) {
        if (!::updateLine.isInitialized) return
        novoIzdanje = izdanje
        updateLine.text = poruka
        if (izdanje != null) {
            val zelena = ColorStateList.valueOf(ZELENA)
            updateButton.text = "Preuzmi i instaliraj ${izdanje.oznaka}"
            updateButton.backgroundTintList = zelena
            updateButton.strokeColor = zelena
            updateButton.setTextColor(0xFFFFFFFF.toInt())
            updateLine.setTextColor(ZELENA)
            updateLine.alpha = 1f
        } else {
            updateButton.text = "Proveri ažuriranje"
            updateButton.backgroundTintList = updateButtonBackground
            updateButtonStroke?.let { updateButton.strokeColor = it }
            updateButtonText?.let { updateButton.setTextColor(it) }
            updateLineColor?.let { updateLine.setTextColor(it) }
            updateLine.alpha = 0.75f
        }
    }

    /** `tiho` je provera pri pokretanju: ne otvara prozore i ne javlja gresku. */
    private fun proveriAzuriranje(tiho: Boolean) {
        if (proveraUToku) return
        proveraUToku = true
        if (!tiho) prikaziStanje("Proveravam GitHub izdanja\u2026", null)
        Thread {
            val ishod = runCatching { Azuriranje.poslednje() }
            runOnUiThread {
                proveraUToku = false
                if (isDestroyed) return@runOnUiThread
                val trenutna = versionName()
                ishod.onSuccess { izdanje ->
                    if (Azuriranje.novije(trenutna, izdanje.oznaka)) {
                        prikaziStanje(
                            "Nova verzija ${izdanje.oznaka} je spremna, instalirana je $trenutna.",
                            izdanje,
                        )
                    } else {
                        prikaziStanje("Imaš najnoviju verziju ($trenutna).", null)
                    }
                }.onFailure { greska ->
                    prikaziStanje(
                        "Provera nije uspela: ${greska.message ?: "nepoznata greška"}",
                        null,
                    )
                }
            }
        }.start()
    }

    private fun preuzmiIzdanje(izdanje: Azuriranje.Izdanje) {
        if (!Azuriranje.smeDaInstalira(this)) {
            AlertDialog.Builder(this)
                .setTitle("Potrebna dozvola")
                .setMessage(
                    "Android traži da aplikaciji dozvoliš instaliranje aplikacija iz " +
                        "nepoznatih izvora. Otvoriću podešavanja, pa se vrati nazad i " +
                        "probaj ponovo."
                )
                .setPositiveButton("Otvori podešavanja") { _, _ -> Azuriranje.otvoriDozvolu(this) }
                .setNegativeButton("Odustani", null)
                .show()
            return
        }

        val traka = LinearProgressIndicator(this).apply {
            max = 100
            progress = 0
        }
        val prozor = AlertDialog.Builder(this)
            .setTitle("Preuzimam ${izdanje.oznaka}")
            .setView(LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(24), dp(20), dp(24), dp(8))
                addView(traka)
            })
            .setCancelable(false)
            .create()
        prozor.show()

        val kontekst = applicationContext
        Thread {
            val ishod = runCatching {
                Azuriranje.preuzmi(kontekst, izdanje.adresaApk) { deo ->
                    runOnUiThread { traka.setProgressCompat(deo, true) }
                }
            }
            runOnUiThread {
                if (prozor.isShowing && !isFinishing && !isDestroyed) prozor.dismiss()
                if (isDestroyed) return@runOnUiThread
                ishod.onSuccess { fajl: File ->
                    runCatching { Azuriranje.instaliraj(this, fajl) }.onFailure { greska ->
                        prikaziStanje(
                            "Instalacija nije pokrenuta: ${greska.message ?: "nepoznata greška"}",
                            izdanje,
                        )
                    }
                }.onFailure { greska ->
                    prikaziStanje(
                        "Preuzimanje nije uspelo: ${greska.message ?: "nepoznata greška"}",
                        izdanje,
                    )
                }
            }
        }.start()
    }

    private fun istorija(): ViewGroup {
        val (card, box) = card(this, "Istorija diktata")
        box.addView(body(this, "Poslednjih 5 uspešnih rezultata. Klikni na poruku da kopiraš ceo tekst."))
        historyRows = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        box.addView(historyRows)
        box.addView(button(this, "Obriši istoriju") {
            cfg.clearHistory()
            showHistory()
        })
        showHistory()
        return card
    }

    private fun showHistory() {
        if (!::historyRows.isInitialized) return
        historyRows.removeAllViews()
        val items = cfg.history()
        if (items.isEmpty()) {
            historyRows.addView(body(this, "Još nema sačuvanih diktata."))
            return
        }
        items.forEachIndexed { index, text ->
            val item = button(this, "") {
                copyHistory(text)
            }
            item.text = (index + 1).toString() + ". " +
                text.replace(Regex("\\s+"), " ").trim()
            item.gravity = Gravity.START
            item.maxLines = 4
            item.ellipsize = TextUtils.TruncateAt.END
            historyRows.addView(item)
        }
    }

    private fun copyHistory(text: String) {
        getSystemService(ClipboardManager::class.java).setPrimaryClip(
            ClipData.newPlainText("Diktat", text)
        )
        Toast.makeText(this, "Kopirano u clipboard.", Toast.LENGTH_SHORT).show()
    }

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
        box.addView(button(this, "Mikrofon na tastaturi (Voice input)") {
            openAny(Settings.ACTION_VOICE_INPUT_SETTINGS, Settings.ACTION_INPUT_METHOD_SETTINGS)
        })
        box.addView(
            body(
                this,
                "Umesto bočnog tastera možeš izabrati Diktat kao Voice input; " +
                    "tada mikrofon na tastaturi radi isto, bez Pristupačnosti.",
            )
        )
        return card
    }

    private fun glasovniUnos(): ViewGroup {
        val (card, box) = card(this, "Glasovni unos")
        box.addView(
            body(this, "Izaberi servis koji pretvara govor u tekst. Podešavanja " +
                "za snimanje prikazuju se prema izabranom servisu.")
        )

        val googleRecording = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(switch(this@MainActivity, "Google neprekidno snimanje", cfg.continuous) {
                cfg.continuous = it
            })
            addView(
                body(
                    this@MainActivity,
                    "Seče na pauzama i šalje delove dok govoriš. Isključeno: " +
                        "jedan snimak do 30 sekundi.",
                )
            )
        }
        val openAiRecording = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(
                switch(
                    this@MainActivity,
                    "OpenAI dugi diktat (do 60 min)",
                    cfg.openAiLongRecording,
                ) { cfg.openAiLongRecording = it },
            )
            addView(
                body(
                    this@MainActivity,
                    "Šalje završen snimak posle Stop-a. Isključeno: jedan snimak " +
                        "do 30 sekundi.",
                )
            )
            addView(body(this@MainActivity, "OpenAI output script"))
            addView(
                choice(
                    this@MainActivity,
                    listOf(
                        "auto" to "Auto",
                        "cyrillic" to "Ćirilica",
                        "latin" to "Latinica",
                    ),
                    cfg.openAiOutputScript,
                ) { cfg.openAiOutputScript = it },
            )
        }
        val geminiRecording = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(switch(
                this@MainActivity,
                "Prikazuj prepis uživo tokom snimanja",
                cfg.geminiLivePreview,
            ) { cfg.geminiLivePreview = it })
            addView(body(
                this@MainActivity,
                "Međurezultat se prikazuje uz tajmer. U polje ulazi samo konačan tekst.",
            ))
        }
        val showProviderOptions: (String) -> Unit = { provider ->
            googleRecording.visibility =
                if (provider == "google" || provider == "gemini_live") View.VISIBLE else View.GONE
            openAiRecording.visibility = if (provider == "openai") View.VISIBLE else View.GONE
            geminiRecording.visibility = if (provider == "gemini_live") View.VISIBLE else View.GONE
        }

        box.addView(body(this, "Provider transkripcije"))
        box.addView(
            choice(
                this,
                listOf(
                    "google" to "Google Speech-to-Text",
                    "openai" to "OpenAI GPT Transcribe",
                    "gemini_live" to "Gemini 3.5 Transcribe Live",
                ),
                cfg.transcriptionProvider,
            ) { provider ->
                cfg.transcriptionProvider = provider
                showProviderOptions(provider)
            },
        )
        box.addView(
            body(
                this,
                "Google koristi postojeći Web Speech tok. OpenAI šalje završen " +
                    "snimak na Audio Transcriptions API i koristi model gpt-transcribe; " +
                    "ne koristi realtime transkripciju. Gemini Transcribe Live " +
                    "šalje zvuk DOK pričaš, pa posle Stop-a nema čekanja — traži " +
                    "stalnu vezu i troši oko 2,5 MB po minutu. Koristi isti " +
                    "Gemini ključ kao AI obrada.",
            )
        )
        box.addView(googleRecording)
        box.addView(geminiRecording)
        box.addView(openAiRecording)
        showProviderOptions(cfg.transcriptionProvider)

        return card
    }

    private fun ispravkaTeksta(): ViewGroup {
        val (card, box) = card(this, "Ispravka teksta pomoću AI")
        box.addView(
            body(
                this,
                "Izaberi model koji sređuje već dobijeni tekst. Ovo je odvojeno " +
                    "od servisa koji transkribuje govor.",
            )
        )

        box.addView(body(this, "Model za manipulaciju teksta"))
        box.addView(
            choice(
                this,
                listOf(
                    "gemini" to "Gemini",
                    "groq" to "Groq GPT-OSS 120B",
                ),
                cfg.textModel,
            ) { cfg.textModel = it },
        )
        box.addView(
            body(
                this,
                "Ovaj izbor važi za zareze, podelu na pasuse, tačke, sređivanje " +
                    "i ponavljanja. Ne menja model transkripcije.",
            )
        )
        box.addView(switch(this, "Sredi tekst (tačke i velika slova)", cfg.polishTidy) {
            cfg.textStyle = if (it) "written" else "spoken"
        })

        box.addView(switch(this, "Dodaj samo zareze", cfg.polishCommas) {
            cfg.polishCommas = it
        })

        box.addView(switch(this, "Sažmi u tačke", cfg.polishBullets) {
            cfg.polishBullets = it
        })

        box.addView(switch(this, "Podeli na pasuse", cfg.polishParagraphs) {
            cfg.polishParagraphs = it
        })

        box.addView(switch(this, "Izbaci ponavljanja", cfg.polishDedupe) {
            cfg.polishDedupe = it
        })

        polishLine = body(this, "")
        box.addView(polishLine)
        return card
    }

    private fun apiKeys(): ViewGroup {
        val (card, box) = card(this, "API ključevi")
        box.addView(
            body(
                this,
                "Svaki servis ima svoje posebno polje. Ključevi se čuvaju локално " +
                    "у апликацији и користе се само када је одговарајућа опција укључена.",
            )
        )
        val (gemini, _) = field(this, "Gemini API ključ", cfg.polishApiKey) {
            cfg.polishApiKey = it
        }
        box.addView(gemini)
        box.addView(body(this, "Gemini obrada teksta."))

        val (groq, _) = field(this, "Groq API ključ", cfg.groqApiKey) {
            cfg.groqApiKey = it
        }
        box.addView(groq)
        box.addView(body(this, "Groq GPT-OSS obrada teksta."))
        val (openAi, _) = field(this, "OpenAI API ključ", cfg.openAiApiKey) {
            cfg.openAiApiKey = it
        }
        box.addView(openAi)
        box.addView(body(this, "OpenAI GPT Transcribe; користи се само када је OpenAI изабран."))
        box.addView(button(this, "Proveri sve API ključeve") {
            Toast.makeText(this, "Provera ključeva je pokrenuta.", Toast.LENGTH_SHORT).show()
            Thread {
                val check = Config(this)
                val results = listOf(
                    "Gemini" to runCatching { Polish.testKey(check) },
                    "Groq" to runCatching { Groq.testKey(check) },
                    "OpenAI" to runCatching { OpenAiTranscription.testKey(check) },
                ).joinToString("\n") { (name, result) ->
                    result.fold(
                        onSuccess = { "✓ $it" },
                        onFailure = { "✗ $name: ${it.message ?: "provera nije uspela"}" },
                    )
                }
                runOnUiThread {
                    AlertDialog.Builder(this)
                        .setTitle("Provera API ključeva")
                        .setMessage(results + "\n\nProvera ne šalje audio i ne troši minute transkripcije.")
                        .setPositiveButton("U redu", null)
                        .show()
                }
            }.start()
        })
        return card
    }

    private fun tekst(): ViewGroup {
        // Ovo radi nas kod, bez modela i bez kljuca — zato je odvojeno od AI
        // kartice i radi i kad je AI iskljucen.
        val (card, box) = card(this, "Tekst")

        // `isChecked` iz koda okida istog slusaoca kao i prst, pa bi bez ove
        // zastavice sinhronizacija prepisivala podesavanja koja upravo cita.
        var sinhronizujem = false
        lateinit var swPravilno: com.google.android.material.materialswitch.MaterialSwitch
        lateinit var swMala: com.google.android.material.materialswitch.MaterialSwitch
        lateinit var swInterpunkcija: com.google.android.material.materialswitch.MaterialSwitch
        lateinit var swKvacice: com.google.android.material.materialswitch.MaterialSwitch
        lateinit var swSkracenice: com.google.android.material.materialswitch.MaterialSwitch

        // Kvacica na „Pravilno" se IZVODI iz ta cetiri, ne pamti se zasebno:
        // inace bi rucno gasenje jednog od njih ostavilo nad-prekidac da laze.
        fun osvezi() {
            sinhronizujem = true
            swPravilno.isChecked = cfg.pravilno
            swMala.isChecked = cfg.lowercase
            swInterpunkcija.isChecked = cfg.stripPunctuation
            swKvacice.isChecked = cfg.asciiDiacritics
            swSkracenice.isChecked = cfg.abbreviations
            sinhronizujem = false
        }

        // Nad-prekidac iznad cetiri. Nije peto podesavanje nego precica: cetiri
        // klika za prelazak izmedju „kako sam izgovorio" i „pravopisno" su
        // cetiri prilike da se jedan zaboravi, pa tekst izadje na pola puta.
        swPravilno = switch(this, "Pravilno (gasi sva četiri ispod)", cfg.pravilno) {
            if (!sinhronizujem) {
                cfg.pravilno = it
                osvezi()
            }
        }
        box.addView(swPravilno)
        box.addView(
            body(
                this,
                "Isto što radi dugme pored brojača dok snimaš. Isključivanje vraća " +
                    "ono što je bilo uključeno pre, ne podrazumevano.",
            )
        )

        swMala = switch(this, "Sva slova mala", cfg.lowercase) {
            if (!sinhronizujem) { cfg.lowercase = it; osvezi() }
        }
        box.addView(swMala)
        swInterpunkcija = switch(this, "Ukloni interpunkciju (brojevi ostaju)", cfg.stripPunctuation) {
            if (!sinhronizujem) { cfg.stripPunctuation = it; osvezi() }
        }
        box.addView(swInterpunkcija)
        swKvacice = switch(this, "Bez kvačica (č ć ž š đ → c c z s dj)", cfg.asciiDiacritics) {
            if (!sinhronizujem) { cfg.asciiDiacritics = it; osvezi() }
        }
        box.addView(swKvacice)
        swSkracenice = switch(this, "Skraćuj česte fraze", cfg.abbreviations) {
            if (!sinhronizujem) { cfg.abbreviations = it; osvezi() }
        }
        box.addView(swSkracenice)
        box.addView(
            body(
                this,
                "Brojevi napisani rečima ostaju kao u transkripciji; na primer " +
                    "\u201Epet minuta\u201C \u2192 \u201Epet min\u201C, dok \u201E5 minuta\u201C postaje \u201E5min\u201C. " +
                    "Česte fraze su ugrađene u ovaj build i na telefonu služe samo za čitanje.",
            )
        )
        box.addView(body(this, "Ugrađene česte fraze:"))
        val pravila = body(this, cfg.abbreviationRules).apply {
            setTextIsSelectable(true)
            setTypeface(android.graphics.Typeface.MONOSPACE)
        }
        box.addView(pravila)
        return card
    }

    private fun potrosnja(): ViewGroup {
        val (card, box) = card(this, "Potrošnja podataka")
        trafficLine = body(this, "")
        box.addView(trafficLine)
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
        val (test, testEdit) = field(this, "Ovde probaj diktat", lines = 6)
        box.addView(test)
        box.addView(button(this, "Obriši") { testEdit.setText("") })
        return card
    }

    // ------------------------------------------------------------ podaci

    private fun showTraffic() {
        val sent = cfg.bytesSent
        val received = cfg.bytesReceived
        val count = cfg.dictationCount
        trafficLine.text = if (count == 0 && cfg.recordedSeconds == 0L) {
            "Još nije poslat nijedan diktat."
        } else {
            val prosek = if (count > 0) human((sent + received) / count) else "—"
            // Zagrade nisu ukras: bez njih `.format` hvata samo POSLEDNJI niz u
            // sabiranju, pa je prvi red ostajao sa sirovim „%d" na ekranu, a
            // drugi je punio pogrešnim vrednostima.
            ("%s diktata\nukupno snimljeno: %s   (u uploadima: %s)\n" +
                "↑ %s poslato   ↓ %s primljeno\nprosečno %s po diktatu").format(
                    count, trajanje(cfg.recordedSeconds), trajanje(cfg.secondsSpoken),
                    human(sent), human(received),
                    prosek,
                )
        }
    }

    /** Sekunde u „2 h 15 min 30 s"; nule se ne ispisuju, kao i na Mac-u. */
    private fun trajanje(seconds: Long): String {
        val ukupno = maxOf(0L, seconds)
        val sati = ukupno / 3600
        val minuti = (ukupno % 3600) / 60
        val sekunde = ukupno % 60
        val delovi = mutableListOf<String>()
        if (sati > 0) delovi += "$sati h"
        if (minuti > 0) delovi += "$minuti min"
        if (sekunde > 0 || delovi.isEmpty()) delovi += "$sekunde s"
        return delovi.joinToString(" ")
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
