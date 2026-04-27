package com.faceplugin.facerecognition

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class FacultyHistoryFragment : Fragment() {

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        val root = LinearLayout(requireContext()).apply {
            orientation   = LinearLayout.VERTICAL
            layoutParams  = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            setPadding(40, 120, 40, 40)
        }

        val title = TextView(requireContext()).apply {
            text      = "Lecture History"
            textSize  = 20f
            setTextColor(android.graphics.Color.WHITE)
            typeface  = android.graphics.Typeface.DEFAULT_BOLD
        }
        root.addView(title)

        val sub = TextView(requireContext()).apply {
            text     = "Loading…"
            textSize = 13f
            setTextColor(0x99FFFFFFu.toInt())
            setPadding(0, 16, 0, 0)
        }
        root.addView(sub)

        RetrofitClient.getService().getFacultyLectures("", "", "").enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                val arr   = resp.body()?.getAsJsonArray("lectures")
                val count = arr?.size() ?: 0
                activity?.runOnUiThread {
                    sub.text = if (count > 0) "$count lecture(s) found.\nTap a session on the Home tab to see details."
                               else "No lecture sessions recorded yet."
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                activity?.runOnUiThread {
                    sub.text = "Could not load history — check connection."
                }
            }
        })
        return root
    }
}
