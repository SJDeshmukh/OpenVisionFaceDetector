package com.faceplugin.facerecognition

import android.Manifest
import android.app.DatePickerDialog
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import android.view.ViewGroup
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import io.socket.client.IO
import io.socket.client.Socket
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

class ParentActivity : AppCompatActivity() {
    private var mSocket: Socket? = null

    private fun createHistoryCard(status: String, timestamp: String, activity: String, place: String): LinearLayout {
        val card = LinearLayout(this)
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

        val tvTime = TextView(this)
        tvTime.setTextColor(resources.getColor(R.color.vision_text_primary))
        tvTime.textSize = 22f
        tvTime.setTypeface(tvTime.typeface, android.graphics.Typeface.BOLD)
        tvTime.text = if (time == "-") "--:--" else time

        val tvSub = TextView(this)
        tvSub.setTextColor(resources.getColor(R.color.vision_text_secondary))
        tvSub.textSize = 12f
        tvSub.text = if (subtitle.isBlank()) " " else subtitle

        card.addView(tvTime)
        card.addView(tvSub)
        return card
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_parent)

        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val savedStudentId = prefs.getString("student_id", "") ?: ""
        val savedMobile = prefs.getString("parent_mobile_number", "") ?: ""
        val etDate = findViewById<EditText>(R.id.et_date)

        findViewById<TextView>(R.id.tv_parent_student_meta).text =
            "Student ID: ${if (savedStudentId.isBlank()) "-" else savedStudentId}"
        findViewById<TextView>(R.id.tv_parent_parent_meta).text =
            "Mobile: ${if (savedMobile.isBlank()) "-" else savedMobile}"

        if (etDate.text.toString().trim().isEmpty()) {
            etDate.setText(SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Calendar.getInstance().time))
        }

        etDate.setOnClickListener { showDatePicker() }

        findViewById<android.widget.Button>(R.id.btn_filter_date).setOnClickListener {
            fetchStudentDay()
        }

        findViewById<android.widget.Button>(R.id.btn_parent_logout).setOnClickListener {
            performLogout()
        }

        if (savedStudentId.isNotEmpty()) {
            joinSocket(savedStudentId)
        }

        scheduleParentNotifications()
        fetchStudentDay()
        ensureNotificationPermission()
    }

    private fun showDatePicker() {
        val etDate = findViewById<EditText>(R.id.et_date)
        val current = Calendar.getInstance()
        try {
            val txt = etDate.text.toString().trim()
            if (txt.matches(Regex("\\d{4}-\\d{2}-\\d{2}"))) {
                val parts = txt.split("-")
                current.set(parts[0].toInt(), parts[1].toInt() - 1, parts[2].toInt())
            }
        } catch (_: Exception) {}

        DatePickerDialog(
            this,
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

    private fun fetchStudentDay() {
        val dateText = findViewById<EditText>(R.id.et_date).text.toString().trim()
        val dateParam = if (dateText.isNotEmpty()) dateText else null

        RetrofitClient.getService().getParentStudentDay(dateParam).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (response.code() == 401 || response.code() == 403) {
                    Toast.makeText(this@ParentActivity, "Session expired. Please login again.", Toast.LENGTH_LONG).show()
                    performLogout()
                    return
                }

                if (!response.isSuccessful || response.body() == null) {
                    Toast.makeText(this@ParentActivity, "Failed to load student details", Toast.LENGTH_SHORT).show()
                    return
                }

                val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                val savedMobile = prefs.getString("parent_mobile_number", "") ?: ""

                val root = response.body()!!
                val studentObj = try { root.getAsJsonObject("student") } catch (_: Exception) { null }
                val studentName = try { studentObj?.get("name")?.asString } catch (_: Exception) { null }
                val studentNum = try { studentObj?.get("student_number")?.asString } catch (_: Exception) { null }
                val lastStatus = try { root.get("last_status")?.asString } catch (_: Exception) { null }
                val date = try { root.get("date")?.asString } catch (_: Exception) { dateText }

                val checkIn = try { root.get("check_in")?.asString } catch (_: Exception) { null }
                val checkOut = try { root.get("check_out")?.asString } catch (_: Exception) { null }

                findViewById<TextView>(R.id.tv_parent_student_name).text = studentName ?: "Student"
                findViewById<TextView>(R.id.tv_parent_student_meta).text =
                    "Student ID: ${studentNum ?: "-"}"
                findViewById<TextView>(R.id.tv_parent_parent_meta).text =
                    "Mobile: ${if (savedMobile.isBlank()) "-" else savedMobile}"

                val checkInTime = formatTime(checkIn)
                val checkOutTime = formatTime(checkOut)
                findViewById<TextView>(R.id.tv_card_checkin_time).text = if (checkInTime == "-") "--:--" else checkInTime
                findViewById<TextView>(R.id.tv_card_checkout_time).text = if (checkOutTime == "-") "--:--" else checkOutTime
                findViewById<TextView>(R.id.tv_card_checkin_hint).text = if (checkInTime == "-") "No check-in" else "Checked in"
                findViewById<TextView>(R.id.tv_card_checkout_hint).text = if (checkOutTime == "-") "No check-out" else "Checked out"

                findViewById<TextView>(R.id.tv_parent_day_summary).text = "Date: ${date ?: "-"} • Status: ${lastStatus ?: "-"}"

                val list = try { root.getAsJsonArray("attendance") } catch (_: Exception) { null }
                val history = findViewById<LinearLayout>(R.id.parent_history_container)
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
                            val activity = try { obj.get("activity")?.asString ?: "" } catch (_: Exception) { "" }
                            val place = try {
                                val dn = obj.get("device_name")?.asString
                                if (!dn.isNullOrBlank()) dn else obj.get("place")?.asString ?: ""
                            } catch (_: Exception) { "" }
                            history.addView(createHistoryCard(status, ts, activity, place))
                        }
                    } catch (_: Exception) {}
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                Toast.makeText(this@ParentActivity, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun joinSocket(studentNumber: String) {
        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val serverUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
            val options = IO.Options()
            options.reconnection = true
            mSocket = IO.socket(serverUrl, options)
            mSocket?.connect()
            val data = org.json.JSONObject()
            data.put("student_number", studentNumber)
            mSocket?.emit("join_student_number", data)
            mSocket?.on("student_attendance") { args ->
                runOnUiThread {
                    try {
                        val obj = args[0] as org.json.JSONObject
                        val n = obj.optString("name")
                        val s = obj.optString("status")
                        val ts = obj.optString("timestamp")
                        val ac = obj.optString("activity")
                        val place = obj.optString("device_name", obj.optString("place", ""))
                        if (s == "CHECK_IN" || s == "CHECK_OUT") {
                            val history = findViewById<LinearLayout>(R.id.parent_history_container)
                            history.addView(createHistoryCard(s, ts, ac, place))
                            if (s == "CHECK_IN") {
                                val t = formatTime(ts)
                                findViewById<TextView>(R.id.tv_card_checkin_time).text = if (t == "-") "--:--" else t
                                findViewById<TextView>(R.id.tv_card_checkin_hint).text = if (t == "-") "No check-in" else "Checked in"
                            }
                            if (s == "CHECK_OUT") {
                                val t = formatTime(ts)
                                findViewById<TextView>(R.id.tv_card_checkout_time).text = if (t == "-") "--:--" else t
                                findViewById<TextView>(R.id.tv_card_checkout_hint).text = if (t == "-") "No check-out" else "Checked out"
                            }
                            try {
                                val dayText = findViewById<TextView>(R.id.tv_parent_day_summary).text.toString()
                                if (dayText.contains("Status:")) {
                                    val parts = dayText.split("Status:")
                                    findViewById<TextView>(R.id.tv_parent_day_summary).text = parts[0].trim() + " • Status: " + s
                                }
                            } catch (_: Exception) {}
                        }
                        showAttendanceNotification(n, s, ts, ac, place)
                        val iv = findViewById<ImageView>(R.id.ivParentStatus)
                        val tvWave = findViewById<TextView>(R.id.tvParentStatus)
                        if (s == "CHECK_IN") {
                            tvWave.visibility = android.view.View.GONE
                            iv.setImageResource(android.R.drawable.checkbox_on_background)
                            iv.setColorFilter(resources.getColor(android.R.color.holo_green_light))
                            iv.visibility = android.view.View.VISIBLE
                            iv.alpha = 1f
                            iv.animate().alpha(0f).setDuration(800).withEndAction {
                                iv.visibility = android.view.View.GONE
                            }.start()
                        } else {
                            iv.visibility = android.view.View.GONE
                            tvWave.text = "👋"
                            tvWave.setTextColor(resources.getColor(android.R.color.holo_blue_light))
                            tvWave.visibility = android.view.View.VISIBLE
                            tvWave.alpha = 1f
                            try {
                                val swing1 = android.animation.ObjectAnimator.ofFloat(tvWave, "rotation", -20f, 20f)
                                swing1.duration = 200
                                val swing2 = android.animation.ObjectAnimator.ofFloat(tvWave, "rotation", -10f, 10f)
                                swing2.duration = 200
                                val settle = android.animation.ObjectAnimator.ofFloat(tvWave, "rotation", 0f)
                                settle.duration = 150
                                val set = android.animation.AnimatorSet()
                                set.playSequentially(swing1, swing2, settle)
                                set.start()
                            } catch (_: Exception) {}
                            tvWave.animate().alpha(0f).setDuration(900).withEndAction {
                                tvWave.visibility = android.view.View.GONE
                            }.start()
                        }
                    } catch (_: Exception) {}
                }
            }
        } catch (_: Exception) {}
    }

    private fun performLogout() {
        try {
            WorkManager.getInstance(applicationContext).cancelUniqueWork("parent-attendance-periodic")
        } catch (_: Exception) {}

        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val token = prefs.getString("token", null)
        val serverUrl = prefs.getString("server_url", null)
        if (!serverUrl.isNullOrBlank()) {
            RetrofitClient.setBaseUrl(serverUrl)
        }
        if (!token.isNullOrBlank()) {
            RetrofitClient.setAuthToken(token)
            try {
                RetrofitClient.getService().parentLogout().enqueue(object : Callback<JsonObject> {
                    override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                        finishLogoutLocal()
                    }
                    override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                        finishLogoutLocal()
                    }
                })
                return
            } catch (_: Exception) {}
        }

        finishLogoutLocal()
    }

    private fun finishLogoutLocal() {
        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            prefs.edit()
                .remove("token")
                .remove("role")
                .remove("vendor_id")
                .remove("company_id")
                .remove("student_id")
                .remove("parent_student_number")
                .remove("parent_mobile_number")
                .apply()
            RetrofitClient.setAuthToken(null)
        } catch (_: Exception) {}
        try {
            startActivity(Intent(this@ParentActivity, LoginActivity::class.java))
            finish()
        } catch (_: Exception) {}
    }

    private fun scheduleParentNotifications() {
        try {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val work = PeriodicWorkRequest.Builder(ParentAttendanceWorker::class.java, 15, java.util.concurrent.TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(applicationContext)
                .enqueueUniquePeriodicWork("parent-attendance-periodic", ExistingPeriodicWorkPolicy.UPDATE, work)
        } catch (_: Exception) {}
    }

    override fun onDestroy() {
        super.onDestroy()
        try {
            mSocket?.disconnect()
            mSocket?.off()
        } catch (_: Exception) {}
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted =
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1001)
            }
        }
        createChannel()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel("parent_attendance", "Parent Attendance", NotificationManager.IMPORTANCE_DEFAULT)
            channel.description = "Check-in/out updates"
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    @android.annotation.SuppressLint("MissingPermission")
    private fun showAttendanceNotification(name: String, status: String, timestamp: String, activity: String, place: String) {
        val builder = NotificationCompat.Builder(this, "parent_attendance")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("$name • $status")
            .setContentText(listOf(timestamp, activity, if (place.isNotBlank()) place else null).filterNotNull().joinToString(" • "))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted =
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            if (!granted) return
        }
        NotificationManagerCompat.from(this).notify(System.currentTimeMillis().toInt(), builder.build())
    }
}
