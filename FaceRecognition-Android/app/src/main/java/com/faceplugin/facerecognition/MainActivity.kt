package com.faceplugin.facerecognition

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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
    private val handler = Handler(Looper.getMainLooper())
    private val syncInterval: Long = 3000 // 3 seconds for near real-time

    private val syncRunnable = object : Runnable {
        override fun run() {
            syncFacesFromBackend()
            handler.postDelayed(this, syncInterval)
        }
    }

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
        // Removed sync from onCreate to rely on onResume

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

    override fun onResume() {
        super.onResume()
        handler.removeCallbacks(syncRunnable) // Prevent duplicates
        handler.post(syncRunnable) // Start sync immediately
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(syncRunnable) // Stop sync when backgrounded
    }

    private fun syncFacesFromBackend() {
        RetrofitClient.getService().downloadFaces().enqueue(object : Callback<SyncResponse> {
            override fun onResponse(call: Call<SyncResponse>, response: Response<SyncResponse>) {
                if (response.isSuccessful) {
                    val faces = response.body()?.faces ?: emptyList()
                    val serverNames = faces.map { it.name }.toSet()
                    
                    // 1. Delete faces that are not on the server (BUT protect unsynced local faces)
                    val localPersons = DBManager.personList.toList() // Copy list to avoid concurrent modification
                    var deletedCount = 0
                    
                    localPersons.forEach { person ->
                        if (!serverNames.contains(person.name)) {
                            // Only delete if it was previously synced.
                            // If synced == false, it means it's a new local user waiting for upload.
                            if (person.synced) {
                                dbManager.deletePerson(person.name)
                                deletedCount++
                            }
                        }
                    }

                    // 2. Add or Update faces
                    var newFacesCount = 0
                    var updatedFacesCount = 0
                    
                    faces.forEach { faceData ->
                        // Check if exists
                        val existingPerson = DBManager.personList.find { it.name == faceData.name }
                        
                        val phone = faceData.phone ?: ""
                        val dept = faceData.department ?: ""
                        val desig = faceData.designation ?: ""

                        if (existingPerson == null) {
                            try {
                                val templates = Base64.decode(faceData.templates, Base64.NO_WRAP)
                                val faceImageBytes = Base64.decode(faceData.faceImage, Base64.NO_WRAP)
                                val faceBitmap = BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size)

                                // Insert into DB and memory
                                if (faceBitmap != null) {
                                    dbManager.insertPerson(faceData.name, faceBitmap, templates, phone, dept, desig)
                                    newFacesCount++
                                }
                            } catch (e: Exception) {
                                e.printStackTrace()
                            }
                        } else {
                            // Check for updates
                            var needsMetadataUpdate = false
                            if (existingPerson.phone != phone || 
                                existingPerson.department != dept || 
                                existingPerson.designation != desig) {
                                needsMetadataUpdate = true
                            }
                            
                            // Check for Face Update
                            var needsFaceUpdate = false
                            try {
                                val serverTemplates = Base64.decode(faceData.templates, Base64.NO_WRAP)
                                // Compare byte arrays
                                if (!java.util.Arrays.equals(existingPerson.templates, serverTemplates)) {
                                    needsFaceUpdate = true
                                }
                            } catch (e: Exception) {
                                e.printStackTrace()
                            }
                            
                            // If it was marked as not synced but now it is on server, mark it as synced
                            if (!existingPerson.synced) {
                                dbManager.updatePersonStatus(faceData.name, true)
                                // No toast needed, silent update
                            }

                            if (needsFaceUpdate) {
                                // Perform Full Update
                                try {
                                    val templates = Base64.decode(faceData.templates, Base64.NO_WRAP)
                                    val faceImageBytes = Base64.decode(faceData.faceImage, Base64.NO_WRAP)
                                    val faceBitmap = BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size)
                                    
                                    if (faceBitmap != null) {
                                        dbManager.insertPerson(faceData.name, faceBitmap, templates, phone, dept, desig)
                                        updatedFacesCount++
                                    }
                                } catch (e: Exception) {
                                    e.printStackTrace()
                                }
                            } else if (needsMetadataUpdate) {
                                dbManager.updatePerson(faceData.name, phone, dept, desig)
                                updatedFacesCount++
                            }
                        }
                    }
                    if (newFacesCount > 0 || deletedCount > 0 || updatedFacesCount > 0) {
                        Toast.makeText(this@MainActivity, "Synced: $newFacesCount added, $updatedFacesCount updated, $deletedCount deleted", Toast.LENGTH_SHORT).show()
                        
                        // Force UI Refresh if UsersFragment is visible
                        val currentFragment = supportFragmentManager.findFragmentById(R.id.fragment_container)
                        if (currentFragment is UsersFragment) {
                            currentFragment.refreshList()
                        }
                    }
                }
            }
            override fun onFailure(call: Call<SyncResponse>, t: Throwable) {
                t.printStackTrace()
            }
        })
    }
}
