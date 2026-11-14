package com.faceplugin.facerecognition

import android.content.Context
import android.util.Log
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.util.concurrent.atomic.AtomicBoolean

object ParentLeaveSyncManager {

    private const val TAG = "ParentLeaveSyncManager"
    private const val PREFS_KEY = "pending_parent_leave_decisions"
    private val isSyncing = AtomicBoolean(false)

    /**
     * Enqueue a locally verified leave decision when offline or network fails.
     */
    @Suppress("DEPRECATION")
    fun enqueueDecision(context: Context, body: JsonObject) {
        try {
            val prefs = context.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
            val currentRaw = prefs.getString(PREFS_KEY, "[]") ?: "[]"
            val array = try {
                JsonParser().parse(currentRaw).asJsonArray
            } catch (_: Exception) {
                JsonArray()
            }
            array.add(body)
            prefs.edit().putString(PREFS_KEY, array.toString()).apply()
            Log.i(TAG, "Enqueued parent leave decision offline (total pending: ${array.size()})")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to enqueue parent leave decision", e)
        }
    }

    /**
     * Asynchronously sync all queued parent leave decisions to the server.
     */
    @Suppress("DEPRECATION")
    fun syncPendingDecisions(context: Context, onComplete: ((syncedCount: Int) -> Unit)? = null) {
        if (!NetworkUtils.isOnline(context)) {
            onComplete?.invoke(0)
            return
        }

        if (!isSyncing.compareAndSet(false, true)) {
            Log.d(TAG, "Sync already in progress, skipping")
            return
        }

        Thread {
            var syncedCount = 0
            try {
                val prefs = context.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
                val currentRaw = prefs.getString(PREFS_KEY, "[]") ?: "[]"
                val array = try {
                    JsonParser().parse(currentRaw).asJsonArray
                } catch (_: Exception) {
                    JsonArray()
                }

                if (array.size() == 0) {
                    isSyncing.set(false)
                    onComplete?.invoke(0)
                    return@Thread
                }

                Log.i(TAG, "Syncing ${array.size()} queued parent leave decisions...")
                val remaining = JsonArray()

                for (i in 0 until array.size()) {
                    val item = try { array.get(i).asJsonObject } catch (_: Exception) { null } ?: continue
                    try {
                        val response = RetrofitClient.getService().parentApproveLeave(item).execute()
                        val isSuccess = response.isSuccessful && response.body()?.get("status")?.asString == "success"
                        val code = response.code()

                        if (isSuccess || code == 409) {
                            // 409 means request was already decided or no longer awaiting parent; considered resolved
                            syncedCount++
                            Log.i(TAG, "Successfully synced leave decision: code=$code")
                        } else {
                            Log.w(TAG, "Failed to sync leave decision (code=$code), will keep in queue")
                            remaining.add(item)
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Network error syncing decision item", e)
                        remaining.add(item)
                    }
                }

                prefs.edit().putString(PREFS_KEY, remaining.toString()).apply()
            } catch (e: Exception) {
                Log.e(TAG, "Error in syncPendingDecisions", e)
            } finally {
                isSyncing.set(false)
                onComplete?.invoke(syncedCount)
            }
        }.start()
    }
}
