package com.faceplugin.facerecognition

import android.content.Context
import android.content.Intent
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment

class FacultyProfileFragment : Fragment() {

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        val ctx   = requireContext()
        val prefs = ctx.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val name  = prefs.getString("faculty_display_name", null) ?: prefs.getString("username", "Faculty")
        val isLight = prefs.getBoolean("theme_light", false)

        val root = LinearLayout(ctx).apply {
            orientation  = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            setPadding(40, 120, 40, 40)
        }

        // Title
        TextView(ctx).apply {
            text     = "Profile"
            textSize = 22f
            setTextColor(resolveTextColor(ctx))
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        }.also { root.addView(it) }

        TextView(ctx).apply {
            text     = "Logged in as: $name\nRole: Faculty"
            textSize = 14f
            setTextColor(resolveSubtextColor(ctx))
            setPadding(0, 16, 0, 32)
        }.also { root.addView(it) }

        // ── Theme toggle ──────────────────────────────────────────────────────
        val sectionLabel = TextView(ctx).apply {
            text     = "Appearance"
            textSize = 13f
            setTextColor(resolveSubtextColor(ctx))
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        }
        root.addView(sectionLabel)

        val toggleRow = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity     = android.view.Gravity.CENTER_VERTICAL
            setPadding(0, 12, 0, 28)
        }

        val dp = ctx.resources.displayMetrics.density.toInt()
        val btnSize = 52 * dp

        fun makeThemeBtn(icon: String, label: String, active: Boolean, onClick: () -> Unit): LinearLayout {
            val bgColor = if (active) 0xFF7C3AFF.toInt() else 0x22FFFFFF.toInt()
            val textColor = if (active) 0xFFFFFFFF.toInt() else resolveSubtextColor(ctx)
            return LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                gravity     = android.view.Gravity.CENTER
                layoutParams = LinearLayout.LayoutParams(btnSize, btnSize).also { it.setMargins(0, 0, 16 * dp, 0) }
                background = GradientDrawable().apply {
                    shape = GradientDrawable.RECTANGLE
                    cornerRadius = 12f * dp
                    setColor(bgColor)
                }
                isClickable = true; isFocusable = true
                setOnClickListener { onClick() }
                addView(TextView(ctx).apply {
                    text = icon; textSize = 22f; gravity = android.view.Gravity.CENTER
                })
                addView(TextView(ctx).apply {
                    text = label; textSize = 10f; gravity = android.view.Gravity.CENTER
                    setTextColor(textColor)
                })
            }
        }

        val btnDark = makeThemeBtn("🌙", "Dark", !isLight) {
            applyTheme(false)
        }
        val btnLight = makeThemeBtn("☀", "Light", isLight) {
            applyTheme(true)
        }
        toggleRow.addView(btnDark)
        toggleRow.addView(btnLight)
        root.addView(toggleRow)

        // ── Logout ─────────────────────────────────────────────────────────────
        Button(ctx).apply {
            text = "Logout"
            setTextColor(0xFFFFFFFF.toInt())
            backgroundTintList = android.content.res.ColorStateList.valueOf(0xFFD32F2F.toInt())
            setOnClickListener { logout() }
        }.also { root.addView(it) }

        return root
    }

    private fun applyTheme(light: Boolean) {
        val ctx = requireContext()
        ctx.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
            .edit().putBoolean("theme_light", light).apply()
        requireActivity().recreate()
    }

    private fun resolveTextColor(ctx: Context): Int {
        val isLight = ctx.getSharedPreferences("app_prefs", Context.MODE_PRIVATE).getBoolean("theme_light", false)
        return if (isLight) 0xFF1A1A2E.toInt() else 0xFFFFFFFF.toInt()
    }

    private fun resolveSubtextColor(ctx: Context): Int {
        val isLight = ctx.getSharedPreferences("app_prefs", Context.MODE_PRIVATE).getBoolean("theme_light", false)
        return if (isLight) 0xFF4A4A6A.toInt() else 0xCCFFFFFF.toInt()
    }

    private fun logout() {
        val prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        prefs.edit()
            .remove("token").remove("role").remove("username")
            .remove("faculty_display_name").remove("vendor_id")
            .apply()
        FacultySessionManager.clearSession(requireContext())
        com.faceplugin.facerecognition.api.RetrofitClient.setAuthToken("")

        val intent = Intent(requireContext(), SplashActivity::class.java)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        startActivity(intent)
        requireActivity().finish()
    }
}
