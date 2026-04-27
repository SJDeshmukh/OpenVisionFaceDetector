package com.faceplugin.facerecognition

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.ocp.facesdk.FaceSDK

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
    }

    override fun onStart() {
        super.onStart()
        // Lazy init: load face engine only when faculty is active (not for parents)
        if (!FaceSDKWrapper.isInitialized) {
            Thread {
                val ret = FaceSDKWrapper.ensureInitialized(applicationContext)
                runOnUiThread {
                    if (ret == FaceSDK.SDK_SUCCESS) {
                        Log.i(TAG, "FaceSDK ready for faculty")
                    } else {
                        Log.w(TAG, "FaceSDK init returned $ret — face matching may be unavailable")
                        Toast.makeText(this, "Face model warning: code $ret", Toast.LENGTH_SHORT).show()
                    }
                }
            }.start()
        }
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

    fun navigateToScan() {
        nav.selectedItemId = R.id.fnav_scan
    }
}
