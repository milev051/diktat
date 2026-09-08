package studio.room211.diktat

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Rect
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
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
import com.google.android.material.color.DynamicColors
import studio.room211.diktat.Ui.body
import studio.room211.diktat.Ui.button
import studio.room211.diktat.Ui.card
import studio.room211.diktat.Ui.choice
import studio.room211.diktat.Ui.indent
import studio.room211.diktat.Ui.setBranchEnabled
import studio.room211.diktat.Ui.dp
import studio.room211.diktat.Ui.field
import studio.room211.diktat.Ui.switch

class MainActivity : AppCompatActivity() {

    private lateinit var cfg: Config
    private lateinit var statusLine: TextView
    private lateinit var trafficLine: TextView
    private lateinit var utilityLine: TextView
    private lateinit var polishLine: TextView
    private lateinit var previewOut: TextView
    private lateinit var historyRows: LinearLayout
    private lateinit var pendingRows: LinearLayout

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

        root.addView(istorija())
        root.addView(neuspeliSnimci())
        // Grupisano po pitanju na koje odgovaras: snimanje glasa, ispravka
        // teksta i osnovni izgled teksta su odvojene celine.
        root.addView(dozvole())
        root.addView(glasovniUnos())
        root.addView(ispravkaTeksta())
        root.addView(apiKeys())
        root.addView(tekst())
        root.addView(potrosnja())
        root.addView(procenaKoristi())
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
        showUtility()
        showHistory()
        showPending()
        polishLine.text = "Poziva modelu danas: ${cfg.polishCountToday}"
    }

    // ------------------------------------------------------------ kartice

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

    private fun neuspeliSnimci(): ViewGroup {
        val (card, box) = card(this, "Sačuvani audio")
        box.addView(
            body(
                this,
                "Ako transkripcija ne uspe, audio ostaje lokalno kao WAV. " +
                    "Možeš da ga pošalješ ponovo kasnije; briše se tek kada uspe.",
            )
        )
        pendingRows = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        box.addView(pendingRows)
        box.addView(button(this, "Osveži sačuvane snimke") { showPending() })
        showPending()
        return card
    }

    private fun showPending() {
        if (!::pendingRows.isInitialized) return
        pendingRows.removeAllViews()
        val store = PendingStore(this, cfg.sampleRate)
        val files = store.list()
        if (files.isEmpty()) {
            pendingRows.addView(body(this, "Nema neuspelih snimaka."))
            return
        }
        pendingRows.addView(body(this, "${files.size} sačuvanih snimaka — izaberi ponovni pokušaj ili obriši."))
        files.asReversed().forEach { file ->
            val seconds = store.seconds(file)
            pendingRows.addView(
                body(this, "${file.name.substringBeforeLast('.')} — " +
                    "${String.format(java.util.Locale.US, "%.1f", seconds)} s · " +
                    if (store.provider(file) == "openai") "OpenAI" else "Google")
            )
            val actions = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                )
            }
            val retry = button(this, "Ponovi") {
                startForegroundService(
                    Intent(this, DictationService::class.java)
                        .setAction(DictationService.ACTION_RETRY_PENDING)
                        .putExtra(DictationService.EXTRA_PENDING_NAME, file.name)
                )
                Toast.makeText(this, "Ponovni pokušaj je pokrenut.", Toast.LENGTH_SHORT).show()
            }.apply {
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    .apply { marginEnd = dp(4) }
                minHeight = dp(42)
            }
            val remove = button(this, "Obriši") {
                store.remove(file)
                showPending()
            }.apply {
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    .apply { marginStart = dp(4) }
                minHeight = dp(42)
            }
            actions.addView(retry)
            actions.addView(remove)
            pendingRows.addView(actions)
        }
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
        val showProviderOptions: (String) -> Unit = { provider ->
            googleRecording.visibility =
                if (provider == "google" || provider == "gemini_live") View.VISIBLE else View.GONE
            openAiRecording.visibility = if (provider == "openai") View.VISIBLE else View.GONE
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
                "Ovaj izbor važi za zareze, podelu na pasuse, tačke, sređivanje, " +
                    "ponavljanja i prevod. Ne menja model transkripcije.",
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

        val (jezik, _) = field(this, "Jezik izlaza (prazno = bez prevoda)", cfg.outputLanguage) {
            cfg.outputLanguage = it
        }
        box.addView(jezik)
        box.addView(
            body(this, "Slobodan opis: \u201Emakedonski\u201C, \u201Eengleski " +
                "formalno\u201C, pa i \u201Epola makedonski pola srpski\u201C.")
        )

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

    private fun procenaKoristi(): ViewGroup {
        val (card, box) = card(this, "Procena koristi — 10 dana")
        box.addView(
            body(
                this,
                "Pokreni period i aplikacija će beležiti diktate, karaktere i vreme " +
                    "snimanja po danima, kao i uspešne pozive po provajderu i modelu. " +
                    "Potrošnju API-ja unosiš ručno kada je vidiš.",
            )
        )
        utilityLine = body(this, "")
        box.addView(utilityLine)

        val (spentLayout, spentEdit) = field(
            this,
            "Potrošeno u periodu (RSD)",
            value = cfg.utilitySpent().toString(),
        )
        spentEdit.inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        box.addView(spentLayout)
        box.addView(button(this, "Sačuvaj potrošnju") {
            val amount = spentEdit.text?.toString()?.trim()?.replace(',', '.')?.toDoubleOrNull()
            if (amount == null || amount < 0) {
                Toast.makeText(this, "Unesi iznos, na primer 12,50.", Toast.LENGTH_SHORT).show()
            } else {
                cfg.setUtilitySpent(amount)
                showUtility()
            }
        })

        val (speedLayout, speedEdit) = field(
            this,
            "Tvoja brzina kucanja (karaktera/min)",
            value = cfg.utilityReport().typingCpm.toString(),
        )
        speedEdit.inputType = InputType.TYPE_CLASS_NUMBER
        box.addView(speedLayout)
        box.addView(button(this, "Sačuvaj brzinu kucanja") {
            val speed = speedEdit.text?.toString()?.trim()?.toIntOrNull()
            if (speed == null || speed <= 0) {
                Toast.makeText(this, "Unesi pozitivan ceo broj.", Toast.LENGTH_SHORT).show()
            } else {
                cfg.setUtilityTypingCpm(speed)
                showUtility()
            }
        })

        box.addView(button(this, "Pokreni novu procenu (briše staru)") {
            cfg.startUtilityEvaluation()
            spentEdit.setText("0")
            speedEdit.setText("180")
            showUtility()
        })
        box.addView(button(this, "Obriši procenu") {
            cfg.resetUtilityEvaluation()
            spentEdit.setText("0")
            speedEdit.setText("180")
            showUtility()
        })
        showUtility()
        return card
    }

    private fun showUtility() {
        if (!::utilityLine.isInitialized) return
        val report = cfg.utilityReport()
        if (!report.started) {
            utilityLine.text = "Procena nije pokrenuta."
            return
        }
        val avgDays = report.elapsedDays.coerceAtLeast(1)
        val lines = mutableListOf(
            "Period: ${report.startDate} — ${report.endDate}",
            "Dan ${report.elapsedDays}/10; preostalo: ${report.remainingDays} dana",
            "Ukupno: ${report.dictations} diktata, ${report.characters} karaktera, " +
                "${report.seconds / 60.0} min snimanja",
            "Prosek dnevno: ${"%.1f".format(report.dictations / avgDays.toDouble())} diktata, " +
                "${"%.0f".format(report.characters / avgDays.toDouble())} karaktera",
            "Procena vremena za kucanje: ${"%.2f".format(report.typedMinutes / 60.0)} h " +
                "(${report.typingCpm} karaktera/min)",
            "Uneto kao trošak: ${"%.2f".format(report.spent)} RSD",
        )
        if (report.dictations > 0) {
            lines += "Trošak po diktatu: ${"%.2f".format(report.costPerDictation)} RSD"
        }
        if (report.characters > 0) {
            lines += "Trošak na 1.000 karaktera: " +
                "${"%.2f".format(report.costPerThousandCharacters)} RSD"
        }
        if (report.modelUsage.isNotEmpty()) {
            lines += ""
            lines += "Korišćeni modeli:"
            lines += report.modelUsage.map { usage ->
                val time = if (usage.seconds > 0.0) {
                    ", ${"%.1f".format(usage.seconds / 60.0)} min zvuka"
                } else ""
                val operation = usage.operation.takeIf { it.isNotBlank() }?.let { " · $it" } ?: ""
                "${usage.provider} / ${usage.model}$operation: ${usage.calls} poziva$time"
            }
        }
        lines += ""
        lines += "Dnevno:"
        lines += report.days.map {
            "${it.date}: ${it.dictations} diktata, ${it.characters} karaktera, " +
                "${"%.1f".format(it.seconds / 60.0)} min"
        }
        utilityLine.text = lines.joinToString("\n")
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
            "%d diktata\nukupno snimljeno: %d s   (u uploadima: %d s)\n" +
                "↑ %s poslato   ↓ %s primljeno\nprosečno %s po diktatu"
                .format(
                    count, cfg.recordedSeconds, cfg.secondsSpoken,
                    human(sent), human(received),
                    prosek,
                )
        }
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
