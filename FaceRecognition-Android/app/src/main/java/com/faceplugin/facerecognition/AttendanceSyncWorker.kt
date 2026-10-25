package com.faceplugin.facerecognition

import android.content.Context
import android.util.Log
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
import java.util.concurrent.Executors

class AttendanceSyncWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {

    override fun doWork(): Result {
        val (successCount, needsRetry) = performSync(applicationContext)
        Log.i(TAG, "AttendanceSyncWorker doWork finished: synced $successCount, needsRetry=$needsRetry")
        return if (needsRetry) Result.retry() else Result.success()
    }

    companion object {
        private const val TAG = "AttendanceSyncWorker"
        private const val UNIQUE_WORK_NAME = "attendance-sync"
        private val syncExecutor = Executors.newSingleThreadExecutor()

        @Volatile
        private var isSyncing = false

        /**
         * Perform the sync loop synchronously. Returns Pair(successCount, needsRetry).
         */
        @JvmStatic
        fun performSync(context: Context): Pair<Int, Boolean> {
            synchronized(this) {
                if (isSyncing) {
                    Log.d(TAG, "Sync already in progress, skipping duplicate invocation")
                    return Pair(0, false)
                }
                isSyncing = true
            }

            try {
                val prefs = context.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
                val baseUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl())
                val token = prefs.getString("token", null)?.takeIf { it.isNotBlank() }
                    ?: prefs.getString("offline_saved_token", null)?.takeIf { it.isNotBlank() }

                if (baseUrl != null) RetrofitClient.setBaseUrl(baseUrl)
                if (token != null) RetrofitClient.setAuthToken(token)

                if (token.isNullOrBlank()) {
                    Log.w(TAG, "No auth token available for attendance sync")
                    return Pair(0, false)
                }

                val service: GreetingService = RetrofitClient.getService()
                val db = DBManager(context)
                val queue = db.attendanceQueue
                if (queue.isEmpty()) {
                    return Pair(0, false)
                }

                Log.i(TAG, "Starting attendance sync for ${queue.size} queued items")
                var successCount = 0
                var needsRetry = false

                val deviceId = android.provider.Settings.Secure.getString(
                    context.contentResolver,
                    android.provider.Settings.Secure.ANDROID_ID
                )
                val deviceName = prefs.getString("device_name", null)?.takeIf { it.isNotBlank() }
                    ?: if (!deviceId.isNullOrBlank() && deviceId.length >= 8) "Mobile ${deviceId.substring(0, 8)}" else "Mobile"

                val vendorId = prefs.getInt("vendor_id", -1).let {
                    if (it > 0) it else prefs.getInt("offline_saved_vendor_id", -1)
                }
                var btype = prefs.getString("selected_business_type_code", null)?.takeIf { it.isNotBlank() }
                    ?: prefs.getString("selected_business_type", null)?.takeIf { it.isNotBlank() }

                for (item in queue) {
                    try {
                        var pid = item.personId
                        if (pid.isNullOrBlank() || pid.startsWith("local:")) {
                            val resolved = db.resolvePersonId(item.localUid, item.name)
                            if (!resolved.isNullOrBlank() && !resolved.startsWith("local:")) {
                                pid = resolved
                            }
                        }

                        // Determine effective ID for backend lookup
                        val effectivePid = if (!pid.isNullOrBlank() && !pid.startsWith("local:")) {
                            pid
                        } else if (!item.localUid.isNullOrBlank()) {
                            "local:${item.localUid}"
                        } else {
                            pid
                        }

                        val personName = item.name ?: ""

                        // Skip only if completely devoid of both identifier and name
                        if (effectivePid.isNullOrBlank() && personName.isBlank()) {
                            Log.w(TAG, "Item ${item.id} has no person_id, local_uid, or name. Discarding corrupt item.")
                            db.deleteQueueItem(item.id)
                            continue
                        }

                        val req = PersonEventRequest(
                            true,
                            true,
                            effectivePid,
                            personName,
                            0.9f,
                            item.image ?: "",
                            true,
                            item.timestamp
                        )
                        req.status = item.status
                        req.deviceId = deviceId
                        req.deviceName = deviceName
                        if (vendorId > 0) req.vendorId = vendorId
                        if (!btype.isNullOrBlank()) req.businessType = btype.lowercase()

                        val resp: Response<com.faceplugin.facerecognition.api.GreetingResponse> =
                            service.sendPersonEvent(req).execute()

                        if (resp.isSuccessful) {
                            try {
                                val status = resp.body()?.status ?: item.status ?: ""
                                val confirmedPid = resp.body()?.personId?.toString() ?: pid
                                db.upsertAttendanceState(confirmedPid, item.localUid, item.name, status, item.timestamp)
                            } catch (_: Exception) {}
                            db.deleteQueueItem(item.id)
                            successCount++
                            Log.i(TAG, "Synced item ${item.id} successfully: person=$personName, status=${item.status}")
                        } else {
                            val code = resp.code()
                            Log.w(TAG, "Item ${item.id} sync failed with HTTP $code: ${resp.message()}")
                            if (code == 400) {
                                // 400 Bad Request: unresolvable person on server or duplicate/bad data
                                // Delete to avoid permanently clogging the offline queue
                                db.deleteQueueItem(item.id)
                            } else if (code == 401 || code == 403) {
                                Log.e(TAG, "Auth error ($code) during sync; stopping further requests until re-authenticated")
                                needsRetry = true
                                break
                            } else if (code == 408 || code == 429 || code in 500..599) {
                                needsRetry = true
                            }
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Exception syncing queue item ${item.id}", e)
                        needsRetry = true
                    }
                }

                return Pair(successCount, needsRetry)
            } finally {
                synchronized(this) {
                    isSyncing = false
                }
            }
        }

        /**
         * Trigger immediate asynchronous sync in a background thread if device is online.
         */
        @JvmStatic
        @JvmOverloads
        fun syncNow(context: Context, callback: ((Int) -> Unit)? = null) {
            val appContext = context.applicationContext
            syncExecutor.execute {
                if (NetworkUtils.isOnline(appContext)) {
                    val (count, _) = performSync(appContext)
                    callback?.invoke(count)
                } else {
                    callback?.invoke(0)
                }
            }
        }

        /**
         * Schedule via WorkManager with REPLACE policy so the request is never dropped.
         */
        @JvmStatic
        fun scheduleImmediate(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val req = OneTimeWorkRequestBuilder<AttendanceSyncWorker>()
                .setConstraints(constraints)
                .build()
            androidx.work.WorkManager.getInstance(context)
                .enqueueUniqueWork(UNIQUE_WORK_NAME, ExistingWorkPolicy.REPLACE, req)
        }
    }
}
