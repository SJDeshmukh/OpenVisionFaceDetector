package com.faceplugin.facerecognition

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ParentActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_parent)

        findViewById<Button>(R.id.btn_parent_logout).setOnClickListener {
            performLogout()
        }

        findViewById<Button>(R.id.btn_change_face).setOnClickListener {
            showFaceResetConfirmation()
        }

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottom_navigation)
        
        if (BuildConfig.IS_ATTENDX) {
            bottomNav.menu.findItem(R.id.nav_leave)?.isVisible = false
            // Also hide the tab row in ParentAttendanceFragment if needed? 
            // Actually, ParentAttendanceFragment already defaults to Lectures tab in AttendX.
        }

        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_attendance -> {
                    loadFragment(ParentAttendanceFragment())
                    true
                }
                R.id.nav_leave -> {
                    loadFragment(ParentLeaveFragment())
                    true
                }
                else -> false
            }
        }

        if (savedInstanceState == null) {
            bottomNav.selectedItemId = R.id.nav_attendance
        }

        scheduleParentNotifications()
        ensureNotificationPermission()
    }

    private fun loadFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.parent_fragment_container, fragment)
            .commit()
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 101)
            }
        }
    }

    private fun scheduleParentNotifications() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val syncRequest = PeriodicWorkRequest.Builder(AttendanceSyncWorker::class.java, 15, java.util.concurrent.TimeUnit.MINUTES)
            .setConstraints(constraints)
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "ParentAttendanceSync",
            ExistingPeriodicWorkPolicy.KEEP,
            syncRequest
        )
    }

    fun performLogout() {
        RetrofitClient.getService().parentLogout().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {}
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        prefs.edit().run {
            remove("parent_student_number")
            remove("parent_mobile_number")
            remove("student_id")
            remove("face_registered")
            remove("parent_face_template")
            remove("token")
            remove("role")
            remove("vendor_id")
            remove("company_id")
            apply()
        }
        RetrofitClient.setAuthToken(null)
        val intent = Intent(this, LoginActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        startActivity(intent)
        finish()
    }

    private fun showFaceResetConfirmation() {
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Change Registered Face")
            .setMessage("Are you sure you want to change your registered face? This will delete your current face data and require admin approval. Once approved, you will be asked to scan your new face.")
            .setPositiveButton("Request Change") { _, _ ->
                submitFaceResetRequest()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun submitFaceResetRequest() {
        val body = JsonObject().apply {
            addProperty("reason", "User requested face change from mobile app")
        }

        RetrofitClient.getService().requestFaceReset(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (response.isSuccessful) {
                    android.widget.Toast.makeText(this@ParentActivity, "Request sent to admin for approval", android.widget.Toast.LENGTH_LONG).show()
                } else {
                    val errorBody = response.errorBody()?.string()
                    val errorMessage = try {
                        com.google.gson.JsonParser.parseString(errorBody).asJsonObject.get("error").asString
                    } catch (e: Exception) {
                        "Failed to submit request"
                    }
                    android.widget.Toast.makeText(this@ParentActivity, errorMessage, android.widget.Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                android.widget.Toast.makeText(this@ParentActivity, "Network error: ${t.message}", android.widget.Toast.LENGTH_SHORT).show()
            }
        })
    }
}
