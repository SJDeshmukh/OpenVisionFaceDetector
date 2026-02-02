package com.faceplugin.facerecognition

import android.content.Context
import android.graphics.BitmapFactory
import android.util.Base64
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.faceplugin.facerecognition.api.GreetingService
import com.faceplugin.facerecognition.api.RetrofitClient
import com.faceplugin.facerecognition.api.SyncRequest
import java.security.MessageDigest

class FaceDownloadWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    override fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
        val token = prefs.getString("token", null)
        if (baseUrl != null) RetrofitClient.setBaseUrl(baseUrl)
        if (token != null) RetrofitClient.setAuthToken(token)
        if (token.isNullOrBlank()) return Result.success()

        val service: GreetingService = RetrofitClient.getService()
        val resp = try {
            service.downloadFaces().execute()
        } catch (_: Exception) {
            return Result.retry()
        }

        if (!resp.isSuccessful) {
            val code = resp.code()
            if (code == 401 || code == 403) return Result.success()
            if (code == 408 || code == 429 || (code in 500..599)) return Result.retry()
            return Result.success()
        }

        val faces = resp.body()?.faces ?: emptyList()
        val signature = facesSignature(faces)
        val lastSig = prefs.getString("last_faces_signature", null)
        if (lastSig != null && lastSig == signature) return Result.success()
        prefs.edit().putString("last_faces_signature", signature).apply()

        val db = DBManager(applicationContext)
        for (faceData in faces) {
            try {
                val id = faceData.id ?: ""
                if (id.isBlank()) continue
                val templatesB64 = faceData.templates
                val faceB64 = faceData.faceImage
                if (templatesB64.isNullOrBlank() || faceB64.isNullOrBlank()) continue

                val templates = Base64.decode(templatesB64, Base64.NO_WRAP)
                val faceImageBytes = Base64.decode(faceB64, Base64.NO_WRAP)
                val faceBitmap = BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size) ?: continue

                val phone = faceData.phone ?: ""
                val dept = faceData.department ?: ""
                val desig = faceData.designation ?: ""
                val shift = faceData.shift ?: ""
                val name = faceData.name ?: ""
                val customDataStr = faceData.customData?.toString() ?: ""

                db.insertPerson(id, name, faceBitmap, templates, phone, dept, desig, shift, customDataStr, true)
            } catch (_: Exception) {
            }
        }

        return Result.success()
    }

    private fun facesSignature(faces: List<SyncRequest>): String {
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

    companion object {
        private const val UNIQUE_WORK_NAME = "face-download"
        fun scheduleImmediate(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val req = OneTimeWorkRequestBuilder<FaceDownloadWorker>()
                .setConstraints(constraints)
                .build()
            androidx.work.WorkManager.getInstance(context)
                .enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.KEEP, req)
        }
    }
}

