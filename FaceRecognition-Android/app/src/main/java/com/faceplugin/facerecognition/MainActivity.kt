package com.faceplugin.facerecognition

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.util.Base64
import android.widget.ImageButton
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.faceplugin.facerecognition.api.SyncResponse
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.ocp.facesdk.FaceSDK
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class MainActivity : AppCompatActivity() {

    private lateinit var dbManager: DBManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Initialize FaceSDK
        var ret = FaceSDK.setActivation(
            "Fqk7LKLbzfSCBor1Oidf0+aPu7OsAJgjxU5m6EQMP3WQ4JZ0Rt44C8T7auT27jjx9iwYmG/8l3TB\n" +
                    "9MBZuaQKCKMiBvwu+JGfbyrQPrs0vyunAZplg0qUm3MUjz/ko1oJNDzh90jOvsdy8C+SGFWgLULQ\n" +
                    "rA6K0dipo5B0v8uPXHkGliNVRuxdKg86iaGHpVzE9V+oqecdXqiuJyRloIqC+vWEYObQkJAocnwR\n" +
                    "M51gg1HHqFYZ0RS9PI5DVzRNHHT4X/ws7e1tc2R0LgU22gd/4SHDYfoV8gHtyi/QdMthKgyzcJrN\n" +
                    "p0lS+CrpoQuOzWl1toECPoSfcrbmmNP6v67ISA=="
        )

        if (ret == FaceSDK.SDK_SUCCESS) {
            ret = FaceSDK.init(assets)
        }

        if (ret != FaceSDK.SDK_SUCCESS) {
            var msg = "SDK Init Failed"
            if (ret == FaceSDK.SDK_LICENSE_KEY_ERROR) {
                msg = "Invalid license!"
            } else if (ret == FaceSDK.SDK_LICENSE_APPID_ERROR) {
                msg = "Invalid error!"
            } else if (ret == FaceSDK.SDK_LICENSE_EXPIRED) {
                msg = "License expired!"
            } else if (ret == FaceSDK.SDK_NO_ACTIVATED) {
                msg = "No activated!"
            } else if (ret == FaceSDK.SDK_INIT_ERROR) {
                msg = "Init error!"
            }
            Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
        }

        // Initialize DB and Sync
        dbManager = DBManager(this)
        dbManager.loadPerson()
        syncFacesFromBackend()

        // Setup Bottom Navigation
        val bottomNav = findViewById<BottomNavigationView>(R.id.bottom_navigation)
        val btnLogout = findViewById<ImageButton>(R.id.btn_logout)

        // Logout
        btnLogout.setOnClickListener {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            prefs.edit().clear().apply()
            
            val intent = Intent(this, LoginActivity::class.java)
            intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            startActivity(intent)
            finish()
        }
        
        // Role Based Access Control
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val role = prefs.getString("role", "user")
        
        if (role == "user") {
            val menu = bottomNav.menu
            menu.findItem(R.id.nav_enroll).isVisible = false
            menu.findItem(R.id.nav_users).isVisible = false
        }

        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_enroll -> {
                    loadFragment(EnrollFragment())
                    true
                }
                R.id.nav_identify -> {
                    loadFragment(IdentifyFragment())
                    true
                }
                R.id.nav_users -> {
                    loadFragment(UsersFragment())
                    true
                }
                else -> false
            }
        }

        // Load default fragment (Identify or Enroll)
        if (savedInstanceState == null) {
            if (role == "user") {
                loadFragment(IdentifyFragment())
                bottomNav.selectedItemId = R.id.nav_identify
            } else {
                loadFragment(EnrollFragment())
                bottomNav.selectedItemId = R.id.nav_enroll
            }
        }
    }

    private fun loadFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.fragment_container, fragment)
            .commit()
    }

    private fun syncFacesFromBackend() {
        RetrofitClient.getService().downloadFaces().enqueue(object : Callback<SyncResponse> {
            override fun onResponse(call: Call<SyncResponse>, response: Response<SyncResponse>) {
                if (response.isSuccessful) {
                    val faces = response.body()?.faces
                    var newFacesCount = 0
                    faces?.forEach { faceData ->
                        // Check if exists
                        val exists = DBManager.personList.any { it.name == faceData.name }
                        if (!exists) {
                            try {
                                val templates = Base64.decode(faceData.templates, Base64.NO_WRAP)
                                val faceImageBytes = Base64.decode(faceData.faceImage, Base64.NO_WRAP)
                                val faceBitmap = BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size)

                                // Insert into DB and memory
                                if (faceBitmap != null) {
                                    val phone = faceData.phone ?: ""
                                    val dept = faceData.department ?: ""
                                    val desig = faceData.designation ?: ""
                                    
                                    dbManager.insertPerson(faceData.name, faceBitmap, templates, phone, dept, desig)
                                    newFacesCount++
                                }
                            } catch (e: Exception) {
                                e.printStackTrace()
                            }
                        }
                    }
                    if (newFacesCount > 0) {
                        Toast.makeText(this@MainActivity, "Synced $newFacesCount new faces from cloud", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            override fun onFailure(call: Call<SyncResponse>, t: Throwable) {
                t.printStackTrace()
            }
        })
    }
}
