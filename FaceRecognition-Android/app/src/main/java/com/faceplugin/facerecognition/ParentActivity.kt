package com.faceplugin.facerecognition

import android.os.Bundle
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.faceplugin.facerecognition.api.RetrofitClient
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import com.google.gson.JsonObject
import io.socket.client.IO
import io.socket.client.Socket
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat

class ParentActivity : AppCompatActivity() {
    private var mSocket: Socket? = null
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_parent)
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val savedNumber = prefs.getString("parent_student_number", "")
        val et = findViewById<android.widget.EditText>(R.id.et_student_number)
        val etDate = findViewById<android.widget.EditText>(R.id.et_date)
        et.setText(savedNumber)
        findViewById<android.widget.Button>(R.id.btn_save_student).setOnClickListener {
            val num = et.text.toString().trim()
            if (num.isEmpty()) return@setOnClickListener
            val req = com.faceplugin.facerecognition.api.ParentSelectRequest(num)
            RetrofitClient.getService().selectStudent(req).enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                    if (response.isSuccessful) {
                        prefs.edit().putString("parent_student_number", num).apply()
                        joinSocket(num)
                        fetchAttendance()
                    }
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
            })
        }
        if (!savedNumber.isNullOrEmpty()) {
            joinSocket(savedNumber!!)
        }
        fetchAttendance()
        findViewById<android.widget.Button>(R.id.btn_filter_date).setOnClickListener {
            fetchAttendance()
        }
        ensureNotificationPermission()
    }
    private fun fetchAttendance() {
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val num = prefs.getString("parent_student_number", "")
        val dateText = findViewById<android.widget.EditText>(R.id.et_date).text.toString().trim()
        val call = if (dateText.isNotEmpty()) {
            RetrofitClient.getService().attendanceByStudentWithDate(num ?: "", dateText)
        } else {
            RetrofitClient.getService().attendanceByStudent(num ?: "")
        }
        call.enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (response.isSuccessful && response.body() != null) {
                    val root = response.body()!!
                    val list = root.getAsJsonArray("attendance")
                    val container = findViewById<LinearLayout>(R.id.parent_container)
                    container.removeAllViews()
                    for (el in list) {
                        val obj = el.asJsonObject
                        val tv = TextView(this@ParentActivity)
                        val n = obj.get("name").asString
                        val s = obj.get("status").asString
                        val ts = obj.get("timestamp").asString
                        val ac = obj.get("activity").asString
                        tv.text = "$n • $s • $ts • $ac"
                        container.addView(tv)
                    }
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
    }
    private fun joinSocket(studentNumber: String) {
        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val serverUrl = prefs.getString("server_url", com.faceplugin.facerecognition.api.RetrofitClient.getBaseUrl())
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
                        val tv = android.widget.TextView(this@ParentActivity)
                        tv.text = "$n • $s • $ts • $ac"
                        findViewById<LinearLayout>(R.id.parent_container).addView(tv, 0)
                        showAttendanceNotification(n, s, ts, ac)
                        val iv = findViewById<android.widget.ImageView>(R.id.ivParentStatus)
                        val tvWave = findViewById<android.widget.TextView>(R.id.tvParentStatus)
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
                    } catch (e: Exception) {}
                }
            }
        } catch (e: Exception) {}
    }
    override fun onDestroy() {
        super.onDestroy()
        mSocket?.disconnect()
        mSocket?.off()
    }
    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
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
    private fun showAttendanceNotification(name: String, status: String, timestamp: String, activity: String) {
        val builder = NotificationCompat.Builder(this, "parent_attendance")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("$name • $status")
            .setContentText("$timestamp • $activity")
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
        NotificationManagerCompat.from(this).notify(System.currentTimeMillis().toInt(), builder.build())
    }
}
