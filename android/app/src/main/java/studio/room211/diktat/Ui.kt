package studio.room211.diktat

import android.content.Context
import android.graphics.Typeface
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout

/**
 * Gradivni elementi ekrana.
 *
 * Podesavanja su grupisana u kartice: bez toga je ekran bio jedan dugacak
 * spisak u kome se nije videlo sta ide uz sta.
 */
object Ui {

    fun Context.dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    /** Kartica sa naslovom; sadrzaj se dodaje u vraceni LinearLayout. */
    fun card(context: Context, title: String): Pair<MaterialCardView, LinearLayout> {
        val inner = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            val p = context.dp(18)
            setPadding(p, context.dp(14), p, context.dp(16))
        }
        inner.addView(TextView(context).apply {
            text = title
            setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_TitleMedium)
            setPadding(0, 0, 0, context.dp(6))
        })

        val card = MaterialCardView(context).apply {
            radius = context.dp(20).toFloat()
            cardElevation = 0f
            setCardBackgroundColor(themeColor(context, com.google.android.material.R.attr.colorSurfaceContainer))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = context.dp(12) }
            addView(inner)
        }
        return card to inner
    }

    fun body(context: Context, text: String) = TextView(context).apply {
        this.text = text
        setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_BodyMedium)
        alpha = 0.75f
        setPadding(0, context.dp(2), 0, context.dp(6))
    }

    fun switch(
        context: Context,
        label: String,
        initial: Boolean,
        onChange: (Boolean) -> Unit,
    ) = MaterialSwitch(context).apply {
        text = label
        isChecked = initial
        minHeight = context.dp(48)          // udoban cilj za prst
        setPadding(0, context.dp(4), 0, context.dp(4))
        setOnCheckedChangeListener { _, checked -> onChange(checked) }
    }

    fun button(context: Context, label: String, onClick: () -> Unit) =
        MaterialButton(
            context, null,
            com.google.android.material.R.attr.materialButtonOutlinedStyle,
        ).apply {
            text = label
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = context.dp(4) }
        }

    /** Polje sa lebdecom oznakom; `lines > 1` pravi visestruko polje. */
    fun field(
        context: Context,
        hint: String,
        value: String = "",
        lines: Int = 1,
        mono: Boolean = false,
        onChange: ((String) -> Unit)? = null,
    ): Pair<TextInputLayout, TextInputEditText> {
        val edit = TextInputEditText(context).apply {
            setText(value)
            inputType = if (lines > 1) {
                InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            } else {
                InputType.TYPE_CLASS_TEXT
            }
            if (lines > 1) {
                setLines(lines)
                gravity = Gravity.TOP or Gravity.START
                isVerticalScrollBarEnabled = true
                scrollBarStyle = View.SCROLLBARS_INSIDE_OVERLAY
                // Pokret se preuzima SAMO ako tekst prelazi visinu polja —
                // bezuslovno preuzimanje zaglavljuje celu stranicu.
                setOnTouchListener { view, event ->
                    val tv = view as TextView
                    val visible = view.height - view.paddingTop - view.paddingBottom
                    view.parent?.parent?.requestDisallowInterceptTouchEvent(
                        (tv.layout?.height ?: 0) > visible
                    )
                    if (event.actionMasked == MotionEvent.ACTION_UP ||
                        event.actionMasked == MotionEvent.ACTION_CANCEL
                    ) {
                        view.parent?.parent?.requestDisallowInterceptTouchEvent(false)
                    }
                    false
                }
            }
            if (mono) {
                typeface = Typeface.MONOSPACE
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            }
            onChange?.let { cb ->
                addTextChangedListener(object : TextWatcher {
                    override fun afterTextChanged(s: Editable?) = cb(s?.toString() ?: "")
                    override fun beforeTextChanged(c: CharSequence?, a: Int, b: Int, d: Int) {}
                    override fun onTextChanged(c: CharSequence?, a: Int, b: Int, d: Int) {}
                })
            }
        }

        val layout = TextInputLayout(
            context, null,
            com.google.android.material.R.attr.textInputOutlinedStyle,
        ).apply {
            this.hint = hint
            val r = context.dp(14).toFloat()
            setBoxCornerRadii(r, r, r, r)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = context.dp(6) }
            addView(edit)
        }
        return layout to edit
    }

    private fun themeColor(context: Context, attr: Int): Int {
        val value = TypedValue()
        context.theme.resolveAttribute(attr, value, true)
        return value.data
    }
}
