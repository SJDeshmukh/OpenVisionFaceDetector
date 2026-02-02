package com.faceplugin.facerecognition

import android.content.Context
import android.graphics.Bitmap
import android.util.Base64
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.faceplugin.facerecognition.api.GreetingService
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import retrofit2.Response
import java.io.ByteArrayOutputStream

class FaceSyncWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    override fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
        val token = prefs.getString("token", null)
        if (baseUrl != null) RetrofitClient.setBaseUrl(baseUrl)
        if (token != null) RetrofitClient.setAuthToken(token)
        if (token.isNullOrBlank()) return Result.success()
        val service: GreetingService = RetrofitClient.getService()

        val db = DBManager(applicationContext)
        val unsynced = db.unsyncedPersons
        var successCount = 0
        var needsRetry = false

        for (p in unsynced) {
            try {
                if (p.localUid.isNullOrBlank() || p.templates == null || p.face == null) continue
                val json = JsonObject()
                json.addProperty("name", p.name ?: "")
                json.addProperty("templates", Base64.encodeToString(p.templates, Base64.NO_WRAP))
                val baos = ByteArrayOutputStream()
                (p.face as Bitmap).compress(Bitmap.CompressFormat.JPEG, 100, baos)
                json.addProperty("face_image", Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP))
                json.addProperty("phone", p.phone ?: "")
                json.addProperty("department", p.department ?: "")
                json.addProperty("designation", p.designation ?: "")
                json.addProperty("shift", p.shift ?: "")

                val customRaw = p.customData
                if (!customRaw.isNullOrBlank()) {
                    try {
                        val el = JsonParser().parse(customRaw)
                        if (el.isJsonObject) {
                            for ((k, v) in el.asJsonObject.entrySet()) {
                                json.add(k, v)
                            }
                        }
                    } catch (_: Exception) {
                    }
                }

                val resp: Response<com.faceplugin.facerecognition.api.UploadFaceResponse> = service.uploadFace(json).execute()
                if (resp.isSuccessful) {
                    val id = resp.body()?.personId?.toString()
                    if (!id.isNullOrBlank()) {
                        db.updatePersonAfterSyncByLocalUid(p.localUid, id)
                    } else {
                        db.updatePersonStatusByLocalUid(p.localUid, true)
                    }
                    successCount++
                } else {
                    val code = resp.code()
                    if (code == 401 || code == 403) {
                        return Result.success()
                    }
                    if (code == 408 || code == 429 || (code in 500..599)) {
                        needsRetry = true
                    }
                }
            } catch (_: Exception) {
                needsRetry = true
            }
        }

        return if (needsRetry) Result.retry() else Result.success()
    }

    companion object {
        private const val UNIQUE_WORK_NAME = "face-sync"
        fun scheduleImmediate(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val req = OneTimeWorkRequestBuilder<FaceSyncWorker>()
                .setConstraints(constraints)
                .build()
            androidx.work.WorkManager.getInstance(context)
                .enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.KEEP, req)
        }
    }
}
