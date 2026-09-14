package com.faceplugin.facerecognition

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import java.io.File
import java.security.MessageDigest
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.faceplugin.facerecognition.api.SyncResponse
import com.faceplugin.facerecognition.update.AppUpdateManager
import com.google.gson.JsonObject
import com.google.android.material.bottomnavigation.BottomNavigationView
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.preference.PreferenceManager
import android.media.AudioManager
import io.socket.client.IO
import io.socket.client.Socket
import org.json.JSONObject

import android.Manifest
import android.content.pm.PackageManager
import androidx.core.app.ActivityCompat
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.provider.Settings
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.location.LocationSettingsRequest
import com.google.android.gms.location.LocationSettingsResponse
import com.google.android.gms.common.api.ResolvableApiException
import android.content.IntentSender

class MainActivity : AppCompatActivity() {

    private var mSocket: Socket? = null
    private lateinit var fusedLocationClient: FusedLocationProviderClient

    private val authFailureReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (MyGlobal.ACTION_AUTH_FAILURE == intent.action) {
                val message = intent.getStringExtra("message") ?: "Session expired. Please login again."
                performLogout(message)
            }
        }
    }

    private lateinit var dbManager: DBManager
    private val handler = Handler(Looper.getMainLooper())
    private val syncInterval: Long = 30000
    private var tvNetworkStatus: TextView? = null
    private var tvGeofenceStatus: TextView? = null
    private var ivGeoIcon: ImageView? = null
    private var lastKnownGeofenceStatus: String? = null
    private var lastKnownDistance: Double? = null
    private var lastKnownLat: Double? = null
    private var lastKnownLng: Double? = null
    private var anchorLat: Double? = null
    private var anchorLng: Double? = null
    private var anchorRadius: Double? = null
    private val REQUEST_CHECK_SETTINGS = 1001
    private var isLoggingOut = false
    private var locationManager: LocationManager? = null
    private var latestDeviceLocation: Location? = null
    private var locationCallback: LocationCallback? = null
    private var nativeLocationListener: LocationListener? = null
    private val networkStatusInterval: Long = 1500
    private val settingsInterval: Long = 60000
    private val heartbeatInterval: Long = 30000 // 30 seconds for responsive geofencing

    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            try {
                if (NetworkUtils.isOnline(applicationContext)) {
                    sendHeartbeat()
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
            handler.postDelayed(this, heartbeatInterval)
        }
    }

    private var enrollFragment: EnrollFragment? = null
    private var identifyFragment: IdentifyFragment? = null
    private var usersFragment: UsersFragment? = null
    private var activeFragment: Fragment? = null
    private var lastClickTime: Long = 0
    private val clickDebounce: Long = 400 // ms

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

        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)

        val permissions = mutableListOf(Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissions.add(Manifest.permission.ACCESS_FINE_LOCATION)
        permissions.add(Manifest.permission.ACCESS_COARSE_LOCATION)

        val ungranted = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (ungranted.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, ungranted.toTypedArray(), 100)
        } else {
            promptEnableLocationSettings()
            startLocationTracking()
        }

        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val sAnchorLat = prefs.getString("anchor_lat", null)?.toDoubleOrNull()
            val sAnchorLng = prefs.getString("anchor_lng", null)?.toDoubleOrNull()
            val sAnchorRad = prefs.getString("anchor_radius", null)?.toDoubleOrNull()
            if (sAnchorLat != null && sAnchorLng != null && sAnchorRad != null && sAnchorRad > 0.0) {
                anchorLat = sAnchorLat
                anchorLng = sAnchorLng
                anchorRadius = sAnchorRad
            }
        } catch (_: Exception) {}

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

            // Auto-engage Kiosk Lockdown Mode for kiosk user
            window.decorView.post {
                startKioskLockdown()
            }
        }

        // Kiosk Mode & Logout
        val btnKiosk = findViewById<ImageButton>(R.id.btn_kiosk)
        btnKiosk?.setOnClickListener {
            if (isKioskModeActive) {
                promptKioskPin {
                    stopKioskLockdown()
                    Toast.makeText(this, "Exited Kiosk Mode", Toast.LENGTH_SHORT).show()
                }
            } else {
                startKioskLockdown()
            }
        }

        btnLogout.setOnClickListener {
            if (isKioskModeActive) {
                promptKioskPin {
                    stopKioskLockdown()
                    performLogout("Logged out.")
                }
            } else {
                performLogout("Logged out.")
            }
        }
        tvNetworkStatus = findViewById<TextView>(R.id.tv_network_status)
        tvGeofenceStatus = findViewById<TextView>(R.id.tv_geofence_status)
        ivGeoIcon = findViewById<ImageView>(R.id.iv_geo_icon)
        val headerGeofence = findViewById<View>(R.id.header_geofence)
        headerGeofence?.setOnClickListener {
            showGeofenceDetailsDialog()
        }
        try {
            val dn = getSharedPreferences("app_prefs", MODE_PRIVATE).getString("device_name", null)
            val tvPlace = findViewById<TextView>(R.id.tv_device_name)
            if (!dn.isNullOrBlank() && tvPlace != null) {
                tvPlace.text = "— $dn"
            }
            
            // If Kiosk user has no place assigned, force selection
            if (isUser && dn.isNullOrBlank()) {
                checkDeviceSlotAssignment()
            }
        } catch (_: Exception) {}
        
        bottomNav.setOnItemSelectedListener { item ->
            val now = System.currentTimeMillis()
            if (now - lastClickTime < clickDebounce) {
                return@setOnItemSelectedListener false
            }
            lastClickTime = now

            when (item.itemId) {
                R.id.nav_enroll -> {
                    if (enrollFragment == null) enrollFragment = EnrollFragment()
                    switchFragment(enrollFragment!!)
                    true
                }
                R.id.nav_identify -> {
                    if (identifyFragment == null) identifyFragment = IdentifyFragment()
                    switchFragment(identifyFragment!!)
                    true
                }
                R.id.nav_users -> {
                    if (usersFragment == null) usersFragment = UsersFragment()
                    switchFragment(usersFragment!!)
                    true
                }
                else -> false
            }
        }

        // Load default fragment
        if (savedInstanceState == null) {
            identifyFragment = IdentifyFragment()
            activeFragment = identifyFragment
            supportFragmentManager.beginTransaction()
                .add(R.id.fragment_container, identifyFragment!!, "identify")
                .commit()
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

            mSocket?.on("app_update_available") { args ->
                android.util.Log.i("MainActivity", "Real-time OTA update broadcast received from SuperAdmin")
                runOnUiThread {
                    checkForOtaUpdate(forceImmediate = true)
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
                        val dnElement = obj?.get("device_name")
                        val dn = if (dnElement != null && dnElement.isJsonPrimitive) dnElement.asString else null
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
        try {
            stopLockTask()
        } catch (_: Exception) {}
        mSocket?.disconnect()
        mSocket?.off()
        stopLocationTracking()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100) {
            val fineGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
            val coarseGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
            if (fineGranted || coarseGranted) {
                promptEnableLocationSettings()
                startLocationTracking()
                handler.removeCallbacks(heartbeatRunnable)
                handler.post(heartbeatRunnable)
            }
        }
    }

    private fun switchFragment(fragment: Fragment) {
        if (activeFragment == fragment) return
        
        val transaction = supportFragmentManager.beginTransaction()
        
        // Hide the active fragment
        activeFragment?.let { transaction.hide(it) }
        
        // Show or add the new fragment
        if (!fragment.isAdded) {
            val tag = when (fragment) {
                is IdentifyFragment -> "identify"
                is EnrollFragment -> "enroll"
                is UsersFragment -> "users"
                else -> null
            }
            transaction.add(R.id.fragment_container, fragment, tag)
        } else {
            transaction.show(fragment)
        }
        
        transaction.commit()
        activeFragment = fragment
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
        promptEnableLocationSettings()
        startLocationTracking()
        handler.removeCallbacks(heartbeatRunnable)
        handler.post(heartbeatRunnable)
        try {
            fetchCooldownSettings()
        } catch (_: Exception) {}

        try {
            checkForOtaUpdate(forceImmediate = false)
        } catch (_: Exception) {}
    }

    private var updateBannerView: View? = null

    private fun checkForOtaUpdate(forceImmediate: Boolean) {
        AppUpdateManager.checkAndUpdateInBackground(
            context = applicationContext,
            quiet = !forceImmediate,
            callback = object : AppUpdateManager.UpdateCallback {
                override fun onUpdateAvailable(release: AppUpdateManager.ReleaseInfo) {
                    android.util.Log.i("MainActivity", "OTA Update Available: v${release.versionName} (${release.versionCode})")
                }

                override fun onUpdateReadyToInstall(release: AppUpdateManager.ReleaseInfo, apkFile: File) {
                    android.util.Log.i("MainActivity", "OTA Update Ready to install: ${apkFile.name}")
                    runOnUiThread {
                        showUpdateBannerOrInstall(release, apkFile)
                    }
                }

                override fun onError(error: String) {
                    android.util.Log.w("MainActivity", "OTA Update check/download notice: $error")
                }
            }
        )
    }

    private fun showUpdateBannerOrInstall(release: AppUpdateManager.ReleaseInfo, apkFile: File) {
        if (isFinishing || isDestroyed) return

        // If forceUpdate is true, install immediately
        if (release.forceUpdate) {
            AppUpdateManager.installApk(this, apkFile)
            return
        }

        // If banner already shown, don't duplicate
        if (updateBannerView != null) return

        val root = findViewById<ViewGroup>(android.R.id.content) ?: return
        val banner = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(32, 20, 32, 20)
            setBackgroundColor(android.graphics.Color.parseColor("#F10F172A")) // Slate 900
            gravity = android.view.Gravity.CENTER_VERTICAL
            elevation = 20f

            val tv = TextView(context).apply {
                text = "🚀 App Update v${release.versionName} Ready"
                setTextColor(android.graphics.Color.WHITE)
                textSize = 14f
                typeface = android.graphics.Typeface.DEFAULT_BOLD
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }

            val btnInstall = Button(context).apply {
                text = "Install"
                setBackgroundColor(android.graphics.Color.parseColor("#4F46E5")) // Indigo 600
                setTextColor(android.graphics.Color.WHITE)
                setOnClickListener {
                    AppUpdateManager.installApk(this@MainActivity, apkFile)
                }
            }

            addView(tv)
            addView(btnInstall)
        }

        val lp = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        )
        root.addView(banner, lp)
        updateBannerView = banner

        // Auto-install after 60 seconds of idle if not touched
        handler.postDelayed({
            if (updateBannerView != null && !isFinishing && !isDestroyed) {
                AppUpdateManager.installApk(this, apkFile)
            }
        }, 60000)
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
                            if (body.has("threshold") && !body.get("threshold").isJsonNull) {
                                val threshold = body.get("threshold").asString.toFloatOrNull()?.coerceIn(0.4f, 0.95f)
                                if (threshold != null) {
                                    PreferenceManager.getDefaultSharedPreferences(this@MainActivity)
                                        .edit().putString("identify_threshold", threshold.toString()).apply()
                                }
                            }
                            if (body.has("voice_greeting") && !body.get("voice_greeting").isJsonNull) {
                                prefs.edit().putBoolean(
                                    "voice_greeting_enabled",
                                    body.get("voice_greeting").asString.equals("true", ignoreCase = true)
                                ).apply()
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
        handler.removeCallbacks(heartbeatRunnable)
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
        if (isFinishing || isLoggingOut) return
        isLoggingOut = true

        runOnUiThread {
            try {
                // 1. Unregister authFailureReceiver immediately to avoid repeated triggers
                try {
                    unregisterReceiver(authFailureReceiver)
                } catch (_: Exception) {}

                // 2. Stop all background runners and location tracking immediately
                handler.removeCallbacks(syncRunnable)
                handler.removeCallbacks(networkStatusRunnable)
                handler.removeCallbacks(settingsRunnable)
                handler.removeCallbacks(heartbeatRunnable)
                stopLocationTracking()

                // 3. Disconnect real-time socket
                try {
                    mSocket?.disconnect()
                    mSocket?.off()
                } catch (_: Exception) {}

                // 4. CRITICAL: Stop LockTask mode (screen pinning) and clear immersive mode
                // Without calling stopLockTask(), Android OS blocks the activity from finishing
                // and traps the device on MainActivity while repeatedly displaying authentication errors.
                try {
                    stopLockTask()
                } catch (e: Exception) {
                    android.util.Log.w("Kiosk", "stopLockTask: ${e.message}")
                }
                isKioskModeActive = false
                clearImmersiveMode()

                // 5. Clear authentication credentials & tokens
                clearAuthState()

                // 6. User-friendly message
                val displayMsg = if (message.equals("Authentication required", ignoreCase = true)
                    || message.equals("Authentication Required", ignoreCase = true)
                    || message.contains("unauthorized", ignoreCase = true)
                    || message.contains("token", ignoreCase = true)) {
                    "Session expired or password changed. Please log in again."
                } else {
                    message
                }
                Toast.makeText(applicationContext, displayMsg, Toast.LENGTH_LONG).show()

                // 7. Route to LoginActivity
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
            } catch (e: Exception) {
                android.util.Log.e("Logout", "Error during performLogout", e)
                try {
                    stopLockTask()
                } catch (_: Exception) {}
                finish()
            }
        }
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
                                            synchronized(DBManager.personList) {
                                                if (!faceData.id.isNullOrEmpty()) {
                                                    existingPerson = DBManager.personList.find { it.id == faceData.id }
                                                }
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
                                            val templates = if (templatesB64.isNullOrEmpty()) null else try { Base64.decode(templatesB64, Base64.NO_WRAP) } catch (e: Exception) { null }
                                            val faceImageBytes = if (faceB64.isNullOrEmpty()) null else try { Base64.decode(faceB64, Base64.NO_WRAP) } catch (e: Exception) { null }
                                            val faceBitmap = if (faceImageBytes != null) try { BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size) } catch (e: Exception) { null } else null

                                            val currentPerson = existingPerson
                                            if (currentPerson == null) {
                                                dbManager.insertPerson(id, faceData.name, faceBitmap, templates, phone, dept, desig, shift, customDataStr, true)
                                                newFacesCount++
                                            } else {
                                                val effectiveId = if (!id.isNullOrEmpty()) id else (currentPerson.id ?: "")
                                                val needsMetadataUpdate =
                                                    currentPerson.phone != phone ||
                                                        currentPerson.department != dept ||
                                                        currentPerson.designation != desig ||
                                                        currentPerson.shift != shift ||
                                                        currentPerson.customData != customDataStr ||
                                                        (currentPerson.id != id && !id.isNullOrEmpty())

                                                var needsFaceUpdate = false
                                                try {
                                                    if (!java.util.Arrays.equals(currentPerson.templates, templates)) {
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
                                    val localPersonsCopy = synchronized(DBManager.personList) {
                                        ArrayList(DBManager.personList)
                                    }
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

    private var consecutiveOutsideCount = 0

    private fun sendHeartbeat() {
        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val token = prefs.getString("token", null)
            if (token.isNullOrBlank()) return

            val battery = Utils.getBatteryLevel(applicationContext)
            val did = android.provider.Settings.Secure.getString(contentResolver, android.provider.Settings.Secure.ANDROID_ID)
            
            val body = JsonObject()
            body.addProperty("device_id", did)
            body.addProperty("battery_level", battery)

            val apiCall = { finalBody: JsonObject ->
                RetrofitClient.getService().sendHeartbeat(finalBody).enqueue(object : Callback<JsonObject> {
                    override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                        if (response.isSuccessful) {
                            val resBody = response.body()
                            val geofenceStatus = resBody?.get("geofence_status")?.asString
                            android.util.Log.d("Heartbeat", "Sent successfully: $battery%, geofence=$geofenceStatus")
                            val distance = if (resBody != null && resBody.has("distance_meters") && !resBody.get("distance_meters").isJsonNull) {
                                resBody.get("distance_meters").asDouble
                            } else null

                            if (resBody != null && resBody.has("anchor_lat") && !resBody.get("anchor_lat").isJsonNull) {
                                anchorLat = resBody.get("anchor_lat").asDouble
                            } else {
                                anchorLat = null
                            }
                            if (resBody != null && resBody.has("anchor_lng") && !resBody.get("anchor_lng").isJsonNull) {
                                anchorLng = resBody.get("anchor_lng").asDouble
                            } else {
                                anchorLng = null
                            }
                            if (resBody != null && resBody.has("radius_meters") && !resBody.get("radius_meters").isJsonNull) {
                                anchorRadius = resBody.get("radius_meters").asDouble
                            } else {
                                anchorRadius = null
                            }

                            // Cache anchor locally for zero-latency local geofence checking
                            try {
                                val prefsEdit = getSharedPreferences("app_prefs", MODE_PRIVATE).edit()
                                if (anchorLat != null && anchorLng != null && anchorRadius != null && anchorRadius!! > 0.0) {
                                    prefsEdit.putString("anchor_lat", anchorLat.toString())
                                    prefsEdit.putString("anchor_lng", anchorLng.toString())
                                    prefsEdit.putString("anchor_radius", anchorRadius.toString())
                                } else {
                                    prefsEdit.remove("anchor_lat")
                                    prefsEdit.remove("anchor_lng")
                                    prefsEdit.remove("anchor_radius")
                                }
                                prefsEdit.apply()
                            } catch (_: Exception) {}

                            val lat = if (finalBody.has("latitude")) finalBody.get("latitude").asDouble else null
                            val lng = if (finalBody.has("longitude")) finalBody.get("longitude").asDouble else null
                            runOnUiThread {
                                updateGeofenceBadge(geofenceStatus, distance, lat, lng)
                            }

                            if (resBody != null && resBody.has("geofence_status")) {
                                if (geofenceStatus == "outside") {
                                    android.util.Log.w("Heartbeat", "Device reported OUTSIDE geofence (dist=$distance m) -> INSTANT LOGOUT")
                                    performLogout("Device moved outside allowed geofence area.")
                                } else if (geofenceStatus == "gps_required") {
                                    android.util.Log.w("Heartbeat", "Server geofencing active but no GPS coordinates provided by device")
                                }
                            }
                        }
                    }
                    override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                        android.util.Log.e("Heartbeat", "Failed to send heartbeat", t)
                        val lat = if (finalBody.has("latitude")) finalBody.get("latitude").asDouble else null
                        val lng = if (finalBody.has("longitude")) finalBody.get("longitude").asDouble else null
                        runOnUiThread {
                            updateGeofenceBadge(null, null, lat, lng)
                        }
                    }
                })
            }

            val hasLocationPerm = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

            if (hasLocationPerm) {
                // 1. Resolve best available cached or continuous location
                var bestLoc = latestDeviceLocation
                if (bestLoc == null) {
                    try {
                        val candidates = mutableListOf<Location>()
                        locationManager?.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let { candidates.add(it) }
                        locationManager?.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)?.let { candidates.add(it) }
                        locationManager?.getLastKnownLocation(LocationManager.PASSIVE_PROVIDER)?.let { candidates.add(it) }
                        bestLoc = candidates.maxByOrNull { it.time }
                    } catch (_: Exception) {}
                }

                // If still null, check persisted prefs
                if (bestLoc == null) {
                    val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                    val sLat = prefs.getString("last_valid_lat", null)?.toDoubleOrNull()
                    val sLng = prefs.getString("last_valid_lng", null)?.toDoubleOrNull()
                    if (sLat != null && sLng != null) {
                        bestLoc = Location("prefs").apply {
                            latitude = sLat
                            longitude = sLng
                        }
                    }
                }

                if (bestLoc != null) {
                    updateBestLocation(bestLoc)
                    body.addProperty("latitude", bestLoc.latitude)
                    body.addProperty("longitude", bestLoc.longitude)
                    body.addProperty("accuracy", bestLoc.accuracy)
                }

                // 2. Also attempt fresh high-accuracy fix from Google Fused Location
                try {
                    fusedLocationClient.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, null)
                        .addOnSuccessListener { freshLoc ->
                            if (freshLoc != null) {
                                updateBestLocation(freshLoc)
                                body.addProperty("latitude", freshLoc.latitude)
                                body.addProperty("longitude", freshLoc.longitude)
                                body.addProperty("accuracy", freshLoc.accuracy)
                            }
                            apiCall(body)
                        }
                        .addOnFailureListener {
                            apiCall(body)
                        }
                } catch (e: Exception) {
                    apiCall(body)
                }
            } else {
                apiCall(body)
            }

        } catch (e: Exception) {
            e.printStackTrace()
        }
    }


    private fun facesSignature(faces: List<com.faceplugin.facerecognition.api.SyncRequest>): String {
        val sb = StringBuilder()
        sb.append(faces.size).append('|')
        for (i in 0 until faces.size) {
            val f = faces[i]
            sb.append(f.id ?: "").append(':').append(f.name ?: "").append('|')
        }
        val bytes = MessageDigest.getInstance("SHA-256").digest(sb.toString().toByteArray(Charsets.UTF_8))
        val out = StringBuilder(bytes.size * 2)
        for (b in bytes) out.append(String.format("%02x", b))
        return out.toString()
    }

    private fun checkDeviceSlotAssignment() {
        val deviceId = android.provider.Settings.Secure.getString(contentResolver, android.provider.Settings.Secure.ANDROID_ID)
        RetrofitClient.getService().getMobileDeviceInfo().enqueue(object : Callback<com.google.gson.JsonObject> {
            override fun onResponse(call: Call<com.google.gson.JsonObject>, infoResp: Response<com.google.gson.JsonObject>) {
                val body = infoResp.body()
                val assigned = if (body != null && body.has("device_name") && !body.get("device_name").isJsonNull) {
                    body.get("device_name").asString
                } else null

                if (!assigned.isNullOrBlank()) {
                    val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                    prefs.edit().putString("device_name", assigned).apply()
                    val tvPlace = findViewById<TextView>(R.id.tv_device_name)
                    if (tvPlace != null) tvPlace.text = "— $assigned"
                } else {
                    fetchSlotsAndPick(false)
                }
            }
            override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {
                // If offline or error, we might just have to skip for now
            }
        })
    }

    private fun fetchSlotsAndPick(includeDeleted: Boolean) {
        val deviceId = android.provider.Settings.Secure.getString(contentResolver, android.provider.Settings.Secure.ANDROID_ID)
        RetrofitClient.getService().getMobileDeviceSlots(includeDeleted).enqueue(object : Callback<com.google.gson.JsonObject> {
            override fun onResponse(call: Call<com.google.gson.JsonObject>, resp: Response<com.google.gson.JsonObject>) {
                val arr = resp.body()?.getAsJsonArray("slots")
                val slots = mutableListOf<String>()
                if (arr != null && !arr.isJsonNull) {
                    for (el in arr) {
                        if (el != null && !el.isJsonNull) {
                             try { slots.add(el.asString) } catch (_: Exception) {}
                        }
                    }
                }
                if (slots.isNotEmpty()) {
                    showSlotSelectionDialog(slots, { selected ->
                        val obj = JsonObject()
                        obj.addProperty("device_id", deviceId)
                        obj.addProperty("slot_name", selected)
                        RetrofitClient.getService().assignMobileDeviceSlot(obj).enqueue(object : Callback<com.google.gson.JsonObject> {
                            override fun onResponse(call: Call<com.google.gson.JsonObject>, resp2: Response<com.google.gson.JsonObject>) {
                                val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                                prefs.edit().putString("device_name", selected).apply()
                                val tvPlace = findViewById<TextView>(R.id.tv_device_name)
                                if (tvPlace != null) tvPlace.text = "— $selected"
                                Toast.makeText(this@MainActivity, "Place assigned: $selected", Toast.LENGTH_SHORT).show()
                            }
                            override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {
                                Toast.makeText(this@MainActivity, "Failed to assign place", Toast.LENGTH_SHORT).show()
                            }
                        })
                    }, if (!includeDeleted) { { fetchSlotsAndPick(true) } } else null)
                }
            }
            override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {}
        })
    }

    private fun showSlotSelectionDialog(options: List<String>, onChosen: (String) -> Unit, onMore: (() -> Unit)? = null) {
        val builder = androidx.appcompat.app.AlertDialog.Builder(this)
        builder.setTitle("Select Device Place")
        var selectedIndex = 0
        val arr = options.toTypedArray()
        builder.setSingleChoiceItems(arr, 0) { _, which -> selectedIndex = which }
        builder.setPositiveButton("Confirm") { dialog, _ ->
            onChosen.invoke(arr[selectedIndex])
            dialog.dismiss()
        }
        if (onMore != null) {
            builder.setNeutralButton("More options") { dialog, _ ->
                onMore.invoke()
                dialog.dismiss()
            }
        }
        builder.setCancelable(false)
        builder.show()
    }

    private var isKioskModeActive = false

    private fun startKioskLockdown() {
        try {
            applyImmersiveMode()
            startLockTask()
            isKioskModeActive = true
            val btnKiosk = findViewById<ImageButton>(R.id.btn_kiosk)
            btnKiosk?.setColorFilter(ContextCompat.getColor(this, R.color.status_success))
            Toast.makeText(this, "Kiosk Lockdown Mode Activated", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            e.printStackTrace()
            applyImmersiveMode()
            isKioskModeActive = true
            val btnKiosk = findViewById<ImageButton>(R.id.btn_kiosk)
            btnKiosk?.setColorFilter(ContextCompat.getColor(this, R.color.status_success))
            Toast.makeText(this, "Kiosk Mode Activated", Toast.LENGTH_SHORT).show()
        }
    }

    private fun stopKioskLockdown() {
        try {
            stopLockTask()
        } catch (e: Exception) {
            e.printStackTrace()
        }
        isKioskModeActive = false
        clearImmersiveMode()
        val btnKiosk = findViewById<ImageButton>(R.id.btn_kiosk)
        btnKiosk?.setColorFilter(ContextCompat.getColor(this, R.color.vision_cyan))
    }

    private fun applyImmersiveMode() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.let {
                it.hide(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.navigationBars())
                it.systemBarsBehavior = android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                or android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or android.view.View.SYSTEM_UI_FLAG_FULLSCREEN
            )
        }
    }

    private fun clearImmersiveMode() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.show(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.navigationBars())
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = android.view.View.SYSTEM_UI_FLAG_VISIBLE
        }
    }

    private fun promptKioskPin(onSuccess: () -> Unit) {
        val input = android.widget.EditText(this)
        input.inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD
        input.hint = "Enter PIN (Default: 8888)"
        input.setPadding(48, 32, 48, 32)

        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Kiosk Lockdown Mode")
            .setMessage("Enter the Master SuperAdmin PIN to unlock this tablet:")
            .setView(input)
            .setPositiveButton("Unlock") { dialog, _ ->
                val entered = input.text.toString().trim()
                val masterPin = getSharedPreferences("app_prefs", MODE_PRIVATE).getString("kiosk_pin", "8888") ?: "8888"
                if (entered == masterPin) {
                    dialog.dismiss()
                    onSuccess.invoke()
                } else {
                    Toast.makeText(this, "Incorrect PIN. Contact SuperAdmin.", Toast.LENGTH_LONG).show()
                }
            }
            .setNegativeButton("Cancel") { dialog, _ -> dialog.dismiss() }
            .setCancelable(false)
            .show()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && isKioskModeActive) {
            applyImmersiveMode()
        }
    }

    private fun startLocationTracking() {
        val hasFine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) return

        try {
            if (locationManager == null) {
                locationManager = getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            }

            val isGpsEnabled = locationManager?.isProviderEnabled(LocationManager.GPS_PROVIDER) ?: false
            val isNetworkEnabled = locationManager?.isProviderEnabled(LocationManager.NETWORK_PROVIDER) ?: false

            if (!isGpsEnabled && !isNetworkEnabled) {
                runOnUiThread {
                    tvGeofenceStatus?.text = "LOCATION OFF"
                    val amber = ContextCompat.getColor(this, R.color.status_warning)
                    tvGeofenceStatus?.setTextColor(amber)
                    ivGeoIcon?.setColorFilter(amber)
                }
                promptEnableLocationSettings()
            }

            // 1. Check all cached providers immediately
            val candidates = mutableListOf<Location>()
            try {
                locationManager?.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let { candidates.add(it) }
                locationManager?.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)?.let { candidates.add(it) }
                locationManager?.getLastKnownLocation(LocationManager.PASSIVE_PROVIDER)?.let { candidates.add(it) }
            } catch (_: Exception) {}

            fusedLocationClient.lastLocation.addOnSuccessListener { fusedLoc ->
                if (fusedLoc != null) {
                    candidates.add(fusedLoc)
                }
                candidates.maxByOrNull { it.time }?.let { best ->
                    updateBestLocation(best)
                }
            }

            candidates.maxByOrNull { it.time }?.let { best ->
                updateBestLocation(best)
            }

            // Fallback to persisted location in app_prefs if available
            if (latestDeviceLocation == null) {
                val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                val sLat = prefs.getString("last_valid_lat", null)?.toDoubleOrNull()
                val sLng = prefs.getString("last_valid_lng", null)?.toDoubleOrNull()
                if (sLat != null && sLng != null) {
                    val fallback = Location("prefs").apply {
                        latitude = sLat
                        longitude = sLng
                    }
                    updateBestLocation(fallback)
                }
            }

            // 2. Register FusedLocationProvider continuous updates
            try {
                val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 10000L)
                    .setMinUpdateIntervalMillis(5000L)
                    .build()

                if (locationCallback == null) {
                    locationCallback = object : LocationCallback() {
                        override fun onLocationResult(result: LocationResult) {
                            result.lastLocation?.let { loc ->
                                updateBestLocation(loc)
                            }
                        }
                    }
                }
                fusedLocationClient.requestLocationUpdates(locationRequest, locationCallback!!, Looper.getMainLooper())
            } catch (e: Exception) {
                android.util.Log.w("Location", "FusedLocationProvider updates error", e)
            }

            // 3. Register native LocationManager listeners as fallback
            if (nativeLocationListener == null) {
                nativeLocationListener = object : LocationListener {
                    override fun onLocationChanged(loc: Location) {
                        updateBestLocation(loc)
                    }
                    @Deprecated("Deprecated in Java")
                    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
                    override fun onProviderEnabled(provider: String) {}
                    override fun onProviderDisabled(provider: String) {}
                }
            }

            try {
                if (isGpsEnabled) {
                    locationManager?.requestLocationUpdates(LocationManager.GPS_PROVIDER, 10000L, 1f, nativeLocationListener!!)
                }
            } catch (_: Exception) {}

            try {
                if (isNetworkEnabled) {
                    locationManager?.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 10000L, 1f, nativeLocationListener!!)
                }
            } catch (_: Exception) {}

        } catch (e: Exception) {
            android.util.Log.e("Location", "Error in startLocationTracking", e)
        }
    }

    private fun updateBestLocation(loc: Location) {
        latestDeviceLocation = loc
        lastKnownLat = loc.latitude
        lastKnownLng = loc.longitude

        try {
            getSharedPreferences("app_prefs", MODE_PRIVATE).edit()
                .putString("last_valid_lat", loc.latitude.toString())
                .putString("last_valid_lng", loc.longitude.toString())
                .apply()
        } catch (_: Exception) {}

        // Instant local geofence check against anchor coordinates
        val aLat = anchorLat
        val aLng = anchorLng
        val aRadius = anchorRadius
        if (aLat != null && aLng != null && aRadius != null && aRadius > 0.0) {
            val distResults = FloatArray(1)
            Location.distanceBetween(loc.latitude, loc.longitude, aLat, aLng, distResults)
            val currentDist = distResults[0].toDouble()
            lastKnownDistance = currentDist

            if (currentDist > aRadius) {
                android.util.Log.w("Geofence", "INSTANT LOGOUT: Current distance $currentDist m exceeds radius $aRadius m")
                runOnUiThread {
                    updateGeofenceBadge("outside", currentDist, loc.latitude, loc.longitude)
                    performLogout("Device moved outside allowed geofence radius (${currentDist.toInt()}m > ${aRadius.toInt()}m).")
                }
                return
            } else {
                runOnUiThread {
                    updateGeofenceBadge("inside", currentDist, loc.latitude, loc.longitude)
                }
                return
            }
        }

        runOnUiThread {
            if (lastKnownGeofenceStatus == null || lastKnownGeofenceStatus == "no_gps" || lastKnownGeofenceStatus == "gps_required") {
                tvGeofenceStatus?.text = "GPS LOCKED"
                val green = ContextCompat.getColor(this, R.color.status_success)
                tvGeofenceStatus?.setTextColor(green)
                ivGeoIcon?.setColorFilter(green)
            }
        }
    }

    private fun stopLocationTracking() {
        try {
            locationCallback?.let { fusedLocationClient.removeLocationUpdates(it) }
            nativeLocationListener?.let { locationManager?.removeUpdates(it) }
        } catch (_: Exception) {}
    }

    private fun updateGeofenceBadge(status: String?, distance: Double?, lat: Double?, lng: Double?) {
        lastKnownGeofenceStatus = status
        lastKnownDistance = distance
        if (lat != null) lastKnownLat = lat
        if (lng != null) lastKnownLng = lng

        val tv = tvGeofenceStatus ?: return
        val iv = ivGeoIcon ?: return

        when (status) {
            "inside" -> {
                val distText = if (distance != null) "${distance.toInt()}m" else "OK"
                tv.text = "INSIDE ($distText)"
                val green = ContextCompat.getColor(this, R.color.status_success)
                tv.setTextColor(green)
                iv.setColorFilter(green)
            }
            "outside" -> {
                val distText = if (distance != null) "${distance.toInt()}m" else "ALERT"
                tv.text = "OUTSIDE ($distText)"
                val red = ContextCompat.getColor(this, R.color.status_error)
                tv.setTextColor(red)
                iv.setColorFilter(red)
            }
            "no_gps", "gps_required" -> {
                if (lastKnownLat != null && lastKnownLng != null) {
                    tv.text = "GPS LOCKED"
                    val green = ContextCompat.getColor(this, R.color.status_success)
                    tv.setTextColor(green)
                    iv.setColorFilter(green)
                } else {
                    tv.text = "NO GPS FIX"
                    val amber = ContextCompat.getColor(this, R.color.status_warning)
                    tv.setTextColor(amber)
                    iv.setColorFilter(amber)
                }
            }
            "disabled" -> {
                tv.text = "NO GEOFENCE"
                val gray = ContextCompat.getColor(this, R.color.vision_text_secondary)
                tv.setTextColor(gray)
                iv.setColorFilter(gray)
            }
            else -> {
                if (lastKnownLat != null && lastKnownLng != null) {
                    tv.text = "GPS LOCKED"
                    val green = ContextCompat.getColor(this, R.color.status_success)
                    tv.setTextColor(green)
                    iv.setColorFilter(green)
                } else {
                    tv.text = "GPS: ACQUIRING"
                    val amber = ContextCompat.getColor(this, R.color.status_warning)
                    tv.setTextColor(amber)
                    iv.setColorFilter(amber)
                }
            }
        }
    }

    private fun showGeofenceDetailsDialog() {
        val isGpsEnabled = locationManager?.isProviderEnabled(LocationManager.GPS_PROVIDER) ?: false
        val isNetworkEnabled = locationManager?.isProviderEnabled(LocationManager.NETWORK_PROVIDER) ?: false
        val isLocationOff = !isGpsEnabled && !isNetworkEnabled

        val hasFine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        val latStr = if (lastKnownLat != null) "%.5f".format(lastKnownLat) else "Waiting for GPS / WiFi signal..."
        val lngStr = if (lastKnownLng != null) "%.5f".format(lastKnownLng) else "Waiting for GPS / WiFi signal..."
        val distStr = if (lastKnownDistance != null) "${lastKnownDistance!!.toInt()} meters from anchor" else "N/A"

        val statusStr = when {
            isLocationOff -> "⚠️ Location is turned OFF in tablet Android Settings."
            !hasFine && !hasCoarse -> "⚠️ Location permission has not been granted."
            lastKnownGeofenceStatus == "inside" -> "🟢 Inside Authorized Geofence"
            lastKnownGeofenceStatus == "outside" -> "🔴 Outside Geofence (Violation)"
            lastKnownGeofenceStatus == "disabled" -> "⚪ Geofence Not Configured"
            lastKnownGeofenceStatus == "no_gps" || lastKnownGeofenceStatus == "gps_required" -> "🟡 Server waiting for GPS lock"
            lastKnownLat != null -> "🟢 GPS Signal Locked"
            else -> "🟡 Acquiring GPS / WiFi Satellite Signal..."
        }

        val providerInfo = "Providers: GPS=${if (isGpsEnabled) "ON" else "OFF"}, Network=${if (isNetworkEnabled) "ON" else "OFF"}"

        val builder = androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Kiosk Location & Geofence")
            .setMessage("Status:\n$statusStr\n\nCoordinates:\nLatitude: $latStr\nLongitude: $lngStr\n\nDistance to Anchor:\n$distStr\n\n$providerInfo")
            .setPositiveButton("Close") { dialog, _ -> dialog.dismiss() }

        if (isLocationOff) {
            builder.setNeutralButton("Turn On Location") { _, _ ->
                promptEnableLocationSettings()
            }
        } else if (!hasFine && !hasCoarse) {
            builder.setNeutralButton("Grant Permission") { _, _ ->
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION), 100)
            }
        }

        builder.show()
    }

    private fun promptEnableLocationSettings() {
        val hasFine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) return

        try {
            val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 10000L)
                .setMinUpdateIntervalMillis(5000L)
                .build()

            val builder = LocationSettingsRequest.Builder()
                .addLocationRequest(locationRequest)
                .setAlwaysShow(true)

            val client = LocationServices.getSettingsClient(this)
            val task = client.checkLocationSettings(builder.build())

            task.addOnSuccessListener {
                startLocationTracking()
            }

            task.addOnFailureListener { exception ->
                if (exception is ResolvableApiException) {
                    try {
                        exception.startResolutionForResult(this@MainActivity, REQUEST_CHECK_SETTINGS)
                    } catch (e: IntentSender.SendIntentException) {
                        e.printStackTrace()
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_CHECK_SETTINGS) {
            if (resultCode == RESULT_OK) {
                startLocationTracking()
            } else {
                Toast.makeText(this, "Device location must be turned on for geofencing.", Toast.LENGTH_LONG).show()
            }
        }
    }
}
