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

    // Launcher for CaptureActivity (the shared local-model camera flow)
    private val cameraLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val imageUriString = result.data?.getStringExtra("image_uri")
            val capturedTemplate = result.data?.getByteArrayExtra("face_template")
            val capturedVerified = result.data?.getBooleanExtra("face_verified", false) == true
            if (imageUriString != null) {
                val imageUri = Uri.parse(imageUriString)
                showLoading(true)
                Thread {
                    try {
                        val bitmap = Utils.getCorrectlyOrientedImage(this, imageUri)
                        if (bitmap != null) {
                            processImage(bitmap, capturedTemplate, capturedVerified)
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

    private fun processImage(bitmap: Bitmap, capturedTemplate: ByteArray?, capturedVerified: Boolean) {
        val faces = LocalFaceEngineFacade.faceDetection(bitmap, FacePipeline.secureDetectionParams(this))
        val hasCapturedTemplate = capturedVerified
            && capturedTemplate != null && capturedTemplate.isNotEmpty()

        if (faces.isEmpty() && !hasCapturedTemplate) {
            runOnUiThread {
                showLoading(false)
                Toast.makeText(this, getString(R.string.no_face_detected), Toast.LENGTH_SHORT).show()
            }
        } else if (faces.size > 1 && !hasCapturedTemplate) {
            runOnUiThread {
                showLoading(false)
                Toast.makeText(this, getString(R.string.multiple_face_detected), Toast.LENGTH_SHORT).show()
            }
        } else {
            val faceBox = faces.firstOrNull()
            
            // Liveness check
            if (!hasCapturedTemplate && !FacePipeline.recognitionReady(
                    this, faceBox, bitmap.width, bitmap.height)) {
                runOnUiThread {
                    showLoading(false)
                    Toast.makeText(this, "Real face required (Spoof detected)", Toast.LENGTH_SHORT).show()
                }
                return
            }

            val template = capturedTemplate?.takeIf { hasCapturedTemplate }
                ?: LocalFaceEngineFacade.templateExtraction(bitmap, faceBox)
            
            if (template != null) {
                // Similarity check against local DB
                var maxSimilarity = 0f
                val people = synchronized(DBManager.personList) { DBManager.personList.toTypedArray() }
                for (p in people) {
                    try {
                        val storedTemplate = p?.templates?.takeIf { it.isNotEmpty() } ?: continue
                        val s = LocalFaceEngineFacade.similarityCalculation(template, storedTemplate)
                        if (s > maxSimilarity) maxSimilarity = s
                    } catch (e: Exception) {}
                }
                
                if (maxSimilarity > SettingsActivity.getIdentifyThreshold(this)) {
                    runOnUiThread {
                        showLoading(false)
                        Toast.makeText(this, "Face already registered on this device", Toast.LENGTH_SHORT).show()
                    }
                    return
                }

                val faceImage = if (faceBox != null) Utils.cropFace(bitmap, faceBox) else bitmap
                val encodedImage = encodeBitmapToBase64(faceImage)
                val encodedTemplate = Base64.encodeToString(template, Base64.NO_WRAP)
                saveFaceLocally(encodedTemplate)
                if (NetworkUtils.isOnline(applicationContext)) {
                    registerFace(encodedImage, encodedTemplate)
                } else {
                    runOnUiThread { finishLocalRegistration("Face saved on this device") }
                }
            } else {
                runOnUiThread {
                    showLoading(false)
                    Toast.makeText(this, "Failed to extract features", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun saveFaceLocally(faceTemplate: String) {
        getSharedPreferences("app_prefs", Context.MODE_PRIVATE).edit()
            .putBoolean("face_registered", true)
            .putString("parent_face_template", faceTemplate)
            .apply()
    }

    private fun finishLocalRegistration(message: String) {
        showLoading(false)
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        startActivity(Intent(this, ParentActivity::class.java))
        finish()
    }

    private fun registerFace(faceImage: String, faceTemplate: String) {
        val prefs = getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val studentId = prefs.getString("parent_student_number", "") ?: ""
        
        val request = ParentRegisterFaceRequest(studentId, "data:image/jpeg;base64,$faceImage", faceTemplate)

        RetrofitClient.getService().parentRegisterFace(request).enqueue(object : Callback<com.google.gson.JsonObject> {
            override fun onResponse(call: Call<com.google.gson.JsonObject>, response: Response<com.google.gson.JsonObject>) {
                runOnUiThread { showLoading(false) }
                if (response.isSuccessful && response.body()?.get("status")?.asString == "success") {
                    finishLocalRegistration("Face saved and synced")
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
                    val syncMessage = "Face saved locally; cloud sync failed: $errorMsg"
                    runOnUiThread { finishLocalRegistration(syncMessage) }
                }
            }

            override fun onFailure(call: Call<com.google.gson.JsonObject>, t: Throwable) {
                runOnUiThread {
                    finishLocalRegistration("Face saved locally; cloud sync will need retrying")
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
