package com.faceplugin.facerecognition

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.view.View
import android.widget.Button
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.faceplugin.facerecognition.api.ParentRegisterFaceRequest
import com.faceplugin.facerecognition.api.RetrofitClient
import com.ocp.facesdk.FaceDetectionParam
import com.ocp.facesdk.FaceSDK
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.io.ByteArrayOutputStream

class ParentFaceRegistrationActivity : AppCompatActivity() {

    private lateinit var btnCaptureFace: Button
    private lateinit var progressBar: ProgressBar
    private lateinit var dbManager: DBManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_parent_face_registration)

        btnCaptureFace = findViewById(R.id.btnCaptureFace)
        progressBar = findViewById(R.id.progressBar)
        dbManager = DBManager(applicationContext)
        dbManager.loadPerson() // Ensure person list is populated for similarity checks

        btnCaptureFace.setOnClickListener {
            Toast.makeText(this, "Look straight into the camera", Toast.LENGTH_SHORT).show()
            val intent = Intent(this, CaptureActivity::class.java)
            intent.putExtra("is_capture_only", true)
            intent.putExtra("force_front_camera", true)
            cameraLauncher.launch(intent)
        }
    }

    // Launcher for CaptureActivity (the existing FaceSDK camera flow)
    private val cameraLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val imageUriString = result.data?.getStringExtra("image_uri")
            if (imageUriString != null) {
                val imageUri = Uri.parse(imageUriString)
                showLoading(true)
                Thread {
                    try {
                        val bitmap = Utils.getCorrectlyOrientedImage(this, imageUri)
                        if (bitmap != null) {
                            runOnUiThread { processImage(bitmap) }
                        } else {
                            runOnUiThread {
                                showLoading(false)
                                Toast.makeText(this, "Failed to load image bitmap", Toast.LENGTH_SHORT).show()
                            }
                        }
                    } catch (e: Exception) {
                        e.printStackTrace()
                        runOnUiThread {
                            showLoading(false)
                            Toast.makeText(this, "Failed to load image", Toast.LENGTH_SHORT).show()
                        }
                    }
                }.start()
            }
        }
    }

    private fun processImage(bitmap: Bitmap) {
        val param = FaceDetectionParam()
        param.check_liveness = true
        param.check_liveness_level = SettingsActivity.getLivenessLevel(this)
        
        val faces = FaceSDKWrapper.faceDetection(bitmap, param)

        if (faces.isEmpty()) {
            showLoading(false)
            Toast.makeText(this, getString(R.string.no_face_detected), Toast.LENGTH_SHORT).show()
        } else if (faces.size > 1) {
            showLoading(false)
            Toast.makeText(this, getString(R.string.multiple_face_detected), Toast.LENGTH_SHORT).show()
        } else {
            val faceBox = faces[0]
            
            // Liveness check
            if (faceBox.liveness < SettingsActivity.getLivenessThreshold(this)) {
                showLoading(false)
                Toast.makeText(this, "Real face required (Spoof detected)", Toast.LENGTH_SHORT).show()
                return
            }

            val template = FaceSDKWrapper.templateExtraction(bitmap, faceBox)
            
            if (template != null) {
                // Similarity check against local DB
                var maxSimilarity = 0f
                for (p in DBManager.personList) {
                    try {
                        val s = FaceSDKWrapper.similarityCalculation(template, p.templates)
                        if (s > maxSimilarity) maxSimilarity = s
                    } catch (e: Exception) {}
                }
                
                if (maxSimilarity > SettingsActivity.getIdentifyThreshold(this)) {
                    showLoading(false)
                    Toast.makeText(this, "Face already registered on this device", Toast.LENGTH_SHORT).show()
                    return
                }

                val faceImage = Utils.cropFace(bitmap, faceBox)
                val encodedImage = encodeBitmapToBase64(faceImage)
                val encodedTemplate = Base64.encodeToString(template, Base64.NO_WRAP)
                registerFace(encodedImage, encodedTemplate)
            } else {
                showLoading(false)
                Toast.makeText(this, "Failed to extract features", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun registerFace(faceImage: String, faceTemplate: String) {
        val prefs = getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val studentId = prefs.getString("parent_student_number", "") ?: ""
        
        val request = ParentRegisterFaceRequest(studentId, "data:image/jpeg;base64,$faceImage", faceTemplate)

        RetrofitClient.getService().parentRegisterFace(request).enqueue(object : Callback<com.google.gson.JsonObject> {
            override fun onResponse(call: Call<com.google.gson.JsonObject>, response: Response<com.google.gson.JsonObject>) {
                runOnUiThread { showLoading(false) }
                if (response.isSuccessful && response.body()?.get("status")?.asString == "success") {
                    val editor = prefs.edit()
                    editor.putBoolean("face_registered", true)
                    editor.putString("parent_face_template", faceTemplate)
                    editor.apply()
                    startActivity(Intent(this@ParentFaceRegistrationActivity, ParentActivity::class.java))
                    finish()
                } else {
                    var errorMsg = "Registration failed"
                    try {
                        val errorBody = response.errorBody()?.string()
                        if (!errorBody.isNullOrEmpty() && errorBody.contains("error")) {
                            val start = errorBody.indexOf("\"error\"") + 9
                            val end = errorBody.indexOf("\"", start)
                            if (start > 8 && end > start) {
                                errorMsg = errorBody.substring(start, end).replace("\\", "")
                            }
                        } else {
                            val bodyMsg = response.body()?.get("error")?.asString
                            if (!bodyMsg.isNullOrEmpty()) errorMsg = bodyMsg
                        }
                    } catch (e: Exception) {
                        e.printStackTrace()
                    }
                    runOnUiThread { Toast.makeText(this@ParentFaceRegistrationActivity, errorMsg, Toast.LENGTH_LONG).show() }
                }
            }

            override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {
                runOnUiThread {
                    showLoading(false)
                    Toast.makeText(this@ParentFaceRegistrationActivity, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            }
        })
    }

    private fun encodeBitmapToBase64(bitmap: Bitmap): String {
        val baos = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, 80, baos)
        return Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
    }

    private fun showLoading(isLoading: Boolean) {
        progressBar.visibility = if (isLoading) View.VISIBLE else View.GONE
        btnCaptureFace.isEnabled = !isLoading
    }
}
