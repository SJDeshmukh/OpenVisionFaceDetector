package com.faceplugin.facerecognition

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.faceplugin.facerecognition.api.GreetingService
import com.faceplugin.facerecognition.api.RetrofitClient

class DeleteSyncWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    override fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
        val token = prefs.getString("token", null)
        if (baseUrl != null) RetrofitClient.setBaseUrl(baseUrl)
        if (token != null) RetrofitClient.setAuthToken(token)
        if (token.isNullOrBlank()) return Result.success()

        val service: GreetingService = RetrofitClient.getService()
        val db = DBManager(applicationContext)
        val queue = db.deleteQueue
        var needsRetry = false

        for (item in queue) {
            try {
                var pid = item.personId
                if (pid.isNullOrBlank() && !item.localUid.isNullOrBlank()) {
                    pid = db.resolvePersonId(item.localUid)
                }
                if (pid.isNullOrBlank()) {
                    needsRetry = true
                    continue
                }
                val resp = service.deleteFaceById(pid).execute()

                if (resp.isSuccessful || resp.code() == 404) {
                    db.deleteDeleteQueueItem(item.id)
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
        private const val UNIQUE_WORK_NAME = "delete-sync"
        fun scheduleImmediate(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val req = OneTimeWorkRequestBuilder<DeleteSyncWorker>()
                .setConstraints(constraints)
                .build()
            androidx.work.WorkManager.getInstance(context)
                .enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.KEEP, req)
        }
    }
}
