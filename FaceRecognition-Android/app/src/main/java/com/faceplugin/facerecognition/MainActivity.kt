package com.faceplugin.facerecognition

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.graphics.Color
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
import com.google.gson.JsonObject
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.ocp.facesdk.FaceSDK
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import android.os.Build
import androidx.core.content.ContextCompat
import android.media.AudioManager
import io.socket.client.IO
import io.socket.client.Socket
import org.json.JSONObject

class MainActivity : AppCompatActivity() {

    private var mSocket: Socket? = null

    private val authFailureReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (MyGlobal.ACTION_AUTH_FAILURE == intent.action) {
                performLogout("Session expired. Please login again.")
            }
        }
    }

    private lateinit var dbManager: DBManager
    private val handler = Handler(Looper.getMainLooper())
    private val syncInterval: Long = 30000
    private var tvNetworkStatus: TextView? = null
    private val networkStatusInterval: Long = 1500
    private val settingsInterval: Long = 60000

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

    private val settingsRunnable = object : Runnable {
        override fun run() {
            try {
                fetchCooldownSettings()
            } catch (_: Exception) {
            }
            handler.postDelayed(this, settingsInterval)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        MyGlobal.context = getApplicationContext()
        android.util.Log.e("AppCrash", "MainActivity onCreate started")
        setContentView(R.layout.activity_main)

        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val serverUrl = prefs.getString("server_url", null)
            if (!serverUrl.isNullOrBlank()) {
                RetrofitClient.setBaseUrl(serverUrl)
            }
            val token = prefs.getString("token", null)
            RetrofitClient.setAuthToken(token)
        } catch (_: Exception) {
        }

        // Keep Screen On Always
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Initialize FaceSDK
        android.util.Log.e("AppCrash", "Initializing FaceSDK")
        var ret = FaceSDKWrapper.setActivation(
            "Fqk7LKLbzfSCBor1Oidf0+aPu7OsAJgjxU5m6EQMP3WQ4JZ0Rt44C8T7auT27jjx9iwYmG/8l3TB\n" +
                    "9MBZuaQKCKMiBvwu+JGfbyrQPrs0vyunAZplg0qUm3MUjz/ko1oJNDzh90jOvsdy8C+SGFWgLULQ\n" +
                    "rA6K0dipo5B0v8uPXHkGliNVRuxdKg86iaGHpVzE9V+oqecdXqiuJyRloIqC+vWEYObQkJAocnwR\n" +
                    "M51gg1HHqFYZ0RS9PI5DVzRNHHT4X/ws7e1tc2R0LgU22gd/4SHDYfoV8gHtyi/QdMthKgyzcJrN\n" +
                    "p0lS+CrpoQuOzWl1toECPoSfcrbmmNP6v67ISA=="
        )

        if (ret == FaceSDK.SDK_SUCCESS) {
            ret = FaceSDKWrapper.init(assets)
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

        // Adjust visibility based on role
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val role = prefs.getString("role", "user")
        val isUser = "user".equals(role, ignoreCase = true)

        if (isUser) {
            // Hide Enroll and Users for user login
            bottomNav.menu.findItem(R.id.nav_enroll).isVisible = false
            bottomNav.menu.findItem(R.id.nav_users).isVisible = false
            // Hide the bottom navigation bar entirely for users since they only have one tab
            bottomNav.visibility = android.view.View.GONE
        }

        // Logout

        btnLogout.setOnClickListener {
            performLogout("Logged out.")
        }
        tvNetworkStatus = findViewById(R.id.tv_network_status)
        try {
            val dn = getSharedPreferences("app_prefs", MODE_PRIVATE).getString("device_name", null)
            val tvPlace = findViewById<TextView>(R.id.tv_device_name)
            if (!dn.isNullOrBlank() && tvPlace != null) {
                tvPlace.text = "— $dn"
            }
        } catch (_: Exception) {}
        
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

        // Load default fragment
        if (savedInstanceState == null) {
            loadFragment(IdentifyFragment())
            bottomNav.selectedItemId = R.id.nav_identify
        }

        fetchCooldownSettings()
        setupAuthSocket()
        // Ensure device name is up to date on launch
        refreshDeviceName()
    }

    private fun setupAuthSocket() {
        try {
            val serverUrl = RetrofitClient.getBaseUrl()
            val options = IO.Options()
            options.transports = arrayOf("polling")
            options.path = "/socket.io"
            mSocket = IO.socket(serverUrl, options)

            mSocket?.on(Socket.EVENT_CONNECT) {
                val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                val vendorId = prefs.getInt("vendor_id", -1)
                if (vendorId != -1) {
                    val data = JSONObject()
                    data.put("vendor_id", vendorId)
                    mSocket?.emit("join_vendor", data)
                }
            }

            mSocket?.on("force_logout") { args ->
                if (args.isNotEmpty()) {
                    val data = args[0] as JSONObject
                    val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                    val myVendorId = prefs.getInt("vendor_id", -1)
                    val targetVendorId = data.optInt("vendor_id", -1)

                    if (myVendorId != -1 && myVendorId == targetVendorId) {
                        runOnUiThread {
                            val reason = data.optString("reason", "Subscription expired")
                            performLogout("Access Denied: $reason")
                        }
                    }
                }
            }
            
            // Sync device name in real-time
            mSocket?.on("device_name_updated") { args ->
                if (args.isNotEmpty()) {
                    try {
                        val obj = args[0] as JSONObject
                        val targetDid = obj.optString("device_id", "")
                        val newName = obj.optString("device_name", "")
                        val myDid = android.provider.Settings.Secure.getString(contentResolver, android.provider.Settings.Secure.ANDROID_ID)
                        if (targetDid == myDid && newName.isNotBlank()) {
                            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                            prefs.edit().putString("device_name", newName).apply()
                            runOnUiThread {
                                val tvPlace = findViewById<TextView>(R.id.tv_device_name)
                                tvPlace?.text = "— $newName"
                            }
                        }
                    } catch (_: Exception) {}
                }
            }
            
            mSocket?.on("force_logout_mobile") { args ->
                if (args.isNotEmpty()) {
                    val data = args[0] as JSONObject
                    val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                    val myVendorId = prefs.getInt("vendor_id", -1)
                    val targetVendorId = data.optInt("vendor_id", -1)
                    if (myVendorId != -1 && myVendorId == targetVendorId) {
                        runOnUiThread {
                            val reason = data.optString("reason", "Device limit decreased")
                            performLogout("Access Denied: $reason")
                        }
                    }
                }
            }
            
            mSocket?.on("features_updated") { args ->
                runOnUiThread {
                    try {
                        android.widget.Toast.makeText(this, "Plan updated", android.widget.Toast.LENGTH_SHORT).show()
                        fetchCooldownSettings()
                    } catch (_: Exception) {}
                }
            }

            mSocket?.connect()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun refreshDeviceName() {
        try {
            RetrofitClient.getService().getMobileDeviceInfo().enqueue(object: Callback<com.google.gson.JsonObject> {
                override fun onResponse(call: Call<com.google.gson.JsonObject>, response: Response<com.google.gson.JsonObject>) {
                    if (response.isSuccessful) {
                        val obj = response.body()
                        val dn = obj?.get("device_name")?.asString
                        if (!dn.isNullOrBlank()) {
                            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                            prefs.edit().putString("device_name", dn).apply()
                            runOnUiThread {
                                val tvPlace = findViewById<TextView>(R.id.tv_device_name)
                                tvPlace?.text = "— $dn"
                            }
                        }
                    }
                }
                override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {}
            })
        } catch (_: Exception) {}
    }

    override fun onDestroy() {
        super.onDestroy()
        mSocket?.disconnect()
        mSocket?.off()
    }

    private fun loadFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.fragment_container, fragment)
            .commit()
    }

    override fun onResume() {
        super.onResume()

        try {
            val audioManager = getSystemService(AUDIO_SERVICE) as AudioManager
            val maxVolume = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
            audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, maxVolume, 0)
        } catch (_: Exception) {
        }

        // Register Auth Failure Receiver
        val filter = IntentFilter(MyGlobal.ACTION_AUTH_FAILURE)
        ContextCompat.registerReceiver(this, authFailureReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)

        handler.removeCallbacks(syncRunnable) // Prevent duplicates
        handler.post(syncRunnable) // Start sync immediately
        try {
            SyncScheduler.scheduleImmediate(applicationContext)
            SyncScheduler.schedulePeriodic(applicationContext)
        } catch (_: Exception) {
        }
        handler.removeCallbacks(networkStatusRunnable)
        handler.post(networkStatusRunnable)
        handler.removeCallbacks(settingsRunnable)
        handler.post(settingsRunnable)
        try {
            fetchCooldownSettings()
        } catch (_: Exception) {}
    }

    private fun fetchCooldownSettings() {
        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val token = prefs.getString("token", null)
            if (token.isNullOrBlank()) return
            RetrofitClient.getService().getSettings().enqueue(object : retrofit2.Callback<JsonObject> {
                override fun onResponse(call: retrofit2.Call<JsonObject>, response: retrofit2.Response<JsonObject>) {
                    try {
                        if (response.isSuccessful && response.body() != null) {
                            val body = response.body()!!
                            if (body.has("cooldown") && !body.get("cooldown").isJsonNull) {
                                val raw = body.get("cooldown")
                                val s = if (raw.isJsonPrimitive) raw.asString else raw.toString()
                                val match = Regex("""\d+""").find(s)
                                val sec = match?.value?.toIntOrNull() ?: 30
                                prefs.edit().putInt("cooldown_seconds", sec).apply()
                            }
                        }
                    } catch (_: Exception) {
                    }
                }

                override fun onFailure(call: retrofit2.Call<JsonObject>, t: Throwable) {
                }
            })
        } catch (_: Exception) {
        }
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
        handler.removeCallbacks(settingsRunnable)
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
            tv.setBackgroundResource(R.drawable.bg_network_status_online)
            tv.setTextColor(Color.BLACK)
        } else {
            tv.text = "OFFLINE"
            tv.setBackgroundResource(R.drawable.bg_network_status_offline)
            tv.setTextColor(Color.BLACK)
        }
    }

    private fun clearAuthState() {
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val editor = prefs.edit()
        editor.remove("role")
        editor.remove("token")
        editor.remove("vendor_id")
        editor.remove("company_id")
        editor.apply()
        RetrofitClient.setAuthToken(null)
    }

    private fun performLogout(message: String) {
        // Prevent multiple calls
        if (isFinishing) return

        Toast.makeText(this, message, Toast.LENGTH_LONG).show()

        clearAuthState()

        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        var selectedCode = prefs.getString("selected_business_type_code", null)
        if (selectedCode.isNullOrBlank()) {
            selectedCode = prefs.getString("selected_business_type", null)
            if (!selectedCode.isNullOrBlank()) {
                prefs.edit().putString("selected_business_type_code", selectedCode).apply()
            }
        }
        if (selectedCode.isNullOrBlank()) {
            selectedCode = prefs.getString("selected_vendor_vertical", null)
            if (!selectedCode.isNullOrBlank()) {
                prefs.edit()
                    .putString("selected_business_type_code", selectedCode)
                    .putString("selected_business_type", selectedCode)
                    .apply()
            }
        }
        val intent = if (selectedCode.isNullOrBlank()) {
            Intent(this, BusinessSelectActivity::class.java)
        } else {
            Intent(this, LoginActivity::class.java)
        }
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
                            val serverIds = faces.mapNotNull { it.id }.toSet() // Track what's currently on server

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

                                    // Cleanup phase: remove local persons that are no longer on server
                                    val localPersonsCopy = ArrayList(DBManager.personList)
                                    localPersonsCopy.forEach { localPerson ->
                                        val localId = localPerson.id
                                        // Only delete if it has a server ID and that ID is not in the current server list
                                        if (!localId.isNullOrEmpty() && !serverIds.contains(localId)) {
                                            dbManager.deletePersonById(localId)
                                            android.util.Log.e("AppCrash", "Deleted person not on server: ${localPerson.name} (id: $localId)")
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
                                     
                                     performLogout("Access denied. Please login again.")
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
