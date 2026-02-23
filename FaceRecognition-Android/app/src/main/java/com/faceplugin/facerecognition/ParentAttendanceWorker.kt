package com.faceplugin.facerecognition

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.WorkManager
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class ParentAttendanceWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    override fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val token = prefs.getString("token", null)
        val role = prefs.getString("role", null)
        if (token.isNullOrBlank() || role != "parent") {
            return Result.success()
        }

        val serverUrl = prefs.getString("server_url", null)
        if (!serverUrl.isNullOrBlank()) {
            RetrofitClient.setBaseUrl(serverUrl)
        }
        RetrofitClient.setAuthToken(token)

        val date = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())

        return try {
            val resp = RetrofitClient.getService().getParentAttendanceByDateLimit(date, 1).execute()
            if (resp.code() == 401 || resp.code() == 403) {
                try {
                    prefs.edit()
                        .remove("token")
                        .remove("role")
                        .remove("vendor_id")
                        .remove("company_id")
                        .apply()
                    RetrofitClient.setAuthToken(null)
                    WorkManager.getInstance(applicationContext).cancelUniqueWork("parent-attendance-periodic")
                } catch (_: Exception) {}
                return Result.success()
            }
            if (!resp.isSuccessful || resp.body() == null) {
                return Result.success()
            }
            val body: JsonObject = resp.body()!!
            val arr = try { body.getAsJsonArray("attendance") } catch (_: Exception) { null }
            if (arr == null || arr.size() == 0) {
                return Result.success()
            }

            val obj = arr[0].asJsonObject
            val id = try { obj.get("id")?.asInt } catch (_: Exception) { null }
            val status = try { obj.get("status")?.asString } catch (_: Exception) { null }
            val ts = try { obj.get("timestamp")?.asString } catch (_: Exception) { null }
            val name = try { obj.get("name")?.asString } catch (_: Exception) { null }
            val activity = try { obj.get("activity")?.asString } catch (_: Exception) { null }

            val lastId = prefs.getInt("parent_last_attendance_id", -1)
            if (id == null || id == lastId) {
                return Result.success()
            }

            prefs.edit().putInt("parent_last_attendance_id", id).apply()
            showNotification(name ?: "Student", status ?: "Update", ts ?: "", activity ?: "")
            Result.success()
        } catch (_: Exception) {
            Result.success()
        }
    }

    private fun showNotification(name: String, status: String, timestamp: String, activity: String) {
        createChannel()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            if (!granted) return
        }

        val title = "$name • $status"
        val content = listOf(timestamp, activity).filter { it.isNotBlank() }.joinToString(" • ")

        val notif = NotificationCompat.Builder(applicationContext, "parent_attendance_bg")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(content)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        NotificationManagerCompat.from(applicationContext).notify((System.currentTimeMillis() % Int.MAX_VALUE).toInt(), notif)
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channel = NotificationChannel(
                "parent_attendance_bg",
                "Parent Attendance",
                NotificationManager.IMPORTANCE_HIGH
            )
            channel.description = "Background check-in/out alerts"
            nm.createNotificationChannel(channel)
        }
    }
}
