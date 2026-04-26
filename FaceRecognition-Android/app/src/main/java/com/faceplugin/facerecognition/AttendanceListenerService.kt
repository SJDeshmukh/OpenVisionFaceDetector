package com.faceplugin.facerecognition

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.faceplugin.facerecognition.api.RetrofitClient
import io.socket.client.IO
import io.socket.client.Socket
import org.json.JSONObject

class AttendanceListenerService : Service() {

    private var mSocket: Socket? = null
    private var studentNumber: String? = null

    companion object {
        private const val CHANNEL_MONITOR = "parent_monitor"
        private const val CHANNEL_ALERT   = "parent_attendance_alert"
        private const val NOTIF_ID_MONITOR = 7001

        fun start(context: Context) {
            val intent = Intent(context, AttendanceListenerService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, AttendanceListenerService::class.java))
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannels()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Show silent persistent notification (required to run in foreground)
        startForeground(NOTIF_ID_MONITOR, buildMonitorNotification())

        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val token = prefs.getString("token", null)
        val role  = prefs.getString("role", null)
        studentNumber = prefs.getString("student_id", null)
            ?: prefs.getString("parent_student_number", null)

        if (token.isNullOrBlank() || role != "parent" || studentNumber.isNullOrBlank()) {
            stopSelf()
            return START_NOT_STICKY
        }

        val serverUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl()) ?: RetrofitClient.getBaseUrl()
        RetrofitClient.setAuthToken(token)
        connectSocket(serverUrl, studentNumber!!)

        // START_STICKY: Android restarts this service automatically if killed
        return START_STICKY
    }

    private fun connectSocket(serverUrl: String, sn: String) {
        try {
            mSocket?.disconnect()
            val opts = IO.Options().apply {
                reconnection = true
                reconnectionAttempts = Int.MAX_VALUE
                reconnectionDelay = 2000
            }
            mSocket = IO.socket(serverUrl, opts)
            mSocket?.connect()

            val data = JSONObject().apply { put("student_number", sn) }
            mSocket?.on(Socket.EVENT_CONNECT) {
                mSocket?.emit("join_student_number", data)
            }
            mSocket?.on("student_attendance") { args ->
                try {
                    val obj = args[0] as JSONObject
                    val name   = obj.optString("name", "Student")
                    val status = obj.optString("status", "")
                    val ts     = obj.optString("timestamp", "")
                    val place  = obj.optString("device_name", obj.optString("place", ""))
                    if (status == "CHECK_IN" || status == "CHECK_OUT") {
                        fireAlertNotification(name, status, ts, place)
                    }
                } catch (_: Exception) {}
            }
        } catch (_: Exception) {}
    }

    @SuppressLint("MissingPermission")
    private fun fireAlertNotification(name: String, status: String, timestamp: String, place: String) {
        val isIn  = status == "CHECK_IN"
        val emoji = if (isIn) "✅" else "👋"
        val verb  = if (isIn) "Checked In" else "Checked Out"
        val time  = formatTime(timestamp)

        val title = "$emoji $name $verb"
        val body  = buildString {
            if (time.isNotBlank() && time != "-") append("at $time")
            if (place.isNotBlank()) append("  •  $place")
        }.trim()

        // Tap → open ParentActivity (home screen)
        val tapIntent = Intent(this, ParentActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pi = PendingIntent.getActivity(
            this, 0, tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notif = NotificationCompat.Builder(this, CHANNEL_ALERT)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body.ifBlank { "Tap to view attendance" })
            .setStyle(NotificationCompat.BigTextStyle().bigText(body.ifBlank { "Tap to view attendance" }))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setVibrate(longArrayOf(0, 200, 100, 200))
            .build()

        try {
            NotificationManagerCompat.from(this)
                .notify((System.currentTimeMillis() % Int.MAX_VALUE).toInt(), notif)
        } catch (_: SecurityException) {}
    }

    private fun buildMonitorNotification(): Notification {
        val tapIntent = Intent(this, ParentActivity::class.java)
        val pi = PendingIntent.getActivity(
            this, 0, tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_MONITOR)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Attendance monitoring active")
            .setContentText("You'll be notified instantly when attendance is marked.")
            .setContentIntent(pi)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun createChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            // Silent persistent channel
            val monitor = NotificationChannel(
                CHANNEL_MONITOR,
                "Attendance Monitoring",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                description = "Silent background service indicator"
                setSound(null, null)
                enableVibration(false)
            }

            // High-priority alert channel
            val alert = NotificationChannel(
                CHANNEL_ALERT,
                "Attendance Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Real-time check-in / check-out alerts"
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 200, 100, 200)
            }

            nm.createNotificationChannel(monitor)
            nm.createNotificationChannel(alert)
        }
    }

    private fun formatTime(ts: String): String {
        if (ts.isBlank()) return ""
        return try {
            if (ts.contains("T")) ts.split("T").getOrNull(1)?.take(5) ?: ""
            else if (ts.contains(" ")) ts.split(" ").getOrNull(1)?.take(5) ?: ""
            else ts.take(5)
        } catch (_: Exception) { "" }
    }

    override fun onDestroy() {
        super.onDestroy()
        mSocket?.disconnect()
        mSocket = null
    }
}
