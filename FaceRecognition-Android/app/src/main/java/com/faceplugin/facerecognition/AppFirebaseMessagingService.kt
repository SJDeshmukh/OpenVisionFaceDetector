package com.faceplugin.facerecognition

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

/**
 * Handles FCM push tokens and incoming messages.
 *
 * Delivery model:
 *   • App OPEN (foreground): onMessageReceived fires → we show the notification.
 *   • App CLOSED / background: FCM system tray handles "notification" messages automatically
 *     (no code needed). onMessageReceived is NOT called in this case.
 *   • Data-only messages (no notification block): onMessageReceived fires even in background.
 *
 * The backend sends combined messages (notification + data), so the system covers
 * the closed-app case natively. This service only needs to handle the foreground path.
 */
class AppFirebaseMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        val prefs = getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        prefs.edit().putString("fcm_token", token).apply()
        uploadTokenIfParent(token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        // Only reached in foreground; background messages are auto-shown by the system.
        val title = message.notification?.title
            ?: message.data["title"]
            ?: return
        val body = message.notification?.body ?: message.data["body"] ?: ""
        showNotification(title, body)
    }

    private fun uploadTokenIfParent(token: String) {
        val prefs = getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val authToken = prefs.getString("token", null)
        val role = prefs.getString("role", null)
        if (authToken.isNullOrBlank() || role != "parent") return

        RetrofitClient.setAuthToken(authToken)
        val body = JsonObject().apply { addProperty("fcm_token", token) }
        RetrofitClient.getService().updateFcmToken(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {}
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
    }

    @android.annotation.SuppressLint("MissingPermission")
    private fun showNotification(title: String, body: String) {
        ensureChannelExists()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) return
        }

        val tapIntent = Intent(this, ParentActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pi = PendingIntent.getActivity(
            this, 0, tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notif = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
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

    private fun ensureChannelExists() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Attendance Alerts",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Real-time check-in / check-out alerts"
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 200, 100, 200)
        }
        nm.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_ID = "parent_attendance_alert"

        /**
         * Call this right after parent login succeeds to register the current FCM token
         * with the backend. Firebase may have already cached a token that won't trigger
         * onNewToken again until the token rotates.
         */
        fun registerCurrentToken(context: Context) {
            com.google.firebase.messaging.FirebaseMessaging.getInstance().token
                .addOnSuccessListener { token ->
                    val prefs = context.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
                    prefs.edit().putString("fcm_token", token).apply()

                    val authToken = prefs.getString("token", null)
                    val role = prefs.getString("role", null)
                    if (authToken.isNullOrBlank() || role != "parent") return@addOnSuccessListener

                    RetrofitClient.setAuthToken(authToken)
                    val body = JsonObject().apply { addProperty("fcm_token", token) }
                    RetrofitClient.getService().updateFcmToken(body)
                        .enqueue(object : Callback<JsonObject> {
                            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {}
                            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
                        })
                }
                .addOnFailureListener {}
        }
    }
}
