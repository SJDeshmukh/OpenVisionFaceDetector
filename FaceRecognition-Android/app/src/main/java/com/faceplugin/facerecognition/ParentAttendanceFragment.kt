package com.faceplugin.facerecognition

import android.app.DatePickerDialog
import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import io.socket.client.IO
import io.socket.client.Socket
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.*

class ParentAttendanceFragment : Fragment() {

    private var mSocket: Socket? = null
    private lateinit var root: View

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        root = inflater.inflate(R.layout.fragment_parent_attendance, container, false)
        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val prefs = requireActivity().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val savedStudentId = prefs.getString("student_id", "") ?: ""
        val savedMobile = prefs.getString("parent_mobile_number", "") ?: ""
        val etDate = root.findViewById<EditText>(R.id.et_date)

        root.findViewById<TextView>(R.id.tv_parent_student_meta).text =
            "Student ID: ${if (savedStudentId.isBlank()) "-" else savedStudentId}"
        root.findViewById<TextView>(R.id.tv_parent_parent_meta).text =
            "Mobile: ${if (savedMobile.isBlank()) "-" else savedMobile}"

        if (etDate.text.toString().trim().isEmpty()) {
            etDate.setText(SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Calendar.getInstance().time))
        }

        etDate.setOnClickListener { showDatePicker() }

        root.findViewById<Button>(R.id.btn_filter_date).setOnClickListener {
            fetchStudentDay()
        }

        if (savedStudentId.isNotEmpty()) {
            joinSocket(savedStudentId)
        }

        fetchStudentDay()
    }

    private fun showDatePicker() {
        val etDate = root.findViewById<EditText>(R.id.et_date)
        val current = Calendar.getInstance()
        try {
            val txt = etDate.text.toString().trim()
            if (txt.matches(Regex("\\d{4}-\\d{2}-\\d{2}"))) {
                val parts = txt.split("-")
                current.set(parts[0].toInt(), parts[1].toInt() - 1, parts[2].toInt())
            }
        } catch (_: Exception) {}

        DatePickerDialog(
            requireContext(),
            { _, year, month, dayOfMonth ->
                val m = (month + 1).toString().padStart(2, '0')
                val d = dayOfMonth.toString().padStart(2, '0')
                etDate.setText("$year-$m-$d")
                fetchStudentDay()
            },
            current.get(Calendar.YEAR),
            current.get(Calendar.MONTH),
            current.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun formatTime(ts: String?): String {
        if (ts.isNullOrBlank()) return "-"
        val t = ts.trim()
        return try {
            if (t.contains("T")) {
                val parts = t.split("T")
                if (parts.size >= 2) parts[1].take(5) else t
            } else if (t.contains(" ")) {
                val parts = t.split(" ")
                if (parts.size >= 2) parts[1].take(5) else t
            } else {
                t
            }
        } catch (_: Exception) {
            t
        }
    }

    private fun createHistoryCard(status: String, timestamp: String, activity: String, place: String): LinearLayout {
        val card = LinearLayout(requireContext())
        card.orientation = LinearLayout.VERTICAL
        card.setBackgroundResource(R.drawable.bg_input_field)
        val pad = (14 * resources.displayMetrics.density).toInt()
        card.setPadding(pad, pad, pad, pad)
        val lp = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        )
        lp.marginEnd = (12 * resources.displayMetrics.density).toInt()
        lp.bottomMargin = (10 * resources.displayMetrics.density).toInt()
        card.layoutParams = lp

        val label = if (status == "CHECK_IN") "Checked In" else "Checked Out"
        val time = formatTime(timestamp)
        val day = try { if (timestamp.contains(" ")) timestamp.split(" ").firstOrNull() ?: "" else "" } catch (_: Exception) { "" }
        val placeLabel = if (place.isNotBlank()) place else ""
        val subtitle = listOf(label, day, activity, placeLabel).filter { it.isNotBlank() }.joinToString(" • ")

        val tvTime = TextView(requireContext())
        tvTime.setTextColor(resources.getColor(R.color.vision_text_primary, null))
        tvTime.textSize = 22f
        tvTime.setTypeface(tvTime.typeface, android.graphics.Typeface.BOLD)
        tvTime.text = if (time == "-") "--:--" else time

        val tvSub = TextView(requireContext())
        tvSub.setTextColor(resources.getColor(R.color.vision_text_secondary, null))
        tvSub.textSize = 12f
        tvSub.text = if (subtitle.isBlank()) " " else subtitle

        card.addView(tvTime)
        card.addView(tvSub)
        return card
    }

    private fun fetchStudentDay() {
        if (!isAdded) return
        val dateText = root.findViewById<EditText>(R.id.et_date).text.toString().trim()
        val dateParam = if (dateText.isNotEmpty()) dateText else null

        RetrofitClient.getService().getParentStudentDay(dateParam).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                if (response.code() == 401 || response.code() == 403) {
                    Toast.makeText(context, "Session expired. Please login again.", Toast.LENGTH_LONG).show()
                    (activity as? ParentActivity)?.performLogout()
                    return
                }

                if (!response.isSuccessful || response.body() == null) {
                    Toast.makeText(context, "Failed to load student details", Toast.LENGTH_SHORT).show()
                    return
                }

                val prefs = requireActivity().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
                val savedMobile = prefs.getString("parent_mobile_number", "") ?: ""

                val resBody = response.body()!!
                val studentObj = try { resBody.getAsJsonObject("student") } catch (_: Exception) { null }
                val studentName = try { studentObj?.get("name")?.asString } catch (_: Exception) { null }
                val studentNum = try { studentObj?.get("student_number")?.asString } catch (_: Exception) { null }
                val lastStatus = try { resBody.get("last_status")?.asString } catch (_: Exception) { null }
                val date = try { resBody.get("date")?.asString } catch (_: Exception) { dateText }

                val checkIn = try { resBody.get("check_in")?.asString } catch (_: Exception) { null }
                val checkOut = try { resBody.get("check_out")?.asString } catch (_: Exception) { null }

                root.findViewById<TextView>(R.id.tv_parent_student_name).text = studentName ?: "Student"
                root.findViewById<TextView>(R.id.tv_parent_student_meta).text =
                    "Student ID: ${studentNum ?: "-"}"
                root.findViewById<TextView>(R.id.tv_parent_parent_meta).text =
                    "Mobile: ${if (savedMobile.isBlank()) "-" else savedMobile}"

                val checkInTime = formatTime(checkIn)
                val checkOutTime = formatTime(checkOut)
                root.findViewById<TextView>(R.id.tv_card_checkin_time).text = if (checkInTime == "-") "--:--" else checkInTime
                root.findViewById<TextView>(R.id.tv_card_checkout_time).text = if (checkOutTime == "-") "--:--" else checkOutTime
                root.findViewById<TextView>(R.id.tv_card_checkin_hint).text = if (checkInTime == "-") "No check-in" else "Checked in"
                root.findViewById<TextView>(R.id.tv_card_checkout_hint).text = if (checkOutTime == "-") "No check-out" else "Checked out"

                root.findViewById<TextView>(R.id.tv_parent_day_summary).text = "Date: ${date ?: "-"} • Status: ${lastStatus ?: "-"}"

                val list = try { resBody.getAsJsonArray("attendance") } catch (_: Exception) { null }
                val history = root.findViewById<LinearLayout>(R.id.parent_history_container)
                history.removeAllViews()

                if (list != null) {
                    try {
                        var maxId = -1
                        for (el in list) {
                            val obj = el.asJsonObject
                            val rid = try { obj.get("id")?.asInt ?: -1 } catch (_: Exception) { -1 }
                            if (rid > maxId) maxId = rid
                        }
                        if (maxId > 0) {
                            prefs.edit().putInt("parent_last_attendance_id", maxId).apply()
                        }
                    } catch (_: Exception) {}

                    try {
                        for (i in 0 until list.size()) {
                            val obj = list[i].asJsonObject
                            val status = try { obj.get("status")?.asString ?: "" } catch (_: Exception) { "" }
                            if (status != "CHECK_IN" && status != "CHECK_OUT") continue
                            val ts = try { obj.get("timestamp")?.asString ?: "" } catch (_: Exception) { "" }
                            val activityStr = try { obj.get("activity")?.asString ?: "" } catch (_: Exception) { "" }
                            val place = try {
                                val dn = obj.get("device_name")?.asString
                                if (!dn.isNullOrBlank()) dn else obj.get("place")?.asString ?: ""
                            } catch (_: Exception) { "" }
                            history.addView(createHistoryCard(status, ts, activityStr, place))
                        }
                    } catch (_: Exception) {}
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (isAdded) {
                    Toast.makeText(context, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            }
        })
    }

    private fun joinSocket(studentNumber: String) {
        try {
            val prefs = requireActivity().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
            val serverUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
            val options = IO.Options()
            options.reconnection = true
            mSocket = IO.socket(serverUrl, options)
            mSocket?.connect()
            val data = org.json.JSONObject()
            data.put("student_number", studentNumber)
            mSocket?.emit("join_student_number", data)
            mSocket?.on("student_attendance") { args ->
                activity?.runOnUiThread {
                    if (!isAdded) return@runOnUiThread
                    try {
                        val obj = args[0] as org.json.JSONObject
                        val n = obj.optString("name")
                        val s = obj.optString("status")
                        val ts = obj.optString("timestamp")
                        val ac = obj.optString("activity")
                        val place = obj.optString("device_name", obj.optString("place", ""))
                        if (s == "CHECK_IN" || s == "CHECK_OUT") {
                            val history = root.findViewById<LinearLayout>(R.id.parent_history_container)
                            history.addView(createHistoryCard(s, ts, ac, place), 0) // add to top
                            if (s == "CHECK_IN") {
                                val t = formatTime(ts)
                                root.findViewById<TextView>(R.id.tv_card_checkin_time).text = if (t == "-") "--:--" else t
                                root.findViewById<TextView>(R.id.tv_card_checkin_hint).text = if (t == "-") "No check-in" else "Checked in"
                            }
                            if (s == "CHECK_OUT") {
                                val t = formatTime(ts)
                                root.findViewById<TextView>(R.id.tv_card_checkout_time).text = if (t == "-") "--:--" else t
                                root.findViewById<TextView>(R.id.tv_card_checkout_hint).text = if (t == "-") "No check-out" else "Checked out"
                            }
                            try {
                                val dayText = root.findViewById<TextView>(R.id.tv_parent_day_summary).text.toString()
                                if (dayText.contains("Status:")) {
                                    val parts = dayText.split("Status:")
                                    root.findViewById<TextView>(R.id.tv_parent_day_summary).text = parts[0].trim() + " • Status: " + s
                                }
                            } catch (_: Exception) {}
                        }
                        showAttendanceFeedback(s)
                    } catch (_: Exception) {}
                }
            }
        } catch (_: Exception) {}
    }

    private fun showAttendanceFeedback(s: String) {
        val iv = root.findViewById<ImageView>(R.id.ivParentStatus)
        val tvWave = root.findViewById<TextView>(R.id.tvParentStatus)
        if (s == "CHECK_IN") {
            tvWave.visibility = View.GONE
            iv.setImageResource(android.R.drawable.checkbox_on_background)
            iv.setColorFilter(resources.getColor(android.R.color.holo_green_light, null))
            iv.visibility = View.VISIBLE
            iv.alpha = 1f
            iv.animate().alpha(0f).setDuration(800).withEndAction {
                iv.visibility = View.GONE
            }.start()
        } else {
            iv.visibility = View.GONE
            tvWave.text = "👋"
            tvWave.setTextColor(resources.getColor(android.R.color.holo_blue_light, null))
            tvWave.visibility = View.VISIBLE
            tvWave.alpha = 1f
            tvWave.animate().alpha(0f).setDuration(800).withEndAction {
                tvWave.visibility = View.GONE
            }.start()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        mSocket?.disconnect()
    }
}
