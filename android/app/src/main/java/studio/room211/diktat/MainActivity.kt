package studio.room211.diktat

import android.Manifest
import android.app.AlarmManager
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Rect
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.TextUtils
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import android.view.inputmethod.EditorInfo
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

        /** Izbor „Interpunkcija": kljuc -> natpis na dugmetu. Isto kao na Mac-u. */
        val INTERPUNKCIJA = listOf(
            "sva" to "Sva",
            "zarezi" to "Zarezi i ?",
            "bez" to "Bez",
        )
    }

    private lateinit var cfg: Config
    private lateinit var trafficLine: TextView
    private lateinit var polishLine: TextView
    private lateinit var previewOut: TextView
    private lateinit var dictationStart: MaterialButton
    private lateinit var dictationStop: MaterialButton
    private val dictationHandler = Handler(Looper.getMainLooper())
    private val dictationTick = object : Runnable {
        override fun run() {
            updateDictationButtons()
            maybeAutoUpdate()
            dictationHandler.postDelayed(this, 250)
        }
    }
    private lateinit var historyRows: LinearLayout
    private lateinit var permissionCard: ViewGroup
    private lateinit var dozvoleRows: LinearLayout
    private lateinit var permissionRows: LinearLayout
    private lateinit var updateButton: MaterialButton
    private var updateButtonBackground: ColorStateList? = null
    private var updateButtonStroke: ColorStateList? = null
    private var updateButtonText: ColorStateList? = null
    private var updateLineColor: ColorStateList? = null
    private var novoIzdanje: Azuriranje.Izdanje? = null
    private var dugmeVerzije: MaterialButton? = null
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

        root.addView(dugmeAzuriranja())
        root.addView(switch(this, "Lowercase", cfg.lowercase) { cfg.lowercase = it })
        root.addView(switch(this, "Remove diacritics", cfg.asciiDiacritics) { cfg.asciiDiacritics = it })
        root.addView(switch(this, "Abbreviations", cfg.abbreviations) { cfg.abbreviations = it })
        root.addView(compactProvider())
        root.addView(compactKey())
        root.addView(nedostajuceDozvole())
        root.addView(istorija())

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(root)
        }
        setContentView(scroll)

        // Tiha provera: nista ne iskace, dugme samo pozeleni ako ima nove verzije.
        if (cfg.updateCheckOnStart) proveriAzuriranje(tiho = true)
        val posleRestarta = cfg.porukaPosleRestarta
        if (posleRestarta.isNotBlank()) {
            cfg.porukaPosleRestarta = ""
            Toast.makeText(this, posleRestarta, Toast.LENGTH_LONG).show()
        }
        vratiPrekinutPrepis()

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
        showPermissions()
        showHistory()
        dictationHandler.post(dictationTick)
    }

    override fun onPause() {
        dictationHandler.removeCallbacks(dictationTick)
        super.onPause()
    }

    private fun updateDictationButtons() {
        if (!::dictationStart.isInitialized) return
        val recording = DictationService.isRecording
        dictationStart.isEnabled = true
        dictationStart.text = if (recording) "Stop" else "Record"

    }

    /**
     * Gasi proces i otvara aplikaciju iznova.
     *
     * Ako je prepis ostao samo na prikazu, ide u clipboard pre gašenja: polje
     * u drugoj aplikaciji tada više nije u fokusu, pa se lepi ručno.
     */
    private fun ponovoPokreni() {
        val tekst = cfg.nedovrseniPrepis.trim()
        if (tekst.isNotBlank()) {
            getSystemService(ClipboardManager::class.java).setPrimaryClip(
                ClipData.newPlainText("diktat", tekst)
            )
            cfg.nedovrseniPrepis = ""
            cfg.porukaPosleRestarta = "Prekinut prepis je u clipboard-u. Nalepi ga u polje."
        }
        val restart = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        val pending = PendingIntent.getActivity(
            applicationContext,
            77,
            restart,
            PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE,
        )
        getSystemService(AlarmManager::class.java)
            .set(AlarmManager.RTC, System.currentTimeMillis() + 400, pending)
        finishAffinity()
        android.os.Process.killProcess(android.os.Process.myPid())
        kotlin.system.exitProcess(0)
    }

    private fun vratiPrekinutPrepis() {
        if (DictationService.isRecording) return
        val tekst = cfg.nedovrseniPrepis.trim()
        if (tekst.isBlank()) return
        getSystemService(ClipboardManager::class.java).setPrimaryClip(
            ClipData.newPlainText("diktat", tekst)
        )
        cfg.nedovrseniPrepis = ""
        Toast.makeText(
            this,
            "Prekinut prepis je u clipboard-u. Nalepi ga u polje.",
            Toast.LENGTH_LONG,
        ).show()
    }

    private fun dictationCommand(action: String) {
        val intent = Intent(this, DictationService::class.java).setAction(action)
        if (action == DictationService.ACTION_START) startForegroundService(intent)
        else startService(intent)
        updateDictationButtons()
    }

    // ------------------------------------------------------------ kartice

    /**
     * Sta jos nije odobreno, sa dugmetom koje vodi tacno tamo.
     *
     * Podesavanja su na Samsungu razbacana po pet ekrana, pa je bez ovoga
     * korisnik morao da zna gde je sta. Kartica se crta pri svakom povratku u
     * aplikaciju i nestaje sama kada je sve odobreno.
     */
    private fun nedostajuceDozvole(): ViewGroup {
        permissionRows = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        permissionCard = permissionRows
        return permissionRows
    }

    /** Jedna stavka provere: ime, zasto treba, da li je odobrena i gde se odobrava. */
    private data class Provera(
        val naziv: String,
        val zasto: String,
        val odobreno: () -> Boolean,
        val otvori: () -> Unit,
        /** Neobavezne stavke se ne guraju na vrh ekrana, samo se vidi stanje. */
        val obavezna: Boolean = true,
    )

    private fun provere(): List<Provera> {
        val spisak = mutableListOf(
            Provera(
                "Microphone",
                "bez njega nema snimanja",
                { checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED },
                { requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1) },
            ),
            Provera(
                "Digital assistant",
                "bočni taster pokreće diktat",
                { jeNas(secure("assistant")) || jeNas(secure("voice_interaction_service")) },
                {
                    openAny(
                        "android.settings.VOICE_INPUT_SETTINGS",
                        Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS, Settings.ACTION_SETTINGS,
                    )
                },
            ),
            Provera(
                "Display over other apps",
                "tajmer dok snimaš",
                { Settings.canDrawOverlays(this) },
                {
                    runCatching {
                        startActivity(
                            Intent(
                                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:$packageName"),
                            )
                        )
                    }
                },
            ),
            Provera(
                "Text input (Accessibility)",
                "bez toga tekst ostaje u clipboard-u",
                { InsertService.isRunning },
                { openAny(Settings.ACTION_ACCESSIBILITY_SETTINGS) },
            ),
            Provera(
                "Install updates",
                "nova verzija se instalira iz aplikacije",
                { Azuriranje.smeDaInstalira(this) },
                { Azuriranje.otvoriDozvolu(this) },
            ),
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            spisak += Provera(
                "Notifications",
                "stanje diktata u statusnoj traci",
                {
                    checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
                        PackageManager.PERMISSION_GRANTED
                },
                { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1) },
            )
        }
        // Samsung tastatura za mikrofon prihvata samo Google-ove pakete
        // (`com.google.android…`), pa Diktat tamo ne moze; Gboard pita sistem
        // koja je glasovna tastatura izabrana i poštuje izbor (22.09.2026).
        spisak += Provera(
            "Mikrofon na Gboard tastaturi",
            "uključi „Diktat glasovni unos“ u listi tastatura; mikrofon na " +
                "Gboard-u tada koristi Diktat. Samsung tastatura to ne dozvoljava.",
            { jeNas(secure("enabled_input_methods")) },
            { openAny(Settings.ACTION_INPUT_METHOD_SETTINGS) },
            obavezna = false,
        )
        return spisak
    }

    private fun odobreno(stavka: Provera) =
        runCatching { stavka.odobreno() }.getOrDefault(false)

    private fun showPermissions() {
        val sve = provere()

        if (::permissionRows.isInitialized) {
            permissionRows.removeAllViews()
            val nedostaju = sve.filter { it.obavezna && !odobreno(it) }
            permissionCard.visibility = if (nedostaju.isEmpty()) View.GONE else View.VISIBLE
            for (stavka in nedostaju) {
                permissionRows.addView(button(this, "Allow: ${stavka.naziv}") { stavka.otvori() })
            }
        }

        // Puna lista istih ekrana: odobreno nosi kvacicu i pritajeno je, jer
        // sluzi samo za kasniju promenu, a neodobreno ostaje da se istice.
        if (!::dozvoleRows.isInitialized) return
        dozvoleRows.removeAllViews()
        for (stavka in sve) {
            val ok = odobreno(stavka)
            val dugme = button(this, if (ok) "✓ ${stavka.naziv}" else stavka.naziv) {
                stavka.otvori()
            }
            if (ok) dugme.alpha = 0.55f
            dozvoleRows.addView(dugme)
            if (!ok) dozvoleRows.addView(indent(this, body(this, stavka.zasto)))
        }
    }

    /** Sistemsko podesavanje kao tekst; nedostupno se ponasa kao prazno. */
    private fun secure(kljuc: String): String =
        runCatching { Settings.Secure.getString(contentResolver, kljuc).orEmpty() }
            .getOrDefault("")

    private fun jeNas(vrednost: String) = vrednost.contains(packageName)

    /**
     * Azuriranje sa GitHub izdanja, bez natpisa na ekranu.
     *
     * Aplikacija nije na Google Play-u. Nova verzija se preuzima sama kada se
     * ne snima; Android i dalje trazi potvrdu instalacije.
     */
    private var downloadRunning = false
    private var attemptedUpdate = ""
    private var pendingApk: File? = null
    private lateinit var geminiKeyRow: LinearLayout
    private lateinit var geminiCheck: MaterialButton
    private var keyCheckGeneration = 0

    private fun prikaziStanje(poruka: String, izdanje: Azuriranje.Izdanje?) {
        novoIzdanje = izdanje
        dugmeVerzije?.text = "Version ${versionName()}\n$poruka"
    }

    /**
     * Veliko dugme na vrhu: pokazuje instaliranu verziju i na klik pita GitHub
     * za novo izdanje. Ako ga ima, preuzima APK i otvara sistemsku instalaciju.
     */
    private fun dugmeAzuriranja(): MaterialButton {
        val dugme = button(this, "Version ${versionName()}\nCheck for updates") {
            val izdanje = novoIzdanje
            when {
                izdanje != null && !Azuriranje.smeDaInstalira(this) -> {
                    Toast.makeText(this, "Allow installing updates, then tap again.", Toast.LENGTH_LONG).show()
                    Azuriranje.otvoriDozvolu(this)
                }
                izdanje != null -> {
                    attemptedUpdate = ""
                    prikaziStanje("Downloading ${izdanje.oznaka}\u2026", izdanje)
                    preuzmiIzdanje(izdanje)
                }
                else -> proveriAzuriranje(tiho = false)
            }
        }
        dugme.minHeight = dp(64)
        dugme.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 16f)
        dugme.contentDescription = "Check for updates"
        (dugme.layoutParams as LinearLayout.LayoutParams).bottomMargin = dp(8)
        dugmeVerzije = dugme
        return dugme
    }

    private fun maybeAutoUpdate() {
        if (DictationService.isActive || downloadRunning || isFinishing || isDestroyed) return
        val apk = pendingApk
        if (apk != null) {
            pendingApk = null
            runCatching { Azuriranje.instaliraj(this, apk) }
            return
        }
        val release = novoIzdanje ?: return
        if (attemptedUpdate == release.oznaka || !Azuriranje.smeDaInstalira(this)) return
        attemptedUpdate = release.oznaka
        preuzmiIzdanje(release)
    }

    private fun compactProvider(): ViewGroup {
        val providers = listOf("gemini_live", "google")
        val spinner = android.widget.Spinner(this).apply {
            adapter = android.widget.ArrayAdapter(this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item,
                listOf("Gemini 3.5 Transcribe Live", "Google Speech-to-Text"))
            setSelection(providers.indexOf(cfg.transcriptionProvider).coerceAtLeast(0))
            contentDescription = "Transcription service"
            onItemSelectedListener = object : android.widget.AdapterView.OnItemSelectedListener {
                override fun onNothingSelected(parent: android.widget.AdapterView<*>?) {}
                override fun onItemSelected(parent: android.widget.AdapterView<*>?, view: View?, position: Int, id: Long) {
                    cfg.transcriptionProvider = providers[position]
                    if (::geminiKeyRow.isInitialized) geminiKeyRow.visibility =
                        if (position == 0) View.VISIBLE else View.GONE
                }
            }
        }
        // Ceo izbor servisa stoji u okviru, istom kao polje kljuca ispod njega.
        return android.widget.FrameLayout(this).apply {
            background = okvir()
            setPadding(dp(4), 0, dp(4), 0)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(8) }
            addView(spinner, android.widget.FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(56), Gravity.CENTER_VERTICAL,
            ))
        }
    }

    private fun bojaTeme(attr: Int): Int {
        val v = android.util.TypedValue()
        theme.resolveAttribute(attr, v, true)
        return v.data
    }

    private fun okvir() = android.graphics.drawable.GradientDrawable().apply {
        cornerRadius = dp(14).toFloat()
        setStroke(dp(1), bojaTeme(com.google.android.material.R.attr.colorOutline))
    }

    private fun compactKey(): ViewGroup {
        geminiKeyRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val (layout, edit) = field(this, "", cfg.polishApiKey) { cfg.polishApiKey = it }
        layout.isHintEnabled = false
        edit.contentDescription = "Gemini API key"
        // Polje kljuca je uokvireno, kao izbor servisa iznad njega.
        layout.boxBackgroundMode = com.google.android.material.textfield.TextInputLayout.BOX_BACKGROUND_OUTLINE
        layout.boxStrokeWidth = dp(1)
        layout.boxStrokeWidthFocused = dp(2)
        layout.setBoxStrokeColorStateList(ColorStateList(
            arrayOf(intArrayOf(android.R.attr.state_focused), intArrayOf()),
            intArrayOf(
                bojaTeme(androidx.appcompat.R.attr.colorPrimary),
                bojaTeme(com.google.android.material.R.attr.colorOutline),
            ),
        ))
        val r = dp(14).toFloat()
        layout.setBoxCornerRadii(r, r, r, r)
        geminiKeyRow.setPadding(0, dp(8), 0, 0)
        geminiKeyRow.gravity = Gravity.CENTER_VERTICAL
        edit.inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
        edit.setOnFocusChangeListener { _, focused -> if (!focused) checkGeminiKey() }
        geminiKeyRow.addView(layout, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        geminiCheck = button(this, "✓") { checkGeminiKey() }
        geminiCheck.contentDescription = "Check Gemini key"
        geminiKeyRow.addView(geminiCheck, LinearLayout.LayoutParams(dp(56), dp(56)).apply {
            marginStart = dp(8)
        })
        geminiKeyRow.visibility = if (cfg.transcriptionProvider == "gemini_live") View.VISIBLE else View.GONE
        checkGeminiKey()
        return geminiKeyRow
    }

    private fun checkGeminiKey() {
        if (!::geminiCheck.isInitialized) return
        val key = cfg.polishApiKey
        val generation = ++keyCheckGeneration
        geminiCheck.text = "…"
        Thread {
            val ok = runCatching { Polish.testKey(Config(this)) }.isSuccess
            runOnUiThread {
                if (isDestroyed || generation != keyCheckGeneration || key != cfg.polishApiKey) return@runOnUiThread
                geminiCheck.text = if (ok) "✓" else "×"
                geminiCheck.setTextColor(if (ok) ZELENA else 0xFFB3261E.toInt())
                geminiCheck.contentDescription = if (ok) "Gemini key works" else "Gemini key check failed"
            }
        }.start()
    }

    /** `tiho` je provera pri pokretanju: ne otvara prozore i ne javlja gresku. */
    private fun proveriAzuriranje(tiho: Boolean) {
        if (proveraUToku) return
        proveraUToku = true
        if (!tiho) prikaziStanje("Checking\u2026", null)
        Thread {
            val ishod = runCatching { Azuriranje.poslednje() }
            runOnUiThread {
                proveraUToku = false
                if (isDestroyed) return@runOnUiThread
                val trenutna = versionName()
                ishod.onSuccess { izdanje ->
                    if (Azuriranje.novije(trenutna, izdanje.oznaka)) {
                        prikaziStanje(
                            "Update ${izdanje.oznaka} available, tap to install",
                            izdanje,
                        )
                    } else {
                        prikaziStanje("Up to date", null)
                    }
                }.onFailure { greska ->
                    prikaziStanje(
                        "Check failed: ${greska.message ?: "unknown error"}",
                        null,
                    )
                }
            }
        }.start()
    }

    private fun preuzmiIzdanje(izdanje: Azuriranje.Izdanje) {
        if (!Azuriranje.smeDaInstalira(this) || downloadRunning) return
        downloadRunning = true
        Thread {
            val result = runCatching { Azuriranje.preuzmi(applicationContext, izdanje.adresaApk) {} }
            runOnUiThread {
                downloadRunning = false
                if (isDestroyed) return@runOnUiThread
                result.onSuccess { pendingApk = it; maybeAutoUpdate() }
                    .onFailure { prikaziStanje("Download failed, tap to retry", izdanje) }
            }
        }.start()
    }

    /**
     * Istorija ide od ivice do ivice ekrana: obican spisak sa linijama izmedju
     * redova, bez zaobljenih dugmadi. Svih do 100 diktata je u stranici, pa se
     * do starijih dolazi obicnim skrolovanjem.
     */
    private fun istorija(): ViewGroup {
        historyRows = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                // Ponistava bocni razmak stranice (16 dp), da redovi dodju do ivice.
                marginStart = -dp(16)
                marginEnd = -dp(16)
                topMargin = dp(16)
            }
        }
        showHistory()
        return historyRows
    }

    private fun linija() = View(this).apply {
        setBackgroundColor(bojaTeme(com.google.android.material.R.attr.colorOutlineVariant))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1)
    }

    private fun showHistory() {
        if (!::historyRows.isInitialized) return
        historyRows.removeAllViews()
        val items = cfg.history()
        if (items.isEmpty()) {
            historyRows.addView(body(this, "No dictation yet.").apply {
                setPadding(dp(16), dp(12), dp(16), dp(12))
            })
            return
        }
        val talas = android.util.TypedValue().also {
            theme.resolveAttribute(android.R.attr.selectableItemBackground, it, true)
        }.resourceId
        historyRows.addView(linija())
        items.forEachIndexed { index, text ->
            val item = TextView(this).apply {
                this.text = (index + 1).toString() + ". " +
                    text.replace(Regex("\\s+"), " ").trim()
                setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_BodyLarge)
                gravity = Gravity.START or Gravity.CENTER_VERTICAL
                maxLines = 1
                ellipsize = TextUtils.TruncateAt.END
                minHeight = dp(52)
                setPadding(dp(16), 0, dp(16), 0)
                setBackgroundResource(talas)
                isClickable = true
                setOnClickListener { copyHistory(text) }
            }
            historyRows.addView(item, LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            ))
            historyRows.addView(linija())
        }
    }

    private fun copyHistory(text: String) {
        // Razmak na kraju, kao posle diktata: sledeca rec se inace zalepi za
        // nalepljen tekst. Isto radi i Mac.
        getSystemService(ClipboardManager::class.java).setPrimaryClip(
            ClipData.newPlainText("Diktat", text.trimEnd() + " ")
        )
        Toast.makeText(this, "Copied.", Toast.LENGTH_SHORT).show()
    }

    private fun dozvole(): ViewGroup {
        val (card, box) = card(this, "Dozvole")
        box.addView(
            body(
                this,
                "Kvačica znači da je stavka odobrena. Dugme i dalje radi, za slučaj da " +
                    "nešto hoćeš da promeniš.",
            )
        )
        dozvoleRows = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        box.addView(dozvoleRows)
        box.addView(
            body(
                this,
                "Bez Pristupačnosti diktat i dalje radi, ali tekst završi u clipboard-u " +
                    "pa ga lepiš ručno. Umesto bočnog tastera možeš izabrati Diktat kao " +
                    "Voice input; tada mikrofon na tastaturi radi isto.",
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
            addView(switch(
                this@MainActivity,
                "Upisuj tekst u aktivno polje tokom govora",
                cfg.geminiLiveInsert,
            ) { cfg.geminiLiveInsert = it })
            addView(body(
                this@MainActivity,
                "Privremeni tekst se tokom govora menja u aktivnom polju kada ono to podržava; " +
                    "potvrđeni delovi ostaju. Prikaz uz tajmer može biti isključen. " +
                    "Ako je uključena AI ispravka teksta, upis čeka kraj diktata. " +
                    "Potrebni su Pristupačnost i aktivno polje za unos.",
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

        box.addView(switch(this, "Utišaj zvuk dok snimam", cfg.utisajZvuk) {
            cfg.utisajZvuk = it
        })
        box.addView(switch(this, "Pauziraj muziku i video dok snimam", cfg.pauzirajPlejer) {
            cfg.pauzirajPlejer = it
        })
        box.addView(
            body(this, "Posle snimanja se zvuk vraća, a muzika nastavlja odakle je stala.")
        )

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

    /** Koji izbor odgovara podesavanjima; „bez" pobedjuje „zareze". */
    private fun interpunkcija() = when {
        cfg.stripPunctuation -> "bez"
        cfg.samoZarezi -> "zarezi"
        else -> "sva"
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
        lateinit var izborInterpunkcije: com.google.android.material.button.MaterialButtonToggleGroup
        lateinit var swKvacice: com.google.android.material.materialswitch.MaterialSwitch
        lateinit var swSkracenice: com.google.android.material.materialswitch.MaterialSwitch

        // Kvacica na „Pravilno" se IZVODI iz prekidaca ispod, ne pamti se zasebno:
        // inace bi rucno gasenje jednog od njih ostavilo nad-prekidac da laze.
        fun osvezi() {
            sinhronizujem = true
            swPravilno.isChecked = cfg.pravilno
            swMala.isChecked = cfg.lowercase
            val izabrano = INTERPUNKCIJA.indexOfFirst { it.first == interpunkcija() }
            izborInterpunkcije.check(izborInterpunkcije.getChildAt(izabrano).id)
            swKvacice.isChecked = cfg.asciiDiacritics
            swSkracenice.isChecked = cfg.abbreviations
            sinhronizujem = false
        }

        // Nad-prekidac iznad cetiri. Nije peto podesavanje nego precica: cetiri
        // klika za prelazak izmedju „kako sam izgovorio" i „pravopisno" su
        // cetiri prilike da se jedan zaboravi, pa tekst izadje na pola puta.
        swPravilno = switch(this, "Pravilno (gasi sve ispod)", cfg.pravilno) {
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
        box.addView(body(this, "Interpunkcija"))
        izborInterpunkcije = choice(this, INTERPUNKCIJA, interpunkcija()) { izbor ->
            if (!sinhronizujem) {
                cfg.stripPunctuation = izbor == "bez"
                cfg.samoZarezi = izbor == "zarezi"
                osvezi()
            }
        }
        box.addView(izborInterpunkcije)
        box.addView(
            body(
                this,
                "Zarezi i ?: tačke postaju zarezi, ostaju samo zarezi i upitnici. " +
                    "Bez: brojevi kao 3,5 i 10:30 ostaju celi.",
            )
        )
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
            })
        return card
    }

    private fun proba(): ViewGroup {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val (layout, edit) = field(this, "", lines = 4)
        layout.isHintEnabled = false
        edit.contentDescription = "Dictation text"
        box.addView(layout)
        dictationStart = button(this, "Record") {
            edit.requestFocus()
            dictationCommand(if (DictationService.isRecording) DictationService.ACTION_STOP else DictationService.ACTION_START)
        }
        box.addView(dictationStart)
        return box
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

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        showPermissions()
    }

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
