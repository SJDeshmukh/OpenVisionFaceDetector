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

        val body = resp.body() ?: return Result.retry()
        val faces = body.faces
        // Treat an unexpected empty response as non-authoritative. A transient backend
        // serialization/database failure must never erase the entire offline gallery.
        if (faces.isEmpty() && hasLocalFaces()) return Result.retry()
        val signature = facesSignature(faces)
        val lastSig = prefs.getString("last_faces_signature", null)
        if (lastSig != null && lastSig == signature) {
            // Even if signature unchanged, perform reconciliation to remove deleted faces
            try {
                reconcileLocalWithServer(faces)
            } catch (_: Exception) {}
            return Result.success()
        }
        val db = DBManager(applicationContext)
        var hadFailure = false
        // Insert/update faces
        for (faceData in faces) {
            try {
                val id = faceData.id ?: ""
                if (id.isBlank()) continue
                val templatesB64 = faceData.templates
                val faceB64 = faceData.faceImage
                val templates = if (templatesB64.isNullOrBlank()) null else Base64.decode(templatesB64, Base64.NO_WRAP)
                val faceImageBytes = if (faceB64.isNullOrBlank()) null else Base64.decode(faceB64, Base64.NO_WRAP)
                
                var faceBitmap: android.graphics.Bitmap? = null
                if (faceImageBytes != null) {
                    // Use BitmapFactory.Options for memory-efficient decoding
                    val options = BitmapFactory.Options()
                    options.inJustDecodeBounds = true
                    BitmapFactory.decodeByteArray(faceImageBytes, 0, faceImageBytes.size, options)
                    
                    // Scale down if image is too large (max 400px)
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
                }

                val phone = faceData.phone ?: ""
                val dept = faceData.department ?: ""
                val desig = faceData.designation ?: ""
                val shift = faceData.shift ?: ""
                val name = faceData.name ?: ""
                val customDataStr = faceData.customData?.toString() ?: ""

                db.insertPerson(id, name, faceBitmap, templates, phone, dept, desig, shift, customDataStr, true)
            } catch (_: Exception) {
                hadFailure = true
            }
        }

        if (hadFailure) return Result.retry()

        // Reconcile: delete any local person not present on server
        try {
            reconcileLocalWithServer(faces)
        } catch (_: Exception) {}

        prefs.edit().putString("last_faces_signature", signature).apply()

        return Result.success()
    }

    private fun facesSignature(faces: List<SyncRequest>): String {
        val digest = MessageDigest.getInstance("SHA-256")
        fun add(value: String?) {
            digest.update((value ?: "").toByteArray(Charsets.UTF_8))
            digest.update(0)
        }
        add(faces.size.toString())
        for (face in faces.sortedBy { it.id ?: "" }) {
            add(face.id)
            add(face.name)
            add(face.templates)
            add(face.faceImage)
            add(face.phone)
            add(face.department)
            add(face.designation)
            add(face.shift)
            add(face.customData?.toString())
        }
        val bytes = digest.digest()
        val out = StringBuilder(bytes.size * 2)
        for (b in bytes) out.append(String.format("%02x", b))
        return out.toString()
    }

    private fun hasLocalFaces(): Boolean {
        val db = DBManager(applicationContext).readableDatabase
        db.rawQuery("SELECT 1 FROM person LIMIT 1", null).use { cursor ->
            return cursor.moveToFirst()
        }
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

    private fun reconcileLocalWithServer(faces: List<com.faceplugin.facerecognition.api.SyncRequest>) {
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
