package studio.room211.diktat

import android.Manifest
import android.content.Intent
import android.graphics.Rect
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
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
    private lateinit var polishLine: TextView
    private lateinit var probaLine: TextView
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

        // Grupisano po pitanju na koje odgovaras, a ne po tome kad je sta
        // nastalo: Snimanje (kako), Tekst (kako izgleda), AI (sta model radi).
        root.addView(dozvole())
        root.addView(rezim())
        root.addView(ai())
        root.addView(tekst())
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
        box.addView(switch(this, "Ne ostavljaj tekst u clipboard-u", cfg.restoreClipboard) {
            cfg.restoreClipboard = it
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
        box.addView(switch(this, "Snimaj samo kad ima polja za unos", cfg.requireInputField) {
            cfg.requireInputField = it
        })
        return card
    }

    private fun ai(): ViewGroup {
        // Sve sto model radi je na jednom mestu, kao i u meniju na Mac-u. Razlika
        // u trajanju se ne gubi: stoji uz sam prekidac koji je uzrokuje.
        val (card, box) = card(this, "AI")
        val alati = mutableListOf<View>()

        box.addView(switch(this, "Uključi AI obradu", cfg.polish) {
            cfg.polish = it
            setBranchEnabled(alati, it)
        })
        box.addView(
            body(
                this,
                "Ceo diktat se sačeka pa jednim pozivom ode modelu; dok se čeka, " +
                    "pokazivač pokazuje AI. Radi samo uz API ključ (Google AI " +
                    "Studio), koji ostaje sačuvan i posle nadogradnje.",
            )
        )

        val slusa = indent(this, switch(this, "Sluša snimak (preciznije)", cfg.audioCheck) {
            cfg.audioCheck = it
        })
        alati.add(slusa)
        box.addView(slusa)
        box.addView(
            indent(this, body(this, "Model dobija i sam zvuk, pa ispravlja ono što je " +
                "prepoznavanje pogrešno čulo — najviše skraćenice i strane nazive " +
                "(\u201EAI\u201C ume da postane \u201Epa\u201C).\n\n" +
                "Ovo je najsporiji deo: snimak ide drugi put, pa se za 20s diktata " +
                "čeka oko 10s; ostalo traje oko sekunde. Čuva se najviše 120s zvuka " +
                "po diktatu — preko toga se prepis više ne proverava."))
        )

        val sredi = indent(this, switch(this, "Sredi tekst (tačke i velika slova)",
            cfg.polishTidy) { cfg.textStyle = if (it) "written" else "spoken" })
        alati.add(sredi)
        box.addView(sredi)
        box.addView(
            indent(this, body(this, "Dodaje tačke i velika slova, i usput sređuje reči " +
                "koje se gramatički ne slažu. Isključeno: tekst ostaje malim slovima " +
                "i bez interpunkcije, kako je izgovoren."))
        )

        val pasusi = indent(this, switch(this, "Podeli na pasuse", cfg.polishParagraphs) {
            cfg.polishParagraphs = it
        })
        alati.add(pasusi)
        box.addView(pasusi)

        val tacke = indent(this, switch(this, "Sažmi u tačke", cfg.polishBullets) {
            cfg.polishBullets = it
        })
        alati.add(tacke)
        box.addView(tacke)
        box.addView(
            indent(this, body(this, "Preuređuje izgovoreno u spisak: jedna misao po " +
                "tački, kratke izjavne rečenice, bez poštapalica. Činjenice i brojevi " +
                "ostaju. Isključuje podelu na pasuse."))
        )

        val ponavljanja = indent(this, switch(this, "Izbaci ponavljanja", cfg.polishDedupe) {
            cfg.polishDedupe = it
        })
        alati.add(ponavljanja)
        box.addView(ponavljanja)
        box.addView(
            indent(this, body(this, "Kad se ista reč ili fraza izgovori dvaput zaredom " +
                "— jer se čovek ispravlja — ostaje jednom. Namerno ponavljanje " +
                "(\u201Evrlo, vrlo dugo\u201C) se ne dira."))
        )

        val (jezik, _) = field(this, "Jezik izlaza (prazno = bez prevoda)", cfg.outputLanguage) {
            cfg.outputLanguage = it
        }
        alati.add(jezik)
        box.addView(indent(this, jezik))
        box.addView(
            indent(this, body(this, "Slobodan opis, ne spisak: \u201Emakedonski\u201C, " +
                "\u201Eengleski formalno\u201C, pa i \u201Epola makedonski pola " +
                "srpski\u201C. Značenje ostaje isto."))
        )

        polishLine = indent(this, body(this, ""))
        box.addView(polishLine)

        box.addView(body(this, "Napredno"))
        val (kljuc, _) = field(this, "API ključ", cfg.polishApiKey) { cfg.polishApiKey = it }
        box.addView(kljuc)
        val (model, _) = field(this, "Model (prazno = ${Polish.DEFAULT_MODEL})", cfg.polishModel) {
            cfg.polishModel = it
        }
        box.addView(model)
        val (pojmovi, _) = field(this, "Pojmovi koje često izgovaram", cfg.vocabulary) {
            cfg.vocabulary = it
        }
        box.addView(pojmovi)
        box.addView(
            body(this, "Skraćenice i nazivi koje prepoznavanje stalno pogreši. Idu " +
                "modelu uz snimak, odvojeni zarezom.")
        )

        setBranchEnabled(alati, cfg.polish)
        return card
    }

    private fun tekst(): ViewGroup {
        // Ovo radi nas kod, bez modela i bez kljuca — zato je odvojeno od AI
        // kartice i radi i kad je AI iskljucen.
        val (card, box) = card(this, "Tekst")
        box.addView(switch(this, "Bez kvačica (č ć ž š đ → c c z s dj)", cfg.asciiDiacritics) {
            cfg.asciiDiacritics = it
        })
        // Prekidac je obrnut od podesavanja: ukljucen znaci pFilter=0, sto je i
        // podrazumevano. Da pise "maskiraj", jedini bi stajao iskljucen.
        box.addView(switch(this, "Ne maskiraj psovke zvezdicama", !cfg.profanityFilter) {
            cfg.profanityFilter = !it
        })

        box.addView(switch(this, "Skraćuj česte fraze", cfg.abbreviations) {
            cfg.abbreviations = it
        })
        box.addView(
            body(
                this,
                "Pravilo je \u201Efraza=skraćenica\u201C, jedno po redu. Ako skraćenica " +
                    "počinje sa \u201E<\u201C, zalepi se za prethodnu reč " +
                    "(minuta=<min \u2192 15min).",
            )
        )
        val (pravila, _) = field(
            this, "Pravila", cfg.abbreviationRules, lines = 6, mono = true,
        ) { cfg.abbreviationRules = it }
        box.addView(pravila)
        val (proba, probaEdit) = field(this, "Proba pravila", "")
        box.addView(proba)
        probaLine = body(this, "")
        box.addView(probaLine)
        probaEdit.addTextChangedListener(object : android.text.TextWatcher {
            override fun afterTextChanged(sadrzaj: android.text.Editable?) {
                val ulaz = sadrzaj?.toString() ?: ""
                probaLine.text = if (ulaz.isBlank()) "" else TextPolish.apply(ulaz, cfg).trim()
            }
            override fun beforeTextChanged(c: CharSequence?, a: Int, b: Int, d: Int) {}
            override fun onTextChanged(c: CharSequence?, a: Int, b: Int, d: Int) {}
        })
        box.addView(button(this, "Vrati podrazumevane skraćenice") {
            cfg.abbreviationRules = Abbreviations.defaultText()
            recreate()
        })
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
