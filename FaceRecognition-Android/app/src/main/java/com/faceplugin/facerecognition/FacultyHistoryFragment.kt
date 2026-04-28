package com.faceplugin.facerecognition

import android.graphics.BitmapFactory
import androidx.core.content.ContextCompat
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Shows past lecture sessions. For sessions that have locally queued photos,
 * provides an Upload button that sends photos to the server one by one,
 * shows recognition results in real time, then lets faculty mark attendance.
 */
class FacultyHistoryFragment : Fragment() {

    companion object {
        private const val TAG = "FacultyHistory"
    }

    // ── Views ─────────────────────────────────────────────────────────────────
    private lateinit var root:           LinearLayout
    private lateinit var tvTitle:        TextView
    private lateinit var progressBar:    ProgressBar
    private lateinit var tvStatus:       TextView
    private lateinit var rvResults:      RecyclerView
    private lateinit var btnMarkAll:     Button
    private lateinit var sessionList:    LinearLayout

    private val scanResults = mutableListOf<ScanResult>()
    private lateinit var resultsAdapter: ScanResultAdapter
    private var activeUploadLectureId   = -1

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        root = LinearLayout(requireContext()).apply {
            orientation  = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            setPadding(0, 0, 0, 0)
        }

        // Title bar
        tvTitle = TextView(requireContext()).apply {
            text     = "Lecture History"
            textSize = 18f
            setTextColor(android.graphics.Color.WHITE)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            setPadding(40, 120, 40, 24)
        }
        root.addView(tvTitle)

        // Session cards list
        val scroll = android.widget.ScrollView(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
            )
        }
        sessionList = LinearLayout(requireContext()).apply {
            orientation  = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            setPadding(24, 0, 24, 24)
        }
        scroll.addView(sessionList)
        root.addView(scroll)

        // Upload progress + status (hidden until upload starts)
        progressBar = ProgressBar(requireContext(), null, android.R.attr.progressBarStyleHorizontal).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                setMargins(40, 8, 40, 0)
            }
            isIndeterminate = false
            visibility = View.GONE
        }
        root.addView(progressBar)

        tvStatus = TextView(requireContext()).apply {
            textSize = 12f
            setTextColor(0x99FFFFFFu.toInt())
            setPadding(40, 4, 40, 4)
            visibility = View.GONE
        }
        root.addView(tvStatus)

        // Results list (shown after upload)
        rvResults = RecyclerView(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
            )
            visibility = View.GONE
        }
        resultsAdapter = ScanResultAdapter(scanResults) { _, _ -> }
        rvResults.layoutManager = LinearLayoutManager(requireContext())
        rvResults.adapter       = resultsAdapter
        root.addView(rvResults)

        // Mark attendance button (shown after upload)
        btnMarkAll = Button(requireContext()).apply {
            text = "Mark Attendance"
            setTextColor(android.graphics.Color.WHITE)
            backgroundTintList = android.content.res.ColorStateList.valueOf(0xFF4CAF50.toInt())
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(40, 8, 40, 32) }
            visibility = View.GONE
            setOnClickListener { markAttendance() }
        }
        root.addView(btnMarkAll)

        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        loadSessions()
    }

    // ── Session list ──────────────────────────────────────────────────────────

    private fun loadSessions() {
        sessionList.removeAllViews()
        addTextCard("Loading sessions…", 0xCCFFFFFFu.toInt())

        RetrofitClient.getService().getFacultyLectures("", "", "").enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (!isAdded) return
                val arr = resp.body()?.getAsJsonArray("lectures")
                sessionList.removeAllViews()

                val db = DBManager(requireContext())

                if (arr == null || arr.size() == 0) {
                    addTextCard("No lecture sessions yet.\nCreate one from the Home tab.", 0x99FFFFFFu.toInt())
                    return
                }

                for (el in arr) {
                    val lecture    = el.asJsonObject
                    val lectureId  = lecture.get("id")?.asInt ?: continue
                    val subject    = lecture.get("subject")?.asString ?: "Unknown"
                    val date       = lecture.get("date")?.asString ?: ""
                    val division   = lecture.get("division")?.asString ?: ""
                    val classYear  = lecture.get("class_year")?.asString ?: ""

                    // Count locally queued photos for this session
                    val pending = db.getPendingImages().count { it[1].toInt() == lectureId }

                    addSessionCard(lectureId, subject, classYear, division, date, pending)
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                sessionList.removeAllViews()
                // Show local sessions only
                val db      = DBManager(requireContext())
                val pending = db.getPendingImages()
                if (pending.isEmpty()) {
                    addTextCard("Could not load sessions — check connection.", 0x99FFFFFFu.toInt())
                } else {
                    // Group by lecture_id
                    val grouped = pending.groupBy { it[1].toInt() }
                    for ((lid, rows) in grouped) {
                        addSessionCard(lid, "Session #$lid", "", "", "", rows.size)
                    }
                }
            }
        })
    }

    private fun addSessionCard(lectureId: Int, subject: String, classYear: String,
                               division: String, date: String, pendingCount: Int) {
        val card = LinearLayout(requireContext()).apply {
            orientation  = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, 0, 0, 16) }
            setPadding(32, 24, 32, 24)
            background = ContextCompat.getDrawable(requireContext(), R.drawable.bg_card_dark)
            elevation  = 4f
        }

        val label = buildString {
            append(subject.ifBlank { "Unknown Subject" })
            if (classYear.isNotBlank()) append(" · $classYear")
            if (division.isNotBlank())  append("-$division")
            if (date.isNotBlank())      append("\n$date")
        }

        TextView(requireContext()).apply {
            text     = label
            textSize = 14f
            setTextColor(android.graphics.Color.WHITE)
        }.also { card.addView(it) }

        if (pendingCount > 0) {
            TextView(requireContext()).apply {
                text     = "$pendingCount photo${if (pendingCount == 1) "" else "s"} ready to upload"
                textSize = 12f
                setTextColor(0xFFFFC107u.toInt())
                setPadding(0, 8, 0, 8)
            }.also { card.addView(it) }

            Button(requireContext()).apply {
                text = "Upload & Detect"
                setTextColor(android.graphics.Color.WHITE)
                backgroundTintList = android.content.res.ColorStateList.valueOf(0xFF3F51B5.toInt())
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
                )
                setOnClickListener { startUpload(lectureId, subject) }
            }.also { card.addView(it) }
        } else {
            TextView(requireContext()).apply {
                text     = "No pending photos"
                textSize = 11f
                setTextColor(0x66FFFFFFu.toInt())
                setPadding(0, 4, 0, 0)
            }.also { card.addView(it) }
        }

        sessionList.addView(card)
    }

    private fun addTextCard(text: String, color: Int) {
        TextView(requireContext()).apply {
            this.text  = text
            textSize   = 13f
            setTextColor(color)
            setPadding(8, 16, 8, 16)
        }.also { sessionList.addView(it) }
    }

    // ── Upload flow ───────────────────────────────────────────────────────────

    private fun startUpload(lectureId: Int, subject: String) {
        val db      = DBManager(requireContext())
        val pending = db.getPendingImages().filter { it[1].toInt() == lectureId }
        if (pending.isEmpty()) {
            Toast.makeText(context, "No photos to upload", Toast.LENGTH_SHORT).show()
            return
        }

        activeUploadLectureId = lectureId
        scanResults.clear()
        resultsAdapter.notifyDataSetChanged()

        // Show progress UI
        progressBar.max      = pending.size
        progressBar.progress = 0
        progressBar.visibility = View.VISIBLE
        tvStatus.visibility    = View.VISIBLE
        tvStatus.text          = "Uploading photo 1 of ${pending.size}…"
        rvResults.visibility   = View.GONE
        btnMarkAll.visibility  = View.GONE

        tvTitle.text = "Scanning: $subject"

        uploadNext(pending, 0, lectureId)
    }

    private fun uploadNext(pending: List<LongArray>, index: Int, lectureId: Int) {
        if (index >= pending.size) {
            // All done
            requireActivity().runOnUiThread {
                progressBar.visibility = View.GONE
                tvStatus.text          = "Done — ${scanResults.size} face(s) identified"
                rvResults.visibility   = View.VISIBLE
                btnMarkAll.visibility  = if (scanResults.any { it.personId != null }) View.VISIBLE else View.GONE
                tvTitle.text           = "Lecture History"
            }
            return
        }

        val row       = pending[index]
        val rowId     = row[0]
        val db        = DBManager(requireContext())
        val imagePath = db.getPendingImagePath(rowId)

        requireActivity().runOnUiThread {
            progressBar.progress = index
            tvStatus.text        = "Uploading photo ${index + 1} of ${pending.size}…"
        }

        if (imagePath == null || !File(imagePath).exists()) {
            db.updatePendingImageStatus(rowId, "uploaded")
            uploadNext(pending, index + 1, lectureId)
            return
        }

        Thread {
            try {
                val bytes  = File(imagePath).readBytes()
                val b64    = Base64.encodeToString(bytes, Base64.NO_WRAP)
                val body   = JsonObject().apply {
                    addProperty("image",      "data:image/jpeg;base64,$b64")
                    addProperty("lecture_id", lectureId)
                }

                val resp = RetrofitClient.getService().scanFacultyImage(body).execute()
                if (resp.isSuccessful && resp.body() != null) {
                    db.updatePendingImageStatus(rowId, "uploaded")
                    File(imagePath).delete()

                    val facesArr = resp.body()!!.getAsJsonArray("faces") ?: com.google.gson.JsonArray()
                    for (el in facesArr) {
                        val face       = el.asJsonObject
                        val personId   = face.get("person_id")?.takeIf { !it.isJsonNull }?.asString
                        val name       = face.get("name")?.asString ?: "Unknown"
                        val confidence = face.get("confidence")?.asFloat ?: 0f
                        val thumbB64   = face.get("face_thumb")?.asString ?: ""
                        val thumb      = decodeThumb(thumbB64)

                        // Deduplicate by person_id — keep highest confidence
                        val existing = scanResults.indexOfFirst { it.personId == personId && personId != null }
                        if (existing >= 0) {
                            if (confidence > scanResults[existing].confidence) {
                                scanResults[existing] = ScanResult(thumb ?: scanResults[existing].faceBitmap, personId, name, confidence, scanResults[existing].status)
                            }
                        } else {
                            scanResults.add(ScanResult(thumb, personId, name, confidence,
                                if (personId != null) "present" else "absent"))
                        }
                    }

                    requireActivity().runOnUiThread {
                        resultsAdapter.notifyDataSetChanged()
                        tvStatus.text = "Photo ${index + 1} done — ${scanResults.size} face(s) so far"
                    }
                } else {
                    Log.w(TAG, "Upload failed for row $rowId: ${resp.code()}")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Upload error", e)
            }
            uploadNext(pending, index + 1, lectureId)
        }.start()
    }

    // ── Mark attendance ───────────────────────────────────────────────────────

    private fun markAttendance() {
        val lectureId = activeUploadLectureId
        if (lectureId < 0) return

        val toMark = scanResults.filter { !it.personId.isNullOrBlank() }
        if (toMark.isEmpty()) {
            Toast.makeText(context, "No recognised students to mark", Toast.LENGTH_SHORT).show()
            return
        }

        val db = DBManager(requireContext())
        val ts = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date())
        toMark.forEach { r ->
            db.insertFacultyAttendance(lectureId, r.personId!!, r.personName, "", ts, r.status, r.confidence)
        }

        val arr = com.google.gson.JsonArray()
        toMark.forEach { r ->
            arr.add(JsonObject().apply {
                addProperty("person_id",  r.personId)
                addProperty("status",     r.status)
                addProperty("timestamp",  ts)
                addProperty("confidence", r.confidence / 100f)
            })
        }
        val body = JsonObject().apply { add("attendance", arr) }

        btnMarkAll.isEnabled = false
        btnMarkAll.text      = "Saving…"

        RetrofitClient.getService().markFacultyLectureAttendance(lectureId, body)
            .enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                    if (!isAdded) return
                    requireActivity().runOnUiThread {
                        btnMarkAll.isEnabled = true
                        if (resp.isSuccessful) {
                            for (p in db.unsyncedFacultyAttendance) db.markFacultyAttendanceSynced(p.first)
                            Toast.makeText(context, "Attendance marked for ${toMark.size} student(s)!", Toast.LENGTH_LONG).show()
                            // Reset and reload
                            scanResults.clear()
                            resultsAdapter.notifyDataSetChanged()
                            rvResults.visibility  = View.GONE
                            btnMarkAll.visibility = View.GONE
                            btnMarkAll.text       = "Mark Attendance"
                            tvStatus.text         = ""
                            tvTitle.text          = "Lecture History"
                            loadSessions()
                        } else {
                            btnMarkAll.text = "Mark Attendance"
                            Toast.makeText(context, "Saved locally (server ${resp.code()})", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                    if (!isAdded) return
                    requireActivity().runOnUiThread {
                        btnMarkAll.isEnabled = true
                        btnMarkAll.text      = "Mark Attendance"
                        Toast.makeText(context, "Saved offline — will sync when connected", Toast.LENGTH_SHORT).show()
                    }
                }
            })
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun decodeThumb(b64: String) = try {
        if (b64.isBlank()) null
        else {
            val payload = if (',' in b64) b64.substringAfter(',') else b64
            val bytes   = Base64.decode(payload, Base64.DEFAULT)
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }
    } catch (_: Exception) { null }
}
