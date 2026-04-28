package com.faceplugin.facerecognition

import android.content.Context
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.Log
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.faceplugin.facerecognition.api.GreetingService
import com.faceplugin.facerecognition.api.RetrofitClient
import com.faceplugin.facerecognition.api.SyncRequest
import java.net.URL
import java.security.MessageDigest

class FaceDownloadWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {

    companion object {
        private const val TAG = "FaceDownloadWorker"
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
        } catch (e: Exception) {
            Log.w(TAG, "downloadFaces failed: ${e.message}")
            return Result.retry()
        }

        if (!resp.isSuccessful) {
            val code = resp.code()
            Log.w(TAG, "downloadFaces HTTP $code")
            if (code == 401 || code == 403) return Result.success()
            if (code == 408 || code == 429 || (code in 500..599)) return Result.retry()
            return Result.success()
        }

        val faces = resp.body()?.faces ?: emptyList()
        Log.i(TAG, "Downloaded ${faces.size} faces from server")

        val signature = facesSignature(faces)
        val lastSig = prefs.getString("last_faces_signature", null)
        if (lastSig != null && lastSig == signature) {
            try { reconcileLocalWithServer(faces) } catch (_: Exception) {}
            return Result.success()
        }
        prefs.edit().putString("last_faces_signature", signature).apply()

        val db = DBManager(applicationContext)
        var imported = 0
        var skipped = 0

        for (faceData in faces) {
            try {
                val id = faceData.id ?: ""
                if (id.isBlank()) { skipped++; continue }

                val name = faceData.name ?: ""
                val phone = faceData.phone ?: ""
                val dept = faceData.department ?: ""
                val desig = faceData.designation ?: ""
                val shift = faceData.shift ?: ""
                val customDataStr = faceData.customData?.toString() ?: ""
                val templatesB64 = faceData.templates

                // Resolve face image: prefer inline base64, then image_url download
                var faceBitmap: android.graphics.Bitmap? = null
                val faceB64 = faceData.faceImage
                val imageUrl = faceData.imageUrl

                // Try base64 face_image first (if it looks like base64, not a URL)
                if (!faceB64.isNullOrBlank() && !faceB64.startsWith("http") && !faceB64.startsWith("s3://")) {
                    try {
                        val faceImageBytes = Base64.decode(faceB64, Base64.NO_WRAP)
                        val options = BitmapFactory.Options()
                        options.inJustDecodeBounds = true
                        BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size, options)
                        val maxDim = 400
                        var inSampleSize = 1
                        if (options.outHeight > maxDim || options.outWidth > maxDim) {
                            val halfHeight = options.outHeight / 2
                            val halfWidth = options.outWidth / 2
                            while (halfHeight / inSampleSize >= maxDim && halfWidth / inSampleSize >= maxDim) {
                                inSampleSize *= 2
                            }
                        }
                        options.inJustDecodeBounds = false
                        options.inSampleSize = inSampleSize
                        faceBitmap = BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size, options)
                    } catch (_: Exception) {}
                }

                // If no base64, try downloading from image_url (presigned S3 URL)
                if (faceBitmap == null && !imageUrl.isNullOrBlank()) {
                    try {
                        val connection = URL(imageUrl).openConnection()
                        connection.connectTimeout = 10000
                        connection.readTimeout = 15000
                        val stream = connection.getInputStream()
                        val bytes = stream.readBytes()
                        stream.close()
                        faceBitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    } catch (e: Exception) {
                        Log.w(TAG, "Failed to download image_url for $name: ${e.message}")
                    }
                }

                // Parse templates (may be empty for students who haven't been face-scanned yet)
                val templates: ByteArray? = if (!templatesB64.isNullOrBlank()) {
                    try { Base64.decode(templatesB64, Base64.NO_WRAP) } catch (_: Exception) { null }
                } else null

                // Insert the person even without templates/photo — they still need to appear in the student list
                if (faceBitmap != null || templates != null) {
                    db.insertPerson(id, name, faceBitmap, templates ?: ByteArray(0), phone, dept, desig, shift, customDataStr, true)
                    imported++
                } else {
                    // Insert with no photo/template — bare record for name roster
                    db.insertPerson(id, name, null, ByteArray(0), phone, dept, desig, shift, customDataStr, true)
                    imported++
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error importing face: ${e.message}")
                skipped++
            }
        }

        Log.i(TAG, "Import complete: $imported imported, $skipped skipped")

        // Reconcile: delete any local person not present on server
        try { reconcileLocalWithServer(faces) } catch (_: Exception) {}

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

    private fun reconcileLocalWithServer(faces: List<SyncRequest>) {
        val db = DBManager(applicationContext)
        val serverIds = faces.mapNotNull { it.id }.filter { it.isNotBlank() }.toSet()
        val readable = db.readableDatabase
        var cursor: android.database.Cursor? = null
        try {
            cursor = readable.rawQuery("select id from person where id is not null and trim(id) != ''", null)
            if (cursor.moveToFirst()) {
                do {
                    val id = cursor.getString(0)
                    if (id != null && id.isNotBlank() && !serverIds.contains(id)) {
                        db.deletePersonById(id)
                    }
                } while (cursor.moveToNext())
            }
        } finally {
            try { cursor?.close() } catch (_: Exception) {}
        }
    }
}
