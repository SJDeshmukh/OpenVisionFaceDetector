package com.faceplugin.facerecognition

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.util.Size
import android.view.View
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.NonNull
import androidx.annotation.OptIn
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.faceplugin.faceengine.FaceBox
import com.faceplugin.faceengine.FaceDetectionParam
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.common.util.concurrent.ListenableFuture
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class ParentFaceVerificationActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "ParentFaceVerification"
        private const val CAMERA_PERMISSION_REQUEST = 1001
    }

    private lateinit var previewView: PreviewView
    private lateinit var faceView: FaceView
    private lateinit var tvStatus: TextView
    private lateinit var tvActionBadge: TextView
    private lateinit var btnClose: ImageView
    private lateinit var progressBar: ProgressBar

    private var action: String = "approved"
    private var requestId: Int = -1
    private var studentNumber: String = ""

    private var savedTemplate: ByteArray? = null
    private var cameraExecutorService: ExecutorService? = null
    private var cameraProvider: ProcessCameraProvider? = null
    private var toneGen: ToneGenerator? = null

    private var activeLensFacing = CameraSelector.LENS_FACING_FRONT
    @Volatile private var isVerifiedOrSubmitting = false
    private var consecutiveNonMatches = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_parent_face_verification)

        previewView = findViewById(R.id.preview)
        faceView = findViewById(R.id.faceView)
        tvStatus = findViewById(R.id.tvVerificationStatus)
        tvActionBadge = findViewById(R.id.tvActionBadge)
        btnClose = findViewById(R.id.btnClose)
        progressBar = findViewById(R.id.progressBar)

        action = intent.getStringExtra("action") ?: "approved"
        requestId = intent.getIntExtra("request_id", -1)
        studentNumber = intent.getStringExtra("student_number") ?: ""

        val actionText = if (action == "rejected") "REJECT LEAVE" else "APPROVE LEAVE"
        tvActionBadge.text = "ACTION: $actionText"
        if (action == "rejected") {
            tvActionBadge.setTextColor(ContextCompat.getColor(this, R.color.vision_error))
        }

        btnClose.setOnClickListener {
            finish()
        }

        // Initialize local face engine
        val initResult = LocalFaceEngineFacade.ensureInitialized(applicationContext)
        if (initResult != LocalFaceEngineFacade.SUCCESS) {
            Toast.makeText(this, "Local face models could not be loaded ($initResult)", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        // Initialize parent face template
        val prefs = getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val templateB64 = prefs.getString("parent_face_template", "") ?: ""
        if (templateB64.isEmpty()) {
            Toast.makeText(this, "Please register your face first to approve/reject leaves", Toast.LENGTH_LONG).show()
            startActivity(Intent(this, ParentFaceRegistrationActivity::class.java))
            finish()
            return
        }

        try {
            savedTemplate = Base64.decode(templateB64, Base64.NO_WRAP)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to decode saved parent template", e)
            Toast.makeText(this, "Stored face template corrupted. Please re-register face.", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        try {
            toneGen = ToneGenerator(AudioManager.STREAM_ALARM, 100)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to init ToneGenerator", e)
        }

        cameraExecutorService = Executors.newSingleThreadExecutor()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_DENIED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), CAMERA_PERMISSION_REQUEST)
        } else {
            previewView.post { setUpCamera() }
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CAMERA_PERMISSION_REQUEST && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            previewView.post { setUpCamera() }
        } else {
            Toast.makeText(this, "Camera permission is required for face verification", Toast.LENGTH_SHORT).show()
            finish()
        }
    }

    private fun setUpCamera() {
        if (isFinishing || !LocalFaceEngineFacade.isInitialized) return
        val cameraProviderFuture: ListenableFuture<ProcessCameraProvider> = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            try {
                cameraProvider = cameraProviderFuture.get()
                bindCameraUseCases()
            } catch (e: Exception) {
                Log.e(TAG, "Unable to obtain CameraX provider", e)
            }
        }, ContextCompat.getMainExecutor(this))
    }

    @SuppressLint("RestrictedApi", "UnsafeExperimentalUsageError", "UnsafeOptInUsageError")
    private fun bindCameraUseCases() {
        val provider = cameraProvider ?: return
        provider.unbindAll()

        var selector = CameraSelector.Builder().requireLensFacing(activeLensFacing).build()
        try {
            if (!provider.hasCamera(selector)) {
                val fallbackLens = if (activeLensFacing == CameraSelector.LENS_FACING_FRONT)
                    CameraSelector.LENS_FACING_BACK else CameraSelector.LENS_FACING_FRONT
                val fallback = CameraSelector.Builder().requireLensFacing(fallbackLens).build()
                if (provider.hasCamera(fallback)) {
                    selector = fallback
                    activeLensFacing = fallbackLens
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error checking camera lens facing", e)
        }

        val preview = Preview.Builder().build()

        val imageAnalyzer = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()
        imageAnalyzer.setAnalyzer(cameraExecutorService!!, FaceAnalyzer())

        try {
            provider.bindToLifecycle(this, selector, preview, imageAnalyzer)
            preview.setSurfaceProvider(previewView.surfaceProvider)
        } catch (e: Exception) {
            Log.e(TAG, "Unable to bind camera use cases", e)
        }
    }

    private inner class FaceAnalyzer : ImageAnalysis.Analyzer {
        @OptIn(markerClass = [ExperimentalGetImage::class])
        override fun analyze(imageProxy: ImageProxy) {
            analyzeImage(imageProxy)
        }
    }

    @OptIn(markerClass = [ExperimentalGetImage::class])
    private fun analyzeImage(imageProxy: ImageProxy) {
        if (isVerifiedOrSubmitting) {
            imageProxy.close()
            return
        }

        try {
            val mediaImage = imageProxy.image ?: return
            val nv21 = Utils.yuv420ToNv21(mediaImage)
            val rotationDegrees = imageProxy.imageInfo.rotationDegrees
            val cameraMode = Utils.getCameraMode(rotationDegrees, activeLensFacing)
            val bitmap = LocalFaceEngineFacade.yuv2Bitmap(nv21, mediaImage.width, mediaImage.height, cameraMode) ?: return

            val param: FaceDetectionParam = FacePipeline.secureDetectionParams(this)
            val faceBoxes: List<FaceBox> = LocalFaceEngineFacade.faceDetection(bitmap, param)

            runOnUiThread {
                faceView.setFrameSize(Size(bitmap.width, bitmap.height))
                faceView.setFaceBoxes(faceBoxes)
            }

            if (faceBoxes.isNotEmpty()) {
                val faceBox = faceBoxes[0]
                if (FacePipeline.recognitionReady(this, faceBox, bitmap.width, bitmap.height)) {
                    val template = LocalFaceEngineFacade.templateExtraction(bitmap, faceBox)
                    val parentTemplate = savedTemplate

                    if (template != null && parentTemplate != null) {
                        val similarity = LocalFaceEngineFacade.similarityCalculation(template, parentTemplate)
                        val threshold = SettingsActivity.getIdentifyThreshold(this)

                        if (similarity >= threshold) {
                            // MATCHED!
                            isVerifiedOrSubmitting = true
                            consecutiveNonMatches = 0

                            runOnUiThread {
                                faceView.setRecognizedName("Parent Verified")
                                tvStatus.text = "Parent Identity Verified! Submitting decision..."
                                progressBar.visibility = View.VISIBLE
                            }

                            playAttendanceBeep()
                            submitVerificationDecision(bitmap, faceBox)
                            return
                        } else {
                            consecutiveNonMatches++
                            runOnUiThread {
                                faceView.setRecognizedName("Unrecognized Face")
                                if (consecutiveNonMatches > 10) {
                                    tvStatus.text = "Face does not match registered parent. Please face camera clearly."
                                }
                            }
                        }
                    }
                } else {
                    runOnUiThread {
                        faceView.setRecognizedName(null)
                    }
                }
            } else {
                runOnUiThread {
                    faceView.setRecognizedName(null)
                    tvStatus.text = "Look directly at the front camera to authenticate..."
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Image analysis error", e)
        } finally {
            imageProxy.close()
        }
    }

    private fun playAttendanceBeep() {
        Thread {
            try {
                val loudToneGen = ToneGenerator(AudioManager.STREAM_ALARM, 100)
                loudToneGen.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 150)
                Thread.sleep(200)
                loudToneGen.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 150)
                Thread.sleep(200)
                loudToneGen.release()
            } catch (e: Exception) {
                Log.e(TAG, "Error playing confirmation tone", e)
            }
        }.start()
    }

    private fun submitVerificationDecision(bitmap: Bitmap, faceBox: FaceBox) {
        Thread {
            try {
                // Ensure camera is stopped to save battery & prevent frame conflicts
                runOnUiThread {
                    try { cameraProvider?.unbindAll() } catch (_: Exception) {}
                }

                // Crop and prepare captured face photo for submission & display in flow
                val facePhoto = try {
                    Utils.cropFace(bitmap, faceBox) ?: bitmap
                } catch (_: Exception) {
                    bitmap
                }
                val resizedBitmap = Utils.resizeBitmap(facePhoto, 360)
                val encodedImage = encodeBitmapToBase64(resizedBitmap)

                val body = JsonObject().apply {
                    addProperty("request_id", requestId)
                    addProperty("student_number", studentNumber)
                    addProperty("action", action)
                    addProperty("captured_face", "data:image/jpeg;base64,$encodedImage")
                }

                RetrofitClient.getService().parentApproveLeave(body).enqueue(object : Callback<JsonObject> {
                    override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                        runOnUiThread { progressBar.visibility = View.GONE }
                        val isSuccess = response.isSuccessful && response.body()?.get("status")?.asString == "success"
                        if (isSuccess) {
                            runOnUiThread {
                                val decision = if (action == "approved") "approved" else "rejected"
                                Toast.makeText(this@ParentFaceVerificationActivity, "Leave $decision successfully!", Toast.LENGTH_LONG).show()
                                setResult(RESULT_OK)
                                finish()
                            }
                        } else {
                            val errorMsg = try {
                                response.errorBody()?.string() ?: response.message()
                            } catch (_: Exception) {
                                response.message()
                            }
                            runOnUiThread {
                                Toast.makeText(this@ParentFaceVerificationActivity, "Action failed: $errorMsg", Toast.LENGTH_LONG).show()
                                isVerifiedOrSubmitting = false
                                bindCameraUseCases()
                            }
                        }
                    }

                    override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                        runOnUiThread {
                            progressBar.visibility = View.GONE
                            Toast.makeText(this@ParentFaceVerificationActivity, "Network error: ${t.message}", Toast.LENGTH_LONG).show()
                            isVerifiedOrSubmitting = false
                            bindCameraUseCases()
                        }
                    }
                })
            } catch (e: Exception) {
                Log.e(TAG, "Error submitting verification decision", e)
                runOnUiThread {
                    progressBar.visibility = View.GONE
                    isVerifiedOrSubmitting = false
                    Toast.makeText(this@ParentFaceVerificationActivity, "Error submitting decision", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    private fun encodeBitmapToBase64(bitmap: Bitmap): String {
        val baos = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, 75, baos)
        return Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
    }

    override fun onDestroy() {
        super.onDestroy()
        toneGen?.release()
        cameraExecutorService?.shutdown()
    }
}
