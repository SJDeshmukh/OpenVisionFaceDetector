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
                btnParentLogin.visibility = View.VISIBLE
            }
        } catch (_: Exception) {
            tvBusiness.text = "Business: -"
            btnParentLogin.visibility = View.VISIBLE
        }
        
        tvServerUrl.text = "Server: " + RetrofitClient.getBaseUrl()
        tvServerUrl.setOnClickListener {
            showServerUrlDialog()
        }

        btnLogin.setOnClickListener {
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
                        val token = response.body()?.token
                        val vendorId = response.body()?.vendorId
                        val companyId = response.body()?.companyId
                        
                        // Save login state
                        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
                        val editor = prefs.edit()
                        editor.putString("username", username)
                        if (token != null) editor.putString("token", token)
                        if (vendorId != null) editor.putInt("vendor_id", vendorId)
                        if (companyId != null) editor.putInt("company_id", companyId)
                        editor.putString("offline_login_hash", offlineLoginHash(username, password))
                        editor.apply()

                        // Set token in RetrofitClient
                        if (token != null) {
                            RetrofitClient.setAuthToken(token)
                        }

                        // Go to MainActivity
                        val intent = Intent(this@LoginActivity, MainActivity::class.java)
                        startActivity(intent)
                        finish()
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
                        val intent = Intent(this@LoginActivity, MainActivity::class.java)
                        startActivity(intent)
                        finish()
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

        findViewById<TextView>(R.id.btn_parent_login).visibility = View.GONE
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
