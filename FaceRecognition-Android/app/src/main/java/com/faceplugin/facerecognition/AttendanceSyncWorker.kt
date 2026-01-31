package com.faceplugin.facerecognition

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Constraints
import androidx.work.NetworkType
import com.faceplugin.facerecognition.api.PersonEventRequest
import com.faceplugin.facerecognition.api.RetrofitClient
import com.faceplugin.facerecognition.api.GreetingService
import retrofit2.Response

class AttendanceSyncWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    override fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
        val token = prefs.getString("token", null)
        if (baseUrl != null) RetrofitClient.setBaseUrl(baseUrl)
        if (token != null) RetrofitClient.setAuthToken(token)
        val service: GreetingService = RetrofitClient.getService()

        val db = DBManager(applicationContext)
        val queue = db.attendanceQueue
        var successCount = 0
        var failureCount = 0
        for (item in queue) {
            try {
                var pid = item.personId
                if (pid.isNullOrBlank()) {
                    pid = db.resolvePersonId(item.localUid, item.name)
                }
                if (pid.isNullOrBlank()) {
                    failureCount++
                    continue
                }
                val req = PersonEventRequest(
                    true,
                    true,
                    pid,
                    item.name,
                    0.9f,
                    item.image ?: "",
                    true,
                    item.timestamp
                )
                val resp: Response<com.faceplugin.facerecognition.api.GreetingResponse> =
                    service.sendPersonEvent(req).execute()
                if (resp.isSuccessful) {
                    db.deleteQueueItem(item.id)
                    successCount++
                } else {
                    failureCount++
                }
            } catch (e: Exception) {
                failureCount++
            }
        }
        return Result.success()
    }

    companion object {
        private const val UNIQUE_WORK_NAME = "attendance-sync"
        fun scheduleImmediate(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val req = OneTimeWorkRequestBuilder<AttendanceSyncWorker>()
                .setConstraints(constraints)
                .build()
            androidx.work.WorkManager.getInstance(context)
                .enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.KEEP, req)
        }
    }
}
