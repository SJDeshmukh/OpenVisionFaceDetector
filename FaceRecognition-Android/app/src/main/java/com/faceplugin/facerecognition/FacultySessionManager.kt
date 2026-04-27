package com.faceplugin.facerecognition

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import android.util.Pair
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

/**
 * Manages the current faculty attendance session.
 * Persists lecture selection across fragment navigations.
 */
object FacultySessionManager {

    private const val TAG   = "FacultySession"
    private const val PREFS = "faculty_session"

    data class LectureSession(
        val lectureId: Int,
        val subject:   String,
        val classYear: String,
        val division:  String,
        val date:      String,
        val teacher:   String
    ) {
        val displayLabel: String get() =
            buildString {
                append(subject.ifBlank { "Unknown Subject" })
                if (classYear.isNotBlank()) append(" · $classYear")
                if (division.isNotBlank())  append("-$division")
            }
    }

    @Volatile var currentSession: LectureSession? = null
        private set

    fun restore(ctx: Context) {
        val p = prefs(ctx)
        val id = p.getInt("lecture_id", -1)
        if (id < 0) return
        currentSession = LectureSession(
            lectureId = id,
            subject   = p.getString("subject", "") ?: "",
            classYear = p.getString("class_year", "") ?: "",
            division  = p.getString("division", "") ?: "",
            date      = p.getString("date", "") ?: "",
            teacher   = p.getString("teacher", "") ?: ""
        )
    }

    fun setSession(ctx: Context, session: LectureSession) {
        currentSession = session
        prefs(ctx).edit()
            .putInt("lecture_id", session.lectureId)
            .putString("subject",   session.subject)
            .putString("class_year",session.classYear)
            .putString("division",  session.division)
            .putString("date",      session.date)
            .putString("teacher",   session.teacher)
            .apply()
        Log.i(TAG, "Session set: ${session.displayLabel} (id=${session.lectureId})")
    }

    fun clearSession(ctx: Context) {
        currentSession = null
        prefs(ctx).edit().clear().apply()
    }

    /** Push all unsynced records to server. Calls [onDone] with (synced, errors). */
    fun syncPendingAttendance(ctx: Context, onDone: (Int, Int) -> Unit) {
        val db:   DBManager = DBManager(ctx)
        val rows: List<Pair<Int, JsonObject>> = db.unsyncedFacultyAttendance
        if (rows.isEmpty()) { onDone(0, 0); return }

        val arr = com.google.gson.JsonArray()
        for (pair in rows) arr.add(pair.second)
        val body = JsonObject().also { it.add("records", arr) }

        RetrofitClient.getService().syncFacultyAttendance(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (resp.isSuccessful) {
                    val synced = resp.body()?.get("synced")?.asInt ?: 0
                    val errors = resp.body()?.get("errors")?.asInt ?: 0
                    for (pair in rows) db.markFacultyAttendanceSynced(pair.first)
                    Log.i(TAG, "Sync complete: $synced synced, $errors errors")
                    onDone(synced, errors)
                } else {
                    Log.w(TAG, "Sync failed: ${resp.code()}")
                    onDone(0, rows.size)
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                Log.w(TAG, "Sync network error: ${t.message}")
                onDone(0, rows.size)
            }
        })
    }

    private fun prefs(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
