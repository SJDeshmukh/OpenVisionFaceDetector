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
        if (token.isNullOrBlank()) return Result.success()
        val service: GreetingService = RetrofitClient.getService()

        val db = DBManager(applicationContext)
        val queue = db.attendanceQueue
        var successCount = 0
        var needsRetry = false
        for (item in queue) {
            try {
                var pid = item.personId
                if (pid.isNullOrBlank()) {
                    pid = db.resolvePersonId(item.localUid)
                }
                if (pid.isNullOrBlank()) {
                    needsRetry = true
                    continue
                }
                val req = PersonEventRequest(
                    true,
                    true,
                    pid,
                    "",
                    0.9f,
                    item.image ?: "",
                    true,
                    item.timestamp
                )
                try {
                    val deviceId = android.provider.Settings.Secure.getString(applicationContext.contentResolver, android.provider.Settings.Secure.ANDROID_ID)
                    val deviceName = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE).getString("device_name", null)
                    val dn = if (!deviceName.isNullOrBlank()) deviceName else {
                        if (!deviceId.isNullOrBlank() && deviceId.length >= 8) "Mobile ${deviceId.substring(0, 8)}" else "Mobile"
                    }
                    req.deviceId = deviceId
                    req.deviceName = dn
                    val prefs2 = applicationContext.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
                    val vendorId = prefs2.getInt("vendor_id", -1)
                    if (vendorId > 0) req.vendorId = vendorId
                    var btype = prefs2.getString("selected_business_type_code", null)
                    if (btype.isNullOrBlank()) {
                        btype = prefs2.getString("selected_business_type", null)
                    }
                    if (!btype.isNullOrBlank()) {
                        req.businessType = btype.lowercase()
                    }
                } catch (_: Exception) {}
                val resp: Response<com.faceplugin.facerecognition.api.GreetingResponse> =
                    service.sendPersonEvent(req).execute()
                if (resp.isSuccessful) {
                    try {
                        val status = resp.body()?.status ?: item.status ?: ""
                        db.upsertAttendanceState(pid, item.localUid, item.name, status, item.timestamp)
                    } catch (_: Exception) {
                    }
                    db.deleteQueueItem(item.id)
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
            } catch (e: Exception) {
                needsRetry = true
            }
        }
        return if (needsRetry) Result.retry() else Result.success()
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
