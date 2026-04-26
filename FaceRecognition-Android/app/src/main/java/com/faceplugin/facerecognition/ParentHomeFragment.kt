package com.faceplugin.facerecognition

import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.app.DatePickerDialog
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator
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

class ParentHomeFragment : Fragment() {

    private var mSocket: Socket? = null
    private lateinit var root: View
    private val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.US)

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        root = inflater.inflate(R.layout.fragment_parent_home, container, false)
        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        root.findViewById<TextView>(R.id.tv_home_greeting).text = greeting()
        animateCardsIn()
        startPulseDot()

        if (BuildConfig.IS_ATTENDX) {
            setupAttendXHome()
        } else {
            setupTapInXHome()
        }
    }

    // ── AttendX: lecture-only home, no check-in/out, no date filter ──────────

    private fun setupAttendXHome() {
        // Hide TapInX-only views
        root.findViewById<LinearLayout>(R.id.card_live_status).visibility = View.GONE
        root.findViewById<LinearLayout>(R.id.row_date_filter).visibility = View.GONE
        root.findViewById<TextView>(R.id.tv_home_recent_title).visibility = View.GONE
        root.findViewById<LinearLayout>(R.id.home_history_container).visibility = View.GONE

        // Show lecture section
        root.findViewById<LinearLayout>(R.id.layout_lectures_home).visibility = View.VISIBLE

        // Auto-load today's lectures
        val today = sdf.format(Calendar.getInstance().time)
        root.findViewById<EditText>(R.id.et_lec_start).setText(today)
        root.findViewById<EditText>(R.id.et_lec_end).setText(today)
        fetchTodayLectures()

        // Load student name/avatar
        loadStudentMeta()
    }

    private fun fetchTodayLectures() {
        if (!isAdded) return
        val today = sdf.format(Calendar.getInstance().time)
        RetrofitClient.getService().getParentLectureAttendance(today, today)
            .enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                    if (!isAdded) return
                    if (response.code() in listOf(401, 403)) {
                        (activity as? ParentActivity)?.performLogout(); return
                    }
                    val body = response.body() ?: return
                    val list = try { body.getAsJsonArray("attendance") } catch (_: Exception) { null }

                    val container = root.findViewById<LinearLayout>(R.id.lecture_list_container_home)
                    container.removeAllViews()

                    if (list == null || list.size() == 0) {
                        val tv = TextView(requireContext())
                        tv.text = "No classes scheduled for today."
                        tv.textSize = 14f
                        tv.setTextColor(Color.parseColor("#99FFFFFF"))
                        container.addView(tv)
                        updateStats(0, 0)
                        root.findViewById<TextView>(R.id.tv_ai_insight).text =
                            "No classes today. Enjoy the break!"
                        return
                    }

                    var present = 0
                    val total = list.size()
                    for (i in 0 until total) {
                        val obj = try { list[i].asJsonObject } catch (_: Exception) { continue }
                        val status = try { obj.get("status")?.asString ?: "absent" } catch (_: Exception) { "absent" }
                        if (status == "present") present++
                        val card = createLectureCard(obj)
                        card.alpha = 0f
                        container.addView(card)
                        card.animate().alpha(1f).setStartDelay((i * 50).toLong()).setDuration(300).start()
                    }
                    updateStats(present, total)
                    root.findViewById<TextView>(R.id.tv_ai_insight).text = buildInsight(present, total - present, if (total > 0) present * 100 / total else 0)
                    root.findViewById<TextView>(R.id.tv_lec_summary).text =
                        "Today: $present / $total lectures present"
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
            })
    }

    private fun loadStudentMeta() {
        if (!isAdded) return
        RetrofitClient.getService().getParentStudentDay(null).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                val body = response.body() ?: return
                val student = try { body.getAsJsonObject("student") } catch (_: Exception) { null }
                val name = try { student?.get("name")?.asString } catch (_: Exception) { null }
                val faceImg = try { student?.get("face_image")?.asString } catch (_: Exception) { null }
                root.findViewById<TextView>(R.id.tv_home_student_name).text = name ?: "Student"
                if (!faceImg.isNullOrBlank()) {
                    try {
                        val bytes = android.util.Base64.decode(faceImg, android.util.Base64.DEFAULT)
                        val bmp = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                        if (bmp != null) root.findViewById<android.widget.ImageView>(R.id.iv_home_avatar).setImageBitmap(bmp)
                    } catch (_: Exception) {}
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
    }

    // ── TapInX: check-in/out daily view ─────────────────────────────────────

    private fun setupTapInXHome() {
        val prefs = requireActivity().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val studentId = prefs.getString("student_id", "") ?: ""

        val etDate = root.findViewById<EditText>(R.id.et_home_date)
        if (etDate.text.isNullOrBlank()) etDate.setText(sdf.format(Calendar.getInstance().time))
        etDate.setOnClickListener { showDatePicker(etDate) }
        root.findViewById<Button>(R.id.btn_home_apply_date).setOnClickListener { fetchDay() }

        // Lecture section stays hidden for TapInX
        root.findViewById<LinearLayout>(R.id.layout_lectures_home).visibility = View.GONE

        if (studentId.isNotEmpty()) joinSocket(studentId)
        fetchDay()
        fetchMonthStats()
    }

    private fun fetchDay() {
        if (!isAdded) return
        val date = root.findViewById<EditText>(R.id.et_home_date).text.toString().trim().ifBlank { null }
        RetrofitClient.getService().getParentStudentDay(date).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                if (response.code() in listOf(401, 403)) { (activity as? ParentActivity)?.performLogout(); return }
                val body = response.body() ?: return
                val student = try { body.getAsJsonObject("student") } catch (_: Exception) { null }
                val name = try { student?.get("name")?.asString } catch (_: Exception) { null }
                val faceImg = try { student?.get("face_image")?.asString } catch (_: Exception) { null }
                val checkIn = try { body.get("check_in")?.asString } catch (_: Exception) { null }
                val checkOut = try { body.get("check_out")?.asString } catch (_: Exception) { null }

                root.findViewById<TextView>(R.id.tv_home_student_name).text = name ?: "Student"
                if (!faceImg.isNullOrBlank()) {
                    try {
                        val bytes = android.util.Base64.decode(faceImg, android.util.Base64.DEFAULT)
                        val bmp = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                        if (bmp != null) root.findViewById<android.widget.ImageView>(R.id.iv_home_avatar).setImageBitmap(bmp)
                    } catch (_: Exception) {}
                }

                val ciTime = formatTime(checkIn)
                val coTime = formatTime(checkOut)
                root.findViewById<TextView>(R.id.tv_home_checkin_time).text = if (ciTime == "-") "--:--" else ciTime
                root.findViewById<TextView>(R.id.tv_home_checkout_time).text = if (coTime == "-") "--:--" else coTime
                root.findViewById<TextView>(R.id.tv_home_checkin_hint).text = if (ciTime == "-") "Not yet" else "Checked in"
                root.findViewById<TextView>(R.id.tv_home_checkout_hint).text = if (coTime == "-") "Not yet" else "Checked out"

                val list = try { body.getAsJsonArray("attendance") } catch (_: Exception) { null }
                val hist = root.findViewById<LinearLayout>(R.id.home_history_container)
                hist.removeAllViews()
                if (list != null) {
                    for (i in 0 until minOf(list.size(), 5)) {
                        val obj = try { list[i].asJsonObject } catch (_: Exception) { continue }
                        val status = try { obj.get("status")?.asString ?: "" } catch (_: Exception) { "" }
                        if (status != "CHECK_IN" && status != "CHECK_OUT") continue
                        val ts = try { obj.get("timestamp")?.asString ?: "" } catch (_: Exception) { "" }
                        val activity = try { obj.get("activity")?.asString ?: "" } catch (_: Exception) { "" }
                        val place = try {
                            obj.get("device_name")?.asString?.takeIf { it.isNotBlank() }
                                ?: obj.get("place")?.asString ?: ""
                        } catch (_: Exception) { "" }
                        val card = createHistoryCard(status, ts, activity, place)
                        card.alpha = 0f
                        hist.addView(card)
                        card.animate().alpha(1f).setStartDelay((i * 60).toLong()).setDuration(300).start()
                    }
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
    }

    private fun fetchMonthStats() {
        if (!isAdded) return
        RetrofitClient.getService().getParentAttendance().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                val body = response.body() ?: return
                val list = try { body.getAsJsonArray("attendance") } catch (_: Exception) { return }
                val days = mutableSetOf<String>()
                val presentDays = mutableSetOf<String>()
                for (i in 0 until list.size()) {
                    val obj = try { list[i].asJsonObject } catch (_: Exception) { continue }
                    val ts = try { obj.get("timestamp")?.asString ?: "" } catch (_: Exception) { "" }
                    val dateStr = ts.take(10)
                    if (!dateStr.matches(Regex("\\d{4}-\\d{2}-\\d{2}"))) continue
                    days.add(dateStr)
                    if ((try { obj.get("status")?.asString } catch (_: Exception) { null }) == "CHECK_IN")
                        presentDays.add(dateStr)
                }
                val total = maxOf(days.size, 1)
                val present = presentDays.size
                val absent = total - present
                val rate = present * 100 / total
                updateStats(present, total)
                root.findViewById<TextView>(R.id.tv_stat_absent).text = "$absent"
                root.findViewById<TextView>(R.id.tv_ai_insight).text = buildInsight(present, absent, rate)
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
    }

    // ── Shared helpers ────────────────────────────────────────────────────────

    private fun updateStats(present: Int, total: Int) {
        val absent = total - present
        val rate = if (total > 0) present * 100 / total else 0
        root.findViewById<TextView>(R.id.tv_stat_present).text = "$present"
        root.findViewById<TextView>(R.id.tv_stat_absent).text = "$absent"
        root.findViewById<TextView>(R.id.tv_stat_rate).text = "$rate%"
    }

    private fun buildInsight(present: Int, absent: Int, rate: Int): String = when {
        rate >= 90 -> "Excellent! $present sessions attended ($rate%). Outstanding performance!"
        rate >= 75 -> "Good job at $rate% ($present sessions). Push for 90%+ this month."
        rate >= 50 -> "Fair attendance: $rate% ($present sessions, $absent missed). Room to improve."
        else -> "Attendance needs attention: $rate% ($absent sessions missed). Take action now."
    }

    private fun greeting() = when (Calendar.getInstance().get(Calendar.HOUR_OF_DAY)) {
        in 5..11 -> "Good morning"; in 12..17 -> "Good afternoon"; else -> "Good evening"
    }

    private fun animateCardsIn() {
        listOf(R.id.card_live_status, R.id.card_ai_insight).forEachIndexed { i, id ->
            root.findViewById<View>(id)?.let { v ->
                v.alpha = 0f; v.translationY = 60f
                v.animate().alpha(1f).translationY(0f)
                    .setStartDelay((i * 120).toLong()).setDuration(400)
                    .setInterpolator(AccelerateDecelerateInterpolator()).start()
            }
        }
    }

    private fun startPulseDot() {
        val dot = root.findViewById<View>(R.id.view_pulse_dot) ?: return
        val scaleX = ObjectAnimator.ofFloat(dot, "scaleX", 1f, 1.5f, 1f).apply {
            duration = 1600; repeatCount = android.animation.ValueAnimator.INFINITE
        }
        val scaleY = ObjectAnimator.ofFloat(dot, "scaleY", 1f, 1.5f, 1f).apply {
            duration = 1600; repeatCount = android.animation.ValueAnimator.INFINITE
        }
        val alpha = ObjectAnimator.ofFloat(dot, "alpha", 1f, 0.4f, 1f).apply {
            duration = 1600; repeatCount = android.animation.ValueAnimator.INFINITE
        }
        AnimatorSet().apply { playTogether(scaleX, scaleY, alpha); start() }
    }

    private fun showDatePicker(et: EditText) {
        val cal = Calendar.getInstance()
        try {
            val p = et.text.toString().trim().split("-")
            if (p.size == 3) cal.set(p[0].toInt(), p[1].toInt() - 1, p[2].toInt())
        } catch (_: Exception) {}
        DatePickerDialog(requireContext(), { _, y, m, d ->
            et.setText("$y-${(m + 1).toString().padStart(2, '0')}-${d.toString().padStart(2, '0')}")
        }, cal.get(Calendar.YEAR), cal.get(Calendar.MONTH), cal.get(Calendar.DAY_OF_MONTH)).show()
    }

    private fun formatTime(ts: String?): String {
        if (ts.isNullOrBlank()) return "-"
        return try {
            if (ts.contains("T")) ts.split("T").getOrNull(1)?.take(5) ?: ts
            else if (ts.contains(" ")) ts.split(" ").getOrNull(1)?.take(5) ?: ts
            else ts
        } catch (_: Exception) { ts }
    }

    private fun createHistoryCard(status: String, ts: String, activity: String, place: String): LinearLayout {
        val isIn = status == "CHECK_IN"
        val dp = resources.displayMetrics.density
        val card = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundResource(R.drawable.bg_history_item)
            val pad = (14 * dp).toInt()
            setPadding(pad, pad, pad, pad)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).also { it.bottomMargin = (10 * dp).toInt() }
        }
        val dot = View(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams((10 * dp).toInt(), (10 * dp).toInt()).also {
                it.marginEnd = (14 * dp).toInt()
                it.gravity = android.view.Gravity.CENTER_VERTICAL
            }
            setBackgroundResource(R.drawable.indicator_dot)
            background?.setColorFilter(
                if (isIn) Color.parseColor("#10B981") else Color.parseColor("#3B82F6"),
                android.graphics.PorterDuff.Mode.SRC_IN
            )
        }
        val col = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val tvTime = TextView(requireContext()).apply {
            text = formatTime(ts).let { if (it == "-") "--:--" else it }
            textSize = 20f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        }
        val meta = listOf(if (isIn) "Checked In" else "Checked Out", ts.take(10), activity, place)
            .filter { it.isNotBlank() }.joinToString(" · ")
        val tvMeta = TextView(requireContext()).apply {
            text = meta; textSize = 12f; setTextColor(Color.parseColor("#99FFFFFF"))
        }
        col.addView(tvTime); col.addView(tvMeta)
        card.addView(dot); card.addView(col)
        return card
    }

    private fun createLectureCard(obj: JsonObject): LinearLayout {
        val status = try { obj.get("status")?.asString ?: "absent" } catch (_: Exception) { "absent" }
        val subject = try { obj.get("subject")?.asString ?: "Lecture" } catch (_: Exception) { "Lecture" }
        val date = try { obj.get("lecture_date")?.asString ?: "" } catch (_: Exception) { "" }
        val time = try { obj.get("start_time")?.asString ?: "" } catch (_: Exception) { "" }
        val teacher = try { obj.get("teacher")?.asString ?: "" } catch (_: Exception) { "" }
        val isPresent = status == "present"
        val dp = resources.displayMetrics.density

        val card = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundResource(R.drawable.bg_history_item)
            val pad = (12 * dp).toInt()
            setPadding(pad, pad, pad, pad)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).also { it.bottomMargin = (8 * dp).toInt() }
        }
        val badge = TextView(requireContext()).apply {
            text = if (isPresent) "P" else "A"
            textSize = 14f; setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (isPresent) Color.parseColor("#10B981") else Color.parseColor("#EF4444"))
            layoutParams = LinearLayout.LayoutParams((40 * dp).toInt(), ViewGroup.LayoutParams.WRAP_CONTENT)
                .also { it.marginEnd = (10 * dp).toInt() }
            gravity = android.view.Gravity.CENTER
        }
        val col = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val tvSubject = TextView(requireContext()).apply {
            text = subject; textSize = 15f
            setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        }
        val tvMeta = TextView(requireContext()).apply {
            text = listOf(date, time, teacher).filter { it.isNotBlank() }.joinToString(" · ")
            textSize = 12f; setTextColor(Color.parseColor("#99FFFFFF"))
        }
        col.addView(tvSubject); col.addView(tvMeta)
        card.addView(badge); card.addView(col)
        return card
    }

    private fun joinSocket(studentNumber: String) {
        try {
            val prefs = requireActivity().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
            val serverUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
            mSocket = IO.socket(serverUrl, IO.Options().apply { reconnection = true })
            mSocket?.connect()
            mSocket?.emit("join_student_number", org.json.JSONObject().apply { put("student_number", studentNumber) })
            mSocket?.on("student_attendance") { args ->
                activity?.runOnUiThread {
                    if (!isAdded) return@runOnUiThread
                    try {
                        val obj = args[0] as org.json.JSONObject
                        val s = obj.optString("status")
                        val ts = obj.optString("timestamp")
                        val ac = obj.optString("activity")
                        val place = obj.optString("device_name", obj.optString("place", ""))
                        if (s == "CHECK_IN" || s == "CHECK_OUT") {
                            val hist = root.findViewById<LinearLayout>(R.id.home_history_container)
                            val card = createHistoryCard(s, ts, ac, place).also { it.alpha = 0f }
                            hist.addView(card, 0)
                            card.animate().alpha(1f).setDuration(400).start()
                            val t = formatTime(ts)
                            if (s == "CHECK_IN") {
                                root.findViewById<TextView>(R.id.tv_home_checkin_time).text = if (t == "-") "--:--" else t
                                root.findViewById<TextView>(R.id.tv_home_checkin_hint).text = "Checked in"
                            } else {
                                root.findViewById<TextView>(R.id.tv_home_checkout_time).text = if (t == "-") "--:--" else t
                                root.findViewById<TextView>(R.id.tv_home_checkout_hint).text = "Checked out"
                            }
                        }
                    } catch (_: Exception) {}
                }
            }
        } catch (_: Exception) {}
    }

    override fun onDestroyView() {
        super.onDestroyView()
        mSocket?.disconnect()
    }
}
