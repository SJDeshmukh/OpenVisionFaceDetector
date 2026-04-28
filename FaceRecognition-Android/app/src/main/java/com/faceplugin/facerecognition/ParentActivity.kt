package com.faceplugin.facerecognition

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.View
import android.view.animation.AccelerateDecelerateInterpolator
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.floatingactionbutton.FloatingActionButton
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ParentActivity : AppCompatActivity() {

    private var currentNavId = R.id.nav_home
    private val TAG = "ParentActivity"

    private val authFailureReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (MyGlobal.ACTION_AUTH_FAILURE == intent.action) {
                Log.w(TAG, "Auth failure detected, redirecting to Login")
                performLogout()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_parent)

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottom_navigation)
        val fab = findViewById<FloatingActionButton>(R.id.fab_scan)

        // Each flavor gets its own nav menu with correct tabs
        if (BuildConfig.IS_ATTENDX) {
            // AttendX: Home | Analytics | History | Profile  (lecture-based, no leave)
            bottomNav.inflateMenu(R.menu.parent_bottom_nav_menu)
            fab.visibility = View.GONE
        } else {
            // TapInX: Home | Analytics | Leave | Profile  (hostel, leave approval)
            bottomNav.inflateMenu(R.menu.parent_bottom_nav_tapinx)
            fab.setOnClickListener {
                hapticMedium()
                animateFab(fab)
                // Quick-jump to Leave from any tab
                loadFragment(ParentLeaveFragment())
                bottomNav.selectedItemId = R.id.nav_leave
            }
        }

        bottomNav.setOnItemSelectedListener { item ->
            if (item.itemId == currentNavId) return@setOnItemSelectedListener true
            hapticLight()
            currentNavId = item.itemId
            when (item.itemId) {
                R.id.nav_home      -> loadFragment(ParentHomeFragment())
                R.id.nav_analytics -> loadFragment(ParentAnalyticsFragment())
                R.id.nav_history   -> loadFragment(ParentHistoryFragment())   // AttendX only
                R.id.nav_leave     -> loadFragment(ParentLeaveFragment())     // TapInX only
                R.id.nav_profile   -> loadFragment(ParentProfileFragment())
                else -> return@setOnItemSelectedListener false
            }
            true
        }

        if (savedInstanceState == null) {
            loadFragment(ParentHomeFragment())
            bottomNav.selectedItemId = R.id.nav_home
        }

        scheduleParentNotifications()
        ensureNotificationPermission()
        AppFirebaseMessagingService.registerCurrentToken(this)
        // Start persistent socket listener for real-time notifications
        AttendanceListenerService.start(this)
        
        val filter = IntentFilter(MyGlobal.ACTION_AUTH_FAILURE)
        ContextCompat.registerReceiver(this, authFailureReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    override fun onDestroy() {
        super.onDestroy()
        try { unregisterReceiver(authFailureReceiver) } catch (_: Exception) {}
    }

    private fun loadFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .setCustomAnimations(android.R.anim.fade_in, android.R.anim.fade_out)
            .replace(R.id.parent_fragment_container, fragment)
            .commit()
    }

    private fun animateFab(fab: FloatingActionButton) {
        fab.animate()
            .scaleX(0.85f).scaleY(0.85f).setDuration(100)
            .setInterpolator(AccelerateDecelerateInterpolator())
            .withEndAction {
                fab.animate().scaleX(1f).scaleY(1f).setDuration(150).start()
            }.start()
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(
                    this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 101
                )
            }
        }
    }

    private fun scheduleParentNotifications() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED).build()
        val req = PeriodicWorkRequest.Builder(
            AttendanceSyncWorker::class.java, 15, java.util.concurrent.TimeUnit.MINUTES
        ).setConstraints(constraints).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "ParentAttendanceSync", ExistingPeriodicWorkPolicy.KEEP, req
        )
    }

    @Suppress("DEPRECATION")
    fun hapticLight() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
                    .defaultVibrator.vibrate(VibrationEffect.createOneShot(20, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                val v = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                    v.vibrate(VibrationEffect.createOneShot(20, VibrationEffect.DEFAULT_AMPLITUDE))
                else v.vibrate(20)
            }
        } catch (_: Exception) {}
    }

    @Suppress("DEPRECATION")
    fun hapticMedium() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
                    .defaultVibrator.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                val v = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                    v.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
                else v.vibrate(50)
            }
        } catch (_: Exception) {}
    }

    fun performLogout() {
        RetrofitClient.getService().parentLogout().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {}
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
        getSharedPreferences("app_prefs", MODE_PRIVATE).edit().apply {
            remove("parent_student_number"); remove("parent_mobile_number")
            remove("student_id"); remove("face_registered")
            remove("parent_face_template"); remove("token")
            remove("role"); remove("vendor_id"); remove("company_id")
            apply()
        }
        RetrofitClient.setAuthToken(null)
        AttendanceListenerService.stop(this)
        startActivity(Intent(this, LoginActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        })
        finish()
    }
}
