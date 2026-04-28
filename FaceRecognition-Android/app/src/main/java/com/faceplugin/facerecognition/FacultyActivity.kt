package com.faceplugin.facerecognition

import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.bottomnavigation.BottomNavigationView

class FacultyActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "FacultyActivity"
    }

    private lateinit var nav: BottomNavigationView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_faculty)

        nav = findViewById(R.id.faculty_bottom_nav)
        nav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.fnav_home    -> showFragment(FacultyHomeFragment())
                R.id.fnav_scan    -> showFragment(FacultyScanFragment())
                R.id.fnav_history -> showFragment(FacultyHistoryFragment())
                R.id.fnav_profile -> showFragment(FacultyProfileFragment())
            }
            true
        }

        FacultySessionManager.restore(this)

        if (savedInstanceState == null) {
            nav.selectedItemId = R.id.fnav_home
        }
        Log.i(TAG, "FacultyActivity ready — face detection runs server-side")
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.i(TAG, "FacultyActivity destroyed")
    }

    private fun showFragment(fragment: androidx.fragment.app.Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.faculty_fragment_container, fragment)
            .commit()
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
