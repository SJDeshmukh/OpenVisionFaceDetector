package com.faceplugin.facerecognition

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.BackoffPolicy
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.faceplugin.facerecognition.api.GreetingService
import com.faceplugin.facerecognition.api.RetrofitClient
import java.util.concurrent.TimeUnit

class DeleteSyncWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    override fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
        val token = prefs.getString("token", null)
        if (baseUrl != null) RetrofitClient.setBaseUrl(baseUrl)
        if (token != null) RetrofitClient.setAuthToken(token)
        if (token.isNullOrBlank()) return Result.success()

        val service: GreetingService = RetrofitClient.getInteractiveService()
        val db = DBManager(applicationContext)
        val queue = db.deleteQueue
        var needsRetry = false

        for (item in queue) {
            try {
                var pid = item.personId
                if (pid.isNullOrBlank() && !item.localUid.isNullOrBlank()) {
                    pid = db.resolvePersonId(item.localUid)
                }
                val resp = if (!pid.isNullOrBlank()) {
                    service.deleteFaceById(pid).execute()
                } else if (!item.name.isNullOrBlank()) {
                    service.deleteFace(item.name).execute()
                } else {
                    // Nothing to delete by, remove from queue
                    db.deleteDeleteQueueItem(item.id)
                    continue
                }

                if (resp.isSuccessful || resp.code() == 404) {
                    db.deleteDeleteQueueItem(item.id)
                } else {
                    val code = resp.code()
                    if (code == 401 || code == 403) {
                        return Result.success()
                    }
                    if (code == 408 || code == 429 || (code in 500..599)) {
                        needsRetry = db.markDeleteQueueItemRetry(item.id, "HTTP $code") || needsRetry
                    } else {
                        db.markDeleteQueueItemFailed(item.id, "HTTP $code")
                    }
                }
            } catch (exc: Exception) {
                needsRetry = db.markDeleteQueueItemRetry(item.id, exc.javaClass.simpleName) || needsRetry
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
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
                .build()
            androidx.work.WorkManager.getInstance(context)
                .enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.REPLACE, req)
        }
    }
}
