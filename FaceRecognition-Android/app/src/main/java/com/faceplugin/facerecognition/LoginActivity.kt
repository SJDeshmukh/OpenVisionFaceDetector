package com.faceplugin.facerecognition

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.faceplugin.facerecognition.api.LoginRequest
import com.faceplugin.facerecognition.api.LoginResponse
import com.faceplugin.facerecognition.api.RetrofitClient
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

import android.widget.TextView
import android.view.View
import android.provider.Settings
import com.faceplugin.facerecognition.api.RegisterRequest
import java.security.MessageDigest
import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.widget.ImageView
import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

class LoginActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        // Show connected server (Debug info)
        Toast.makeText(this, "Connected to: " + RetrofitClient.getBaseUrl(), Toast.LENGTH_LONG).show()

        val etUsername = findViewById<EditText>(R.id.et_username)
        val etPassword = findViewById<EditText>(R.id.et_password)
        val btnLogin = findViewById<Button>(R.id.btn_login)
        val btnRegister = findViewById<TextView>(R.id.btn_register)
        val tvServerUrl = findViewById<TextView>(R.id.tv_server_url)
        val tvBusiness = findViewById<TextView>(R.id.tv_business_name)
        val btnParentLogin = findViewById<TextView>(R.id.btn_parent_login)

        val etStudentId = findViewById<EditText>(R.id.et_student_id)
        val etMobileNumber = findViewById<EditText>(R.id.et_mobile_number)
        var isParentLogin = false
        
        btnParentLogin.setOnClickListener {
            if (!isParentLogin) {
                isParentLogin = true
                etUsername.visibility = View.GONE
                etPassword.visibility = View.GONE
                btnRegister.visibility = View.GONE
                etStudentId.visibility = View.VISIBLE
                etMobileNumber.visibility = View.VISIBLE
                btnParentLogin.text = "Back to Staff Login"
                btnLogin.text = "Secure Parent Login"
            } else {
                isParentLogin = false
                etUsername.visibility = View.VISIBLE
                etPassword.visibility = View.VISIBLE
                btnRegister.visibility = View.VISIBLE
                etStudentId.visibility = View.GONE
                etMobileNumber.visibility = View.GONE
                btnParentLogin.text = "Parent Portal Login"
                btnLogin.text = "SIGN IN"
            }
        }

        // AttendX Customization
        if (BuildConfig.IS_ATTENDX) {
            // Default to Parent Login
            isParentLogin = true
            etUsername.visibility = View.GONE
            etPassword.visibility = View.GONE
            btnRegister.visibility = View.GONE
            etStudentId.visibility = View.VISIBLE
            etMobileNumber.visibility = View.VISIBLE
            btnParentLogin.visibility = View.GONE // Hide toggle
            btnLogin.text = "Sign in to AttendX"
        }

        try {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            var code = prefs.getString("selected_business_type_code", null)
            var label = prefs.getString("selected_business_type_label", null)
            if (code.isNullOrBlank()) {
                code = prefs.getString("selected_business_type", null)
            }
            val allowParentLogin = try {
                prefs.getBoolean("selected_allow_parent_login", code?.equals("school", true) == true)
            } catch (_: Exception) {
                code?.equals("school", true) == true
            }
            if (label.isNullOrBlank()) {
                label = when (code?.lowercase()) {
                    "school" -> "School / College"
                    "wages" -> "Daily Wages / Workforce"
                    "enterprise" -> "Enterprise (Custom)"
                    else -> code
                }
            }
            if (!code.isNullOrBlank()) {
                tvBusiness.text = "Business: $label"
                btnParentLogin.visibility = if (allowParentLogin) View.VISIBLE else View.GONE
            } else {
                tvBusiness.text = "Business: -"
                btnParentLogin.visibility = View.GONE
            }
        } catch (_: Exception) {
            tvBusiness.text = "Business: -"
            btnParentLogin.visibility = View.GONE
        }
        
        tvServerUrl.text = "Server: " + RetrofitClient.getBaseUrl()
        tvServerUrl.setOnClickListener {
            showServerUrlDialog()
        }

        btnLogin.setOnClickListener {
            haptic()
            if (isParentLogin) {
                val studentId = etStudentId.text.toString().trim()
                val mobile = etMobileNumber.text.toString().trim()
                if (studentId.isEmpty() || mobile.isEmpty()) {
                    Toast.makeText(this, "Enter Student ID and Mobile Number", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                
                val deviceId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
                val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                var vendorId = prefs.getInt("vendor_id", -1)
                if (vendorId == -1) vendorId = 1
                
                val request = com.faceplugin.facerecognition.api.ParentLoginRequest(studentId, mobile, deviceId, vendorId, "")
                
                RetrofitClient.getService().parentLogin(request).enqueue(object : Callback<LoginResponse> {
                    override fun onResponse(call: Call<LoginResponse>, response: Response<LoginResponse>) {
                        if (response.isSuccessful && response.body()?.status == "success") {
                             val token = response.body()?.token
                             val role = response.body()?.role
                             val vId = response.body()?.vendorId
                             val faceRegistered = response.body()?.faceRegistered ?: false
                             val faceTemplate = response.body()?.faceTemplate
                             
                             val vertical = response.body()?.getVertical()
                             val hasBulkAttendance = response.body()?.getHasBulkAttendance() ?: false
                             val appMode = try { response.body()?.let {
                                 val jo = com.google.gson.Gson().toJsonTree(it).asJsonObject
                                 jo.get("app_mode")?.asString
                             } } catch (_: Exception) { null }
                             val editor = prefs.edit()
                             if (token != null) editor.putString("token", token)
                             if (role != null) editor.putString("role", role)
                             if (vId != null) editor.putInt("vendor_id", vId)
                             editor.putBoolean("face_registered", faceRegistered)
                             if (faceTemplate != null) editor.putString("parent_face_template", faceTemplate)
                             editor.putString("student_id", studentId)
                             editor.putString("parent_student_number", studentId)
                             editor.putString("parent_mobile_number", mobile)
                             if (vertical != null) editor.putString("parent_vendor_vertical", vertical)
                             editor.putBoolean("parent_has_bulk_attendance", hasBulkAttendance)
                             if (appMode != null) editor.putString("parent_app_mode", appMode)
                             editor.apply()

                             if (token != null) RetrofitClient.setAuthToken(token)

                             runLogoShineThenNavigate()
                        } else {
                             var errorMsg = "Login Failed"
                             try {
                                 val errorBody = response.errorBody()?.string()
                                 if (!errorBody.isNullOrEmpty() && errorBody.contains("error")) {
                                     val start = errorBody.indexOf("\"error\"") + 9
                                     val end = errorBody.indexOf("\"", start)
                                     if (start > 8 && end > start) {
                                         errorMsg = errorBody.substring(start, end).replace("\\", "")
                                     }
                                 } else {
                                     errorMsg = response.body()?.error ?: "Invalid credentials"
                                 }
                             } catch (e: Exception) {
                                 e.printStackTrace()
                             }
                             Toast.makeText(this@LoginActivity, errorMsg, Toast.LENGTH_LONG).show()
                        }
                    }
                    override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                        Toast.makeText(this@LoginActivity, "Network Error: ${t.message}", Toast.LENGTH_SHORT).show()
                    }
                })
                return@setOnClickListener
            }

            val username = etUsername.text.toString().trim()
            val password = etPassword.text.toString().trim()

            if (username.isEmpty() || password.isEmpty()) {
                Toast.makeText(this, "Please enter username and password", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val deviceId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
            val request = LoginRequest(username, password, deviceId)

            val online = try {
                NetworkUtils.isOnline(applicationContext)
            } catch (_: Exception) {
                false
            }

            if (!online) {
                if (tryOfflineLogin(username, password)) {
                    val intent = Intent(this@LoginActivity, MainActivity::class.java)
                    startActivity(intent)
                    finish()
                } else {
                    Toast.makeText(this, "Offline: Login needs last successful credentials", Toast.LENGTH_SHORT).show()
                }
                return@setOnClickListener
            }

            RetrofitClient.getService().login(request).enqueue(object : Callback<LoginResponse> {
                override fun onResponse(call: Call<LoginResponse>, response: Response<LoginResponse>) {
                    if (response.isSuccessful && response.body()?.status == "success") {
                        val body = response.body()
                        val token = body?.token
                        val vendorId = body?.vendorId
                        val companyId = body?.companyId
                        val role = body?.role
                        
                        // Save login state
                        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                        val editor = prefs.edit()
                        editor.putString("username", username)
                        if (!role.isNullOrBlank()) editor.putString("role", role)
                        if (token != null) editor.putString("token", token)
                        if (vendorId != null) editor.putInt("vendor_id", vendorId)
                        if (companyId != null) editor.putInt("company_id", companyId)
                        try {
                            val vc = body?.vendorConfig
                            val cached = when {
                                vc == null || vc.isJsonNull -> null
                                vc.isJsonArray -> vc.asJsonArray.toString()
                                vc.isJsonObject -> {
                                    val obj = vc.asJsonObject
                                    val reg = obj.get("registration_config")
                                    when {
                                        reg != null && reg.isJsonArray -> reg.asJsonArray.toString()
                                        reg != null && reg.isJsonObject && reg.asJsonObject.get("fields")?.isJsonArray == true ->
                                            reg.asJsonObject.getAsJsonArray("fields").toString()
                                        else -> null
                                    }
                                }
                                else -> null
                            }
                            if (!cached.isNullOrBlank()) {
                                editor.putString("cached_registration_config", cached)
                            }
                        } catch (_: Exception) {}
                        editor.putString("offline_login_hash", offlineLoginHash(username, password))
                        editor.apply()

                        // Set token in RetrofitClient
                        if (token != null) {
                            RetrofitClient.setAuthToken(token)
                        }

                        // Prompt for device place on first run (or if admin configured slots and not yet confirmed)
                        try {
                            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                            val cachedName = prefs.getString("device_name", null)
                            val alreadyPrompted = try { prefs.getBoolean("place_onboarded", false) } catch (_: Exception) { false }
                            val deviceId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
                            
                            // Helper to fetch slots and show picker
                            fun fetchSlotsAndPick(includeDeleted: Boolean = false) {
                                RetrofitClient.getService().getMobileDeviceSlots(includeDeleted).enqueue(object: Callback<com.google.gson.JsonObject> {
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
                                                try {
                                                    val obj = com.google.gson.JsonObject()
                                                    obj.addProperty("device_id", deviceId)
                                                    obj.addProperty("slot_name", selected)
                                                    RetrofitClient.getService().assignMobileDeviceSlot(obj).enqueue(object: Callback<com.google.gson.JsonObject> {
                                                        override fun onResponse(call: Call<com.google.gson.JsonObject>, resp2: Response<com.google.gson.JsonObject>) {
                                                            try {
                                                                prefs.edit().putString("device_name", selected).apply()
                                                                prefs.edit().putBoolean("place_onboarded", true).apply()
                                                            } catch (_: Exception) {}
                                                            runLogoShineThenNavigate()
                                                        }
                                                        override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {
                                                            Toast.makeText(this@LoginActivity, "Slot assign failed: ${t.message}", Toast.LENGTH_SHORT).show()
                                                            runLogoShineThenNavigate()
                                                        }
                                                    })
                                                } catch (_: Exception) {
                                                    runLogoShineThenNavigate()
                                                }
                                            }, if (!includeDeleted) { { fetchSlotsAndPick(true) } } else null)
                                        } else {
                                            runLogoShineThenNavigate()
                                        }
                                    }
                                    override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {
                                        runLogoShineThenNavigate()
                                    }
                                })
                            }
                            
                            // Always run onboarding once per install (or when not yet confirmed)
                            // If role is user (kiosk), we MUST have a place.
                            val role = prefs.getString("role", "user")
                            if (!alreadyPrompted || (role == "user" && cachedName.isNullOrBlank())) {
                                RetrofitClient.getService().getMobileDeviceInfo().enqueue(object: Callback<com.google.gson.JsonObject> {
                                    override fun onResponse(call: Call<com.google.gson.JsonObject>, infoResp: Response<com.google.gson.JsonObject>) {
                                        val body = infoResp.body()
                                        val assigned = if (body != null && body.has("device_name") && !body.get("device_name").isJsonNull) {
                                            body.get("device_name").asString
                                        } else null

                                        if (!assigned.isNullOrBlank()) {
                                            // Sync local storage if server already has it
                                            prefs.edit().putString("device_name", assigned).apply()
                                            prefs.edit().putBoolean("place_onboarded", true).apply()
                                            
                                            val builder = androidx.appcompat.app.AlertDialog.Builder(this@LoginActivity)
                                            builder.setTitle("Device Place")
                                            builder.setMessage("This device is assigned to \"$assigned\". Use it or change?")
                                            builder.setPositiveButton("Use \"$assigned\"") { dialog, _ ->
                                                runLogoShineThenNavigate()
                                            }
                                            builder.setNegativeButton("Change Place") { dialog, _ ->
                                                fetchSlotsAndPick(false)
                                            }
                                            builder.setCancelable(false)
                                            builder.show()
                                        } else {
                                            // Not assigned: fetch available slots for selection
                                            fetchSlotsAndPick(false)
                                        }
                                    }
                                    override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {
                                        fetchSlotsAndPick(false)
                                    }
                                })
                                return
                            }
                        } catch (_: Exception) {}

                        runLogoShineThenNavigate()
                    } else {
                        var errorMsg = "Login failed"
                        try {
                            val errorBody = response.errorBody()?.string()
                            if (!errorBody.isNullOrEmpty() && errorBody.contains("error")) {
                                // Manual JSON parsing since we don't have a Gson helper ready here for error body
                                val start = errorBody.indexOf("\"error\"") + 9
                                val end = errorBody.indexOf("\"", start)
                                if (start > 8 && end > start) {
                                    errorMsg = errorBody.substring(start, end).replace("\\", "")
                                }
                            } else {
                                errorMsg = response.body()?.error ?: "Invalid credentials"
                            }
                        } catch (e: Exception) {
                            e.printStackTrace()
                        }
                        Toast.makeText(this@LoginActivity, errorMsg, Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                    if (tryOfflineLogin(username, password)) {
                        Toast.makeText(this@LoginActivity, "Offline: Using cached login", Toast.LENGTH_SHORT).show()
                        runLogoShineThenNavigate()
                    } else {
                        Toast.makeText(this@LoginActivity, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            })
        }

        btnRegister.setOnClickListener {
            val username = etUsername.text.toString().trim()
            val password = etPassword.text.toString().trim()

            if (username.isEmpty() || password.isEmpty()) {
                Toast.makeText(this, "Enter username and password to register", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val request = RegisterRequest(username, password, "user")
            RetrofitClient.getService().register(request).enqueue(object : Callback<LoginResponse> {
                override fun onResponse(call: Call<LoginResponse>, response: Response<LoginResponse>) {
                    if (response.isSuccessful && response.body()?.status == "success") {
                         Toast.makeText(this@LoginActivity, "Registration successful! Please Login.", Toast.LENGTH_LONG).show()
                    } else {
                        Toast.makeText(this@LoginActivity, "Registration failed: ${response.body()?.error ?: "Unknown error"}", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                    Toast.makeText(this@LoginActivity, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
        }

    }

    private fun showSlotSelectionDialog(options: List<String>, onChosen: (String) -> Unit, onMore: (() -> Unit)? = null) {
        if (options.isEmpty()) { onChosen.invoke(""); return }
        val builder = androidx.appcompat.app.AlertDialog.Builder(this)
        builder.setTitle("Select Device Place")
        var selectedIndex = 0
        val arr = options.toTypedArray()
        builder.setSingleChoiceItems(arr, 0) { _, which ->
            selectedIndex = which
        }
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
        builder.setNegativeButton("Cancel") { dialog, _ ->
            dialog.cancel()
        }
        builder.setCancelable(false)
        builder.show()
    }

    private fun runLogoShineThenNavigate() {
        try {
            val logo = findViewById<ImageView>(R.id.logo_login)
            val shine = findViewById<View>(R.id.logo_shine)
            if (logo != null && shine != null) {
                shine.visibility = View.VISIBLE
                shine.alpha = 0.0f
                // Position shine to start left outside logo bounds
                val width = logo.width.toFloat()
                val startX = -width * 0.6f
                val endX = width * 0.6f
                shine.translationX = startX
                // Animations: alpha up, slide across, alpha down
                val fadeIn = ObjectAnimator.ofFloat(shine, "alpha", 0f, 0.9f)
                fadeIn.duration = 120
                val slide = ObjectAnimator.ofFloat(shine, "translationX", startX, endX)
                slide.duration = 420
                val fadeOut = ObjectAnimator.ofFloat(shine, "alpha", 0.9f, 0f)
                fadeOut.duration = 120
                val set = AnimatorSet()
                set.playSequentially(fadeIn, slide, fadeOut)
                set.start()
                shine.postDelayed({
                    shine.visibility = View.GONE
                    val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                    val target = getTargetActivity(prefs)
                    val intent = Intent(this@LoginActivity, target)
                    startActivity(intent)
                    finish()
                }, 650)
            } else {
                val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                val target = getTargetActivity(prefs)
                val intent = Intent(this@LoginActivity, target)
                startActivity(intent)
                finish()
            }
        } catch (_: Exception) {
            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val target = getTargetActivity(prefs)
            val intent = Intent(this@LoginActivity, target)
            startActivity(intent)
            finish()
        }
    }

    private fun getTargetActivity(prefs: android.content.SharedPreferences): Class<*> {
        val role = prefs.getString("role", null)
        return if (role == "parent") {
            if (prefs.getBoolean("face_registered", false)) {
                ParentActivity::class.java
            } else {
                ParentFaceRegistrationActivity::class.java
            }
        } else if (role == "owner") {
            OwnerActivity::class.java
        } else {
            MainActivity::class.java
        }
    }

    private fun showServerUrlDialog() {
        val builder = androidx.appcompat.app.AlertDialog.Builder(this)
        builder.setTitle("Set Server URL")

        val input = EditText(this)
        input.setText(RetrofitClient.getBaseUrl())
        builder.setView(input)

        builder.setPositiveButton("Save") { dialog, which ->
            var url = input.text.toString().trim()
            if (url.isNotEmpty()) {
                val lower = url.lowercase()
                if (lower.contains(":5173")) {
                    Toast.makeText(this, "Enter backend URL like http://<LAN_IP>:5001", Toast.LENGTH_LONG).show()
                    return@setPositiveButton
                }
                if (!url.endsWith("/")) url += "/"
                RetrofitClient.setBaseUrl(url)
                
                val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                prefs.edit().putString("server_url", url).apply()
                
                findViewById<TextView>(R.id.tv_server_url).text = "Server: $url"
                Toast.makeText(this, "Server URL updated", Toast.LENGTH_SHORT).show()
            }
        }
        builder.setNegativeButton("Cancel") { dialog, which -> dialog.cancel() }

        builder.show()
    }

    @Suppress("DEPRECATION")
    private fun haptic() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
                vm.defaultVibrator.vibrate(VibrationEffect.createOneShot(40, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                val v = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    v.vibrate(VibrationEffect.createOneShot(40, VibrationEffect.DEFAULT_AMPLITUDE))
                } else {
                    v.vibrate(40)
                }
            }
        } catch (_: Exception) {}
    }

    private fun offlineLoginHash(username: String, password: String): String {
        val input = "$username:$password"
        val bytes = MessageDigest.getInstance("SHA-256").digest(input.toByteArray(Charsets.UTF_8))
        val sb = StringBuilder(bytes.size * 2)
        for (b in bytes) {
            sb.append(String.format("%02x", b))
        }
        return sb.toString()
    }

    private fun tryOfflineLogin(username: String, password: String): Boolean {
        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        val savedUser = prefs.getString("username", null)
        val savedHash = prefs.getString("offline_login_hash", null)
        if (savedUser.isNullOrBlank() || savedHash.isNullOrBlank()) return false
        if (savedUser != username) return false
        return savedHash == offlineLoginHash(username, password)
    }
}
