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
        if (token.isNullOrBlank()) return Result.retry()

        val service: GreetingService = RetrofitClient.getService()
        val db = DBManager(applicationContext)
        val queue = db.deleteQueue

        for (item in queue) {
            try {
                val pid = item.personId
                val name = item.name
                val resp = if (!pid.isNullOrBlank()) {
                    service.deleteFaceById(pid).execute()
                } else if (!name.isNullOrBlank()) {
                    service.deleteFace(name).execute()
                } else {
                    db.deleteDeleteQueueItem(item.id)
                    continue
                }

                if (resp.isSuccessful || resp.code() == 404) {
                    db.deleteDeleteQueueItem(item.id)
                }
            } catch (_: Exception) {
            }
        }

        return Result.success()
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

