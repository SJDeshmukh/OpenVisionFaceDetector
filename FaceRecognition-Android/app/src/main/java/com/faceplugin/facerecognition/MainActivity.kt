package com.faceplugin.facerecognition

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import java.security.MessageDigest
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.faceplugin.facerecognition.api.SyncResponse
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.ocp.facesdk.FaceSDK
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import android.os.Build

class MainActivity : AppCompatActivity() {

    private val authFailureReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (MyGlobal.ACTION_AUTH_FAILURE == intent.action) {
                performLogout()
            }
        }
    }

    private lateinit var dbManager: DBManager
    private val handler = Handler(Looper.getMainLooper())
    private val syncInterval: Long = 30000
    private var tvNetworkStatus: TextView? = null
    private val networkStatusInterval: Long = 1500

    private val syncRunnable = object : Runnable {
        override fun run() {
            try {
                if (NetworkUtils.isOnline(applicationContext)) {
                    val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                    val token = prefs.getString("token", null)
                    if (!token.isNullOrBlank()) {
                        syncFacesFromBackend()
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
            handler.postDelayed(this, syncInterval)
        }
    }

    private val networkStatusRunnable = object : Runnable {
        override fun run() {
            updateNetworkStatusBadge()
            handler.postDelayed(this, networkStatusInterval)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        MyGlobal.context = getApplicationContext()
        android.util.Log.e("AppCrash", "MainActivity onCreate started")
        setContentView(R.layout.activity_main)

        // Keep Screen On Always
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Initialize FaceSDK
        android.util.Log.e("AppCrash", "Initializing FaceSDK")
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
        android.util.Log.e("AppCrash", "Initializing DBManager")
        dbManager = DBManager(applicationContext)
        dbManager.loadPerson()
        // Removed sync from onCreate to rely on onResume

        // Setup Bottom Navigation
        val bottomNav = findViewById<BottomNavigationView>(R.id.bottom_navigation)
        val btnLogout = findViewById<ImageButton>(R.id.btn_logout)

        // Logout

        btnLogout.setOnClickListener {
            performLogout()
        }
        tvNetworkStatus = findViewById(R.id.tv_network_status)
        
        // Role Based Access Control
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val role = prefs.getString("role", "user")
        
        android.util.Log.e("AppCrash", "Role: $role")

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

        // Register Auth Failure Receiver
        val filter = IntentFilter(MyGlobal.ACTION_AUTH_FAILURE)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(authFailureReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(authFailureReceiver, filter)
        }

        handler.removeCallbacks(syncRunnable) // Prevent duplicates
        handler.post(syncRunnable) // Start sync immediately
        try {
            SyncScheduler.scheduleImmediate(applicationContext)
        } catch (_: Exception) {
        }
        handler.removeCallbacks(networkStatusRunnable)
        handler.post(networkStatusRunnable)
    }

    override fun onPause() {
        super.onPause()

        // Unregister Auth Failure Receiver
        try {
            unregisterReceiver(authFailureReceiver)
        } catch (e: Exception) {
            e.printStackTrace()
        }

        handler.removeCallbacks(syncRunnable) // Stop sync when backgrounded
        handler.removeCallbacks(networkStatusRunnable)
    }

    private fun updateNetworkStatusBadge() {
        val tv = tvNetworkStatus ?: return
        val online = try {
            NetworkUtils.isOnline(applicationContext)
        } catch (_: Exception) {
            false
        }
        if (online) {
            tv.text = "ONLINE"
            tv.setTextColor(resources.getColor(R.color.vision_success))
        } else {
            tv.text = "OFFLINE"
            tv.setTextColor(resources.getColor(R.color.vision_error))
        }
    }

    private fun performLogout() {
        // Prevent multiple calls
        if (isFinishing) return

        Toast.makeText(this, "Session Expired. Please Login Again.", Toast.LENGTH_LONG).show()

        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        prefs.edit().clear().apply()
        
        RetrofitClient.setAuthToken(null) // Clear token
        
        val intent = Intent(this, LoginActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        startActivity(intent)
        finish()
    }

    private fun syncFacesFromBackend() {
        android.util.Log.e("AppCrash", "Starting syncFacesFromBackend")
        try {
            RetrofitClient.getService().downloadFaces().enqueue(object : Callback<SyncResponse> {
                override fun onResponse(call: Call<SyncResponse>, response: Response<SyncResponse>) {
                    android.util.Log.e("AppCrash", "Sync Response: ${response.code()}")
                    try {
                        if (response.isSuccessful) {
                            val faces = response.body()?.faces ?: emptyList()
                            val signature = facesSignature(faces)
                            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                            val lastSig = prefs.getString("last_faces_signature", null)
                            if (lastSig != null && lastSig == signature) {
                                return
                            }
                            prefs.edit().putString("last_faces_signature", signature).apply()

                            Thread {
                                try {
                                    var newFacesCount = 0
                                    var updatedFacesCount = 0

                                    faces.forEach { faceData ->
                                        try {
                                            var existingPerson: com.faceplugin.facerecognition.Person? = null
                                            if (!faceData.id.isNullOrEmpty()) {
                                                existingPerson = DBManager.personList.find { it.id == faceData.id }
                                            }
                                            if (existingPerson == null) {
                                                existingPerson = DBManager.personList.find { it.synced && it.name == faceData.name }
                                            }

                                            val phone = faceData.phone ?: ""
                                            val dept = faceData.department ?: ""
                                            val desig = faceData.designation ?: ""
                                            val shift = faceData.shift ?: ""
                                            val id = faceData.id ?: ""
                                            val customDataObj = faceData.customData
                                            val customDataStr = if (customDataObj != null) customDataObj.toString() else ""

                                            val templatesB64 = faceData.templates
                                            val faceB64 = faceData.faceImage
                                            if (templatesB64.isNullOrEmpty() || faceB64.isNullOrEmpty()) return@forEach

                                            val templates = Base64.decode(templatesB64, Base64.NO_WRAP)
                                            val faceImageBytes = Base64.decode(faceB64, Base64.NO_WRAP)
                                            val faceBitmap = BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size) ?: return@forEach

                                            if (existingPerson == null) {
                                                dbManager.insertPerson(id, faceData.name, faceBitmap, templates, phone, dept, desig, shift, customDataStr, true)
                                                newFacesCount++
                                            } else {
                                                val effectiveId = if (!id.isNullOrEmpty()) id else (existingPerson.id ?: "")
                                                val needsMetadataUpdate =
                                                    existingPerson.phone != phone ||
                                                        existingPerson.department != dept ||
                                                        existingPerson.designation != desig ||
                                                        existingPerson.shift != shift ||
                                                        existingPerson.customData != customDataStr ||
                                                        (existingPerson.id != id && !id.isNullOrEmpty())

                                                var needsFaceUpdate = false
                                                try {
                                                    if (!java.util.Arrays.equals(existingPerson.templates, templates)) {
                                                        needsFaceUpdate = true
                                                    }
                                                } catch (_: Exception) {}

                                                if (needsFaceUpdate || needsMetadataUpdate) {
                                                    dbManager.insertPerson(effectiveId, faceData.name, faceBitmap, templates, phone, dept, desig, shift, customDataStr, true)
                                                    updatedFacesCount++
                                                }
                                            }
                                        } catch (_: Exception) {
                                        }
                                    }

                                    runOnUiThread {
                                        try {
                                            dbManager.loadPerson()
                                        } catch (_: Exception) {
                                        }
                                        val currentFragment = supportFragmentManager.findFragmentById(R.id.fragment_container)
                                        if (currentFragment is UsersFragment) {
                                            currentFragment.refreshList()
                                        }
                                    }
                                } catch (_: Exception) {
                                }
                            }.start()
                        } else {
                            // Handle 403 Suspended
                             try {
                                val errorBody = response.errorBody()?.string()
                                if (response.code() == 403 || (errorBody != null && errorBody.contains("Access Denied"))) {
                                     handler.removeCallbacks(syncRunnable) // Stop syncing
                                     
                                     Toast.makeText(this@MainActivity, "Access Denied: Vendor Suspended. Logging out...", Toast.LENGTH_LONG).show()
                                     
                                     // Logout
                                     val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                                     prefs.edit().clear().apply()
        
                                     RetrofitClient.setAuthToken(null) // Clear token
                                     
                                     val intent = Intent(this@MainActivity, LoginActivity::class.java)
                                     intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                                     startActivity(intent)
                                     finish()
                                }
                            } catch (e: Exception) {
                                e.printStackTrace()
                            }
                        }
                    } catch (e: Exception) {
                        e.printStackTrace()
                    }
                }
                override fun onFailure(call: Call<SyncResponse>, t: Throwable) {
                    t.printStackTrace()
                }
            })
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun facesSignature(faces: List<com.faceplugin.facerecognition.api.SyncRequest>): String {
        val sb = StringBuilder()
        sb.append(faces.size).append('|')
        for (i in 0 until kotlin.math.min(faces.size, 100)) {
            val f = faces[i]
            sb.append(f.id ?: "").append(':').append(f.name ?: "").append('|')
        }
        val bytes = MessageDigest.getInstance("SHA-256").digest(sb.toString().toByteArray(Charsets.UTF_8))
        val out = StringBuilder(bytes.size * 2)
        for (b in bytes) out.append(String.format("%02x", b))
        return out.toString()
    }
}
