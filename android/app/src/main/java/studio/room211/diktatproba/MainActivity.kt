package studio.room211.diktatproba

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * Ekran za probu. Ne radi nista pametno — samo objasni sta se proverava i
 * odvede na prava mesta u podesavanjima, jer su ta mesta na Samsungu zakopana.
 */
class MainActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }

        root.addView(heading("Diktat — proba mehanizama"))
        root.addView(
            body(
                "Aplikacija ništa ne prepoznaje. Prijavljena je na četiri mesta " +
                    "u sistemu i sa svakog vraća svoj marker, pa se po tekstu " +
                    "koji stigne tačno zna šta na ovom telefonu radi."
            )
        )

        root.addView(heading("A — mikrofon na postojećoj tastaturi"))
        root.addView(
            body(
                "Izaberi „Diktat proba (A)\" kao Voice input, pa u polju ispod " +
                    "pritisni mikrofon na tastaturi.\n\n" +
                    "Ako upiše „proba a" + "\" — ovo je pobednik: nema nove " +
                    "tastature ni posebnih dozvola."
            )
        )
        root.addView(
            action("Otvori podešavanja za Voice input") {
                openAny(
                    Settings.ACTION_VOICE_INPUT_SETTINGS,
                    Settings.ACTION_INPUT_METHOD_SETTINGS,
                )
            }
        )
        root.addView(TextView(this).apply {
            text = "Polje za probu:"
            setPadding(0, 24, 0, 8)
        })
        root.addView(EditText(this).apply {
            hint = "ovde pritisni mikrofon na tastaturi"
            inputType = InputType.TYPE_CLASS_TEXT
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        })

        root.addView(heading("B — zasebna tastatura"))
        root.addView(
            body(
                "Uključi „Diktat proba (B)\" u listi tastatura, pa se prebaci na " +
                    "nju u polju iznad. Ima jedno dugme; treba da upiše „proba b\".\n\n" +
                    "Ovo sigurno radi — pitanje je samo koliko smeta prebacivanje."
            )
        )
        root.addView(
            action("Otvori listu tastatura") {
                openAny(Settings.ACTION_INPUT_METHOD_SETTINGS)
            }
        )

        root.addView(heading("C — bočni taster (asistent)"))
        root.addView(
            body(
                "Postavi „Diktat proba\" kao digitalni asistent, pa zadrži bočni " +
                    "taster. Treba da iskoči poruka „proba c\".\n\n" +
                    "Obrati pažnju na jednu stvar: da li se pri tome zatvorila " +
                    "tastatura i izgubio kursor iz polja u kome si bio."
            )
        )
        root.addView(
            action("Otvori podrazumevane aplikacije") {
                openAny(
                    "android.settings.VOICE_INPUT_SETTINGS",
                    Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS,
                    Settings.ACTION_SETTINGS,
                )
            }
        )

        root.addView(heading("E — pločica u brzim podešavanjima"))
        root.addView(
            body(
                "Spusti zavesu, uredi pločice i dodaj „Diktat proba (E)\". " +
                    "Tap treba da spusti „proba e\" u clipboard."
            )
        )

        root.addView(heading("Šta mi javi"))
        root.addView(
            body(
                "Za svako od A, B, C i E samo: radi ili ne radi. Ako ne radi, " +
                    "da li se uopšte pojavljuje u odgovarajućem spisku.\n\n" +
                    "Na osnovu toga biramo koji način dovršavamo."
            )
        )

        setContentView(ScrollView(this).apply { addView(root) })
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

    /** Probaj redom — Samsung neke od ovih ekrana nema pod standardnim imenom. */
    private fun openAny(vararg actions: String) {
        for (action in actions) {
            try {
                startActivity(Intent(action))
                return
            } catch (_: Exception) {
                // sledeci
            }
        }
        Toast.makeText(this, "Ne mogu da otvorim taj ekran — potraži ručno.", Toast.LENGTH_LONG)
            .show()
    }
}
