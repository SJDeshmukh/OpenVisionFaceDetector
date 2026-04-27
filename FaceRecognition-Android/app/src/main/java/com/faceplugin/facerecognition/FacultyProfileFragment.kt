package com.faceplugin.facerecognition

import android.content.Context
import android.content.Intent
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
        val root = LinearLayout(requireContext()).apply {
            orientation  = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            setPadding(40, 120, 40, 40)
        }

        val prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val name  = prefs.getString("faculty_display_name", null) ?: prefs.getString("username", "Faculty")

        TextView(requireContext()).apply {
            text     = "Profile"
            textSize = 20f
            setTextColor(android.graphics.Color.WHITE)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        }.also { root.addView(it) }

        TextView(requireContext()).apply {
            text     = "Logged in as: $name\nRole: Faculty"
            textSize = 14f
            setTextColor(0xCCFFFFFFu.toInt())
            setPadding(0, 16, 0, 32)
        }.also { root.addView(it) }

        Button(requireContext()).apply {
            text = "Logout"
            setOnClickListener { logout() }
        }.also { root.addView(it) }

        return root
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
