package studio.room211.diktat

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {

    private lateinit var cfg: Config
    private lateinit var statusLine: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        cfg = Config(this)
        askForMicrophone()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 64)
        }

        root.addView(heading("Diktat"))
        root.addView(
            body(
                "Zadrži bočni taster, pričaj, pa ga zadrži ponovo. Tekst se upiše " +
                    "tamo gde ti je kursor.\n\nTajmer gore desno: zeleno snima, " +
                    "crveno od 15s, žuto dok se obrađuje. Staje na 30s."
            )
        )

        root.addView(heading("Dozvole"))
        statusLine = body("")
        root.addView(statusLine)
        root.addView(action("Postavi kao digitalnog asistenta") {
            openAny("android.settings.VOICE_INPUT_SETTINGS",
                Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS, Settings.ACTION_SETTINGS)
        })
        root.addView(action("Dozvoli prikaz preko drugih aplikacija") {
            runCatching {
                startActivity(
                    Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:$packageName"),
                    )
                )
            }
        })
        root.addView(action("Uključi unos teksta (Pristupačnost)") {
            openAny(Settings.ACTION_ACCESSIBILITY_SETTINGS)
        })
        root.addView(
            body(
                "Bez Pristupačnosti tekst ne može da se upiše u polje — tada " +
                    "završi u clipboard-u pa ga lepiš ručno."
            )
        )

        root.addView(heading("Mikrofon na tastaturi"))
        root.addView(
            body(
                "Umesto bočnog tastera možeš izabrati „Diktat\" kao Voice input; " +
                    "tada mikrofon na Samsung tastaturi radi isto, bez Pristupačnosti."
            )
        )
        root.addView(action("Otvori Voice input") {
            openAny(Settings.ACTION_VOICE_INPUT_SETTINGS, Settings.ACTION_INPUT_METHOD_SETTINGS)
        })

        root.addView(heading("Obrada teksta"))
        root.addView(toggle("Sve malim slovima", cfg.lowercase) { cfg.lowercase = it })
        root.addView(toggle("Bez interpunkcije", cfg.stripPunctuation) { cfg.stripPunctuation = it })
        root.addView(toggle("Razmak na kraju", cfg.trailingSpace) { cfg.trailingSpace = it })
        root.addView(toggle("Maskiraj psovke zvezdicama", cfg.profanityFilter) {
            cfg.profanityFilter = it
        })
        root.addView(toggle("Bez kvačica (č ć ž š đ → c c z s dj)", cfg.asciiDiacritics) {
            cfg.asciiDiacritics = it
        })

        root.addView(heading("Skraćenice"))
        root.addView(toggle("Skraćuj česte fraze", cfg.abbreviations) { cfg.abbreviations = it })
        root.addView(body("Jedno pravilo po redu, oblik  fraza=skraćenica"))
        root.addView(EditText(this).apply {
            setText(cfg.abbreviationRules)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            setLines(6)
            gravity = android.view.Gravity.TOP or android.view.Gravity.START
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
            setOnFocusChangeListener { _, focused ->
                if (!focused) cfg.abbreviationRules = text.toString()
            }
        })
        root.addView(action("Vrati podrazumevane skraćenice") {
            cfg.abbreviationRules = Abbreviations.defaultText()
            recreate()
        })

        root.addView(heading("Jezik"))
        root.addView(EditText(this).apply {
            setText(cfg.language)
            inputType = InputType.TYPE_CLASS_TEXT
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
            setOnFocusChangeListener { _, focused ->
                if (!focused) cfg.language = text.toString().trim().ifBlank { "sr-RS" }
            }
        })
        root.addView(body("sr-RS, en-US, hr-HR…"))

        root.addView(heading("Proba"))
        root.addView(EditText(this).apply {
            hint = "ovde probaj diktat"
            inputType = InputType.TYPE_CLASS_TEXT
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
        })

        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onResume() {
        super.onResume()
        val ready = InsertService.isRunning
        title = if (ready) "Diktat — spreman" else "Diktat"
        statusLine.text = if (ready) {
            "Pristupačnost je uključena — tekst se upisuje gde je kursor."
        } else {
            "Pristupačnost NIJE uključena — tekst će završiti u clipboard-u."
        }
    }

    private fun askForMicrophone() {
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

    private fun heading(text: String) = TextView(this).apply {
        this.text = text
        textSize = 17f
        setTextColor(Color.BLACK)
        setPadding(0, 40, 0, 8)
    }

    private fun body(text: String) = TextView(this).apply {
        this.text = text
        textSize = 14f
        setLineSpacing(0f, 1.15f)
    }

    private fun action(label: String, run: () -> Unit) = Button(this).apply {
        text = label
        setOnClickListener { run() }
    }

    private fun toggle(label: String, initial: Boolean, onChange: (Boolean) -> Unit) =
        Switch(this).apply {
            text = label
            isChecked = initial
            setPadding(0, 16, 0, 16)
            setOnCheckedChangeListener { _, checked -> onChange(checked) }
        }

    private fun openAny(vararg actions: String) {
        for (action in actions) {
            runCatching { startActivity(Intent(action)); return }
        }
        Toast.makeText(this, "Ne mogu da otvorim taj ekran — potraži ručno.", Toast.LENGTH_LONG)
            .show()
    }
}
