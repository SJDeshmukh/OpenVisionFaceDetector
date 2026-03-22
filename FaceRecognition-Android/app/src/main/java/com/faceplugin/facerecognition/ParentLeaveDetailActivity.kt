package com.faceplugin.facerecognition

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Bundle
import android.util.Base64
import android.view.View
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.constraintlayout.widget.ConstraintLayout
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.io.ByteArrayOutputStream

class ParentLeaveDetailActivity : AppCompatActivity() {

    private lateinit var tvStudentName: TextView
    private lateinit var tvReason: TextView
    private lateinit var tvStartDate: TextView
    private lateinit var tvEndDate: TextView
    private lateinit var btnApprove: Button
    private lateinit var btnReject: Button
    private lateinit var progressBar: ProgressBar

    private var pendingAction = ""
    private var leaveRequestId: Int = -1
    private var studentNumber: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_parent_leave_detail)

        tvStudentName = findViewById(R.id.tvStudentName)
        tvReason = findViewById(R.id.tvReason)
        tvStartDate = findViewById(R.id.tvStartDate)
        tvEndDate = findViewById(R.id.tvEndDate)
        btnApprove = findViewById(R.id.btnApprove)
        btnReject = findViewById(R.id.btnReject)
        progressBar = findViewById(R.id.verificationProgress)

        val leaveDataStr = intent.getStringExtra("leave_data")
        if (leaveDataStr != null) {
            try {
                val json = JSONObject(leaveDataStr)
                leaveRequestId = json.optInt("id", -1)
                studentNumber = getSharedPreferences("app_prefs", Context.MODE_PRIVATE).getString("parent_student_number", "") ?: ""
                
                tvStudentName.text = "ID: $studentNumber"
                tvReason.text = json.optString("reason", "No Reason Provided")
                tvStartDate.text = json.optString("start_date", "-")
                tvEndDate.text = json.optString("end_date", "-")
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }

        btnApprove.setOnClickListener {
            startVerification("approved")
        }

        btnReject.setOnClickListener {
            startVerification("rejected")
        }
    }

    private fun startVerification(action: String) {
        pendingAction = action
        val intent = Intent(this, CaptureActivity::class.java)
        intent.putExtra("is_capture_only", true)
        intent.putExtra("force_front_camera", true)
        cameraLauncher.launch(intent)
    }

    private val cameraLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val imageUriString = result.data?.getStringExtra("image_uri")
            if (imageUriString != null) {
                val imageUri = android.net.Uri.parse(imageUriString)
                processCapturedImage(imageUri)
            }
        }
    }

    private fun processCapturedImage(imageUri: android.net.Uri) {
        progressBar.visibility = View.VISIBLE
        Thread {
            try {
                val bitmap = Utils.getCorrectlyOrientedImage(this, imageUri)
                if (bitmap != null) {
                    runOnUiThread {
                        val faces = FaceSDKWrapper.faceDetection(bitmap, null)
                        if (faces.isNotEmpty()) {
                            val faceBox = faces[0]
                            val liveEmbedding = FaceSDKWrapper.templateExtraction(bitmap, faceBox)
                            if (liveEmbedding != null) {
                                verifyAndSubmit(liveEmbedding, bitmap)
                            } else {
                                progressBar.visibility = View.GONE
                                Toast.makeText(this, "Failed to extract features", Toast.LENGTH_SHORT).show()
                            }
                        } else {
                            progressBar.visibility = View.GONE
                            Toast.makeText(this, "No face detected in captured image", Toast.LENGTH_SHORT).show()
                        }
                    }
                } else {
                    runOnUiThread { progressBar.visibility = View.GONE }
                }
            } catch (e: Exception) {
                e.printStackTrace()
                runOnUiThread { progressBar.visibility = View.GONE }
            }
        }.start()
    }

    private fun verifyAndSubmit(liveEmbedding: ByteArray, bitmap: Bitmap) {
        val prefs = getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val savedTemplateB64 = prefs.getString("parent_face_template", "") ?: ""
        
        if (savedTemplateB64.isEmpty()) {
            runOnUiThread {
                progressBar.visibility = View.GONE
                Toast.makeText(this, "No registered face found. Please register your face first.", Toast.LENGTH_LONG).show()
            }
            return
        }

        try {
            val savedEmbedding = Base64.decode(savedTemplateB64, Base64.NO_WRAP)
            val similarity = FaceSDKWrapper.similarityCalculation(liveEmbedding, savedEmbedding)

            if (similarity >= 0.82f) {
                runOnUiThread { Toast.makeText(this, "Verified! Approving...", Toast.LENGTH_SHORT).show() }
                val encodedImage = encodeBitmapToBase64(bitmap)
                submitApproval(encodedImage)
            } else {
                runOnUiThread {
                    progressBar.visibility = View.GONE
                    Toast.makeText(this, "Face verification failed. Please try again.", Toast.LENGTH_LONG).show()
                }
            }
        } catch (e: Exception) {
            runOnUiThread {
                progressBar.visibility = View.GONE
                Toast.makeText(this, "Error during verification.", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun submitApproval(capturedFaceB64: String) {
        val body = JsonObject()
        body.addProperty("request_id", leaveRequestId)
        body.addProperty("student_number", studentNumber)
        body.addProperty("action", pendingAction)
        body.addProperty("local_verified", true)
        body.addProperty("captured_face", "data:image/jpeg;base64,$capturedFaceB64")

        RetrofitClient.getService().parentApproveLeave(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                runOnUiThread { progressBar.visibility = View.GONE }
                if (response.isSuccessful && response.body()?.get("status")?.asString == "success") {
                    Toast.makeText(this@ParentLeaveDetailActivity, "Leave $pendingAction successfully", Toast.LENGTH_SHORT).show()
                    finish()
                } else {
                    Toast.makeText(this@ParentLeaveDetailActivity, "Action failed: ${response.message()}", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                runOnUiThread {
                    progressBar.visibility = View.GONE
                    Toast.makeText(this@ParentLeaveDetailActivity, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            }
        })
    }

    private fun encodeBitmapToBase64(bitmap: Bitmap): String {
        val baos = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, 70, baos)
        return Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
    }
}
