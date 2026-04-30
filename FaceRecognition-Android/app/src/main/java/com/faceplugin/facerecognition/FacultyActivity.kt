package com.faceplugin.facerecognition

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.android.material.bottomnavigation.BottomNavigationView
import androidx.core.content.ContextCompat

class FacultyActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "FacultyActivity"
    }

    private lateinit var nav: BottomNavigationView

    // Cache fragments so scan state (photos, faces) persists across tab switches
    private val fragmentCache = mutableMapOf<Int, androidx.fragment.app.Fragment>()
    private var activeFragment: androidx.fragment.app.Fragment? = null

    private val authFailureReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (MyGlobal.ACTION_AUTH_FAILURE == intent.action) {
                Log.w(TAG, "Auth failure detected, redirecting to Login")
                RetrofitClient.setAuthToken(null)
                val loginIntent = Intent(this@FacultyActivity, LoginActivity::class.java)
                loginIntent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                startActivity(loginIntent)
                finish()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        val prefs = getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE)
        if (prefs.getBoolean("theme_light", false)) {
            setTheme(R.style.Theme_FaceAttribute_Light)
        }
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_faculty)

        nav = findViewById(R.id.faculty_bottom_nav)
        nav.setOnItemSelectedListener { item ->
            val frag = when (item.itemId) {
                R.id.fnav_home    -> fragmentCache.getOrPut(R.id.fnav_home)    { FacultyHomeFragment() }
                R.id.fnav_scan    -> fragmentCache.getOrPut(R.id.fnav_scan)    { FacultyScanFragment() }
                R.id.fnav_history -> fragmentCache.getOrPut(R.id.fnav_history) { FacultyHistoryFragment() }
                R.id.fnav_profile -> fragmentCache.getOrPut(R.id.fnav_profile) { FacultyProfileFragment() }
                else -> return@setOnItemSelectedListener true
            }
            showFragment(frag)
            true
        }

        FacultySessionManager.restore(this)

        if (savedInstanceState == null) {
            nav.selectedItemId = R.id.fnav_home
        }
        
        val filter = IntentFilter(MyGlobal.ACTION_AUTH_FAILURE)
        ContextCompat.registerReceiver(this, authFailureReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
        Log.i(TAG, "FacultyActivity ready")
    }

    override fun onDestroy() {
        super.onDestroy()
        try { unregisterReceiver(authFailureReceiver) } catch (_: Exception) {}
        fragmentCache.clear()
        activeFragment = null
        Log.i(TAG, "FacultyActivity destroyed")
    }

    private fun showFragment(fragment: androidx.fragment.app.Fragment) {
        val ft = supportFragmentManager.beginTransaction()
        // Hide the currently active fragment
        activeFragment?.let { ft.hide(it) }
        // Add new fragment if not yet added, otherwise just show it
        if (!fragment.isAdded) {
            ft.add(R.id.faculty_fragment_container, fragment)
        } else {
            ft.show(fragment)
        }
        ft.commit()
        activeFragment = fragment
    }

    fun navigateToHome() {
        nav.selectedItemId = R.id.fnav_home
    }

    fun navigateToScan() {
        nav.selectedItemId = R.id.fnav_scan
    }

    fun navigateToHistory() {
        nav.selectedItemId = R.id.fnav_history
    }
}
