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
import androidx.appcompat.app.AlertDialog
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
 * Shows past lecture sessions. Lecture cards are clickable — tapping them
 * fetches attendance from the server and shows a present/absent drill-down.
 * For sessions with locally queued photos, provides an Upload button.
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
        resultsAdapter = ScanResultAdapter(scanResults) { _, _ -> }.apply {
            setRelabelCallback { face -> showRelabelDialog(face) }
            setSaveEmbeddingCallback { face -> 
                if (face.personId != null) {
                    relabelAndSave(face, face.personId!!, face.personName)
                }
            }
        }
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

    override fun onHiddenChanged(hidden: Boolean) {
        super.onHiddenChanged(hidden)
        if (!hidden) loadSessions()
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
                    val date       = lecture.get("date")?.asString
                        ?: lecture.get("lecture_date")?.asString ?: ""
                    val division   = lecture.get("division")?.asString ?: ""
                    val classYear  = lecture.get("class_year")?.asString ?: ""
                    val teacher    = lecture.get("teacher")?.asString ?: ""
                    val presentCnt = lecture.get("present_count")?.asInt ?: 0

                    // Count locally queued photos for this session
                    val pending = db.getPendingImages().count { it[1].toInt() == lectureId }

                    addSessionCard(lectureId, subject, classYear, division, date, teacher, pending, presentCnt)
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
                        addSessionCard(lid, "Session #$lid", "", "", "", "", rows.size, 0)
                    }
                }
            }
        })
    }

    private fun addSessionCard(lectureId: Int, subject: String, classYear: String,
                               division: String, date: String, teacher: String,
                               pendingCount: Int, presentCount: Int) {
        val card = LinearLayout(requireContext()).apply {
            orientation  = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, 0, 0, 16) }
            setPadding(32, 24, 32, 24)
            background = ContextCompat.getDrawable(requireContext(), R.drawable.bg_card_dark)
            elevation  = 4f
            isClickable  = true
            isFocusable  = true
        }

        val label = buildString {
            append(subject.ifBlank { "Unknown Subject" })
            if (classYear.isNotBlank()) append(" · $classYear")
            if (division.isNotBlank())  append("-$division")
            if (date.isNotBlank())      append("\n$date")
            if (teacher.isNotBlank())   append(" · $teacher")
        }

        TextView(requireContext()).apply {
            text     = label
            textSize = 14f
            setTextColor(android.graphics.Color.WHITE)
        }.also { card.addView(it) }

        // Present count badge
        if (presentCount > 0) {
            TextView(requireContext()).apply {
                text     = "$presentCount student${if (presentCount == 1) "" else "s"} marked present"
                textSize = 12f
                setTextColor(0xFF4CAF50.toInt())
                setPadding(0, 6, 0, 4)
            }.also { card.addView(it) }
        }

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
            // Hint text
            TextView(requireContext()).apply {
                text     = "Tap to view attendance →"
                textSize = 11f
                setTextColor(0x88FFFFFFu.toInt())
                setPadding(0, 4, 0, 0)
            }.also { card.addView(it) }
        }

        // Make the whole card clickable for drill-down
        card.setOnClickListener { showLectureAttendance(lectureId, subject, classYear, division) }

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

    // ── Lecture Attendance Drill-down ──────────────────────────────────────────

    private fun showLectureAttendance(lectureId: Int, subject: String, classYear: String, division: String) {
        val ctx = requireContext()
        val loading = AlertDialog.Builder(ctx)
            .setTitle("$subject ${classYear.ifBlank { "" }}${if (division.isNotBlank()) "-$division" else ""}")
            .setMessage("Loading attendance…")
            .setCancelable(true)
            .show()

        RetrofitClient.getService().getLectureDetail(lectureId).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (!isAdded) { loading.dismiss(); return }
                loading.dismiss()

                val body = resp.body()
                if (!resp.isSuccessful || body == null) {
                    Toast.makeText(ctx, "Failed to load attendance", Toast.LENGTH_SHORT).show()
                    return
                }

                val attendanceArr = body.getAsJsonArray("attendance") ?: com.google.gson.JsonArray()
                if (attendanceArr.size() == 0) {
                    AlertDialog.Builder(ctx)
                        .setTitle("$subject")
                        .setMessage("No attendance records yet for this lecture.")
                        .setPositiveButton("OK", null)
                        .show()
                    return
                }

                // Local state for toggling
                val currentAttendance = mutableMapOf<String, String>() // person_id -> status
                val studentNames      = mutableMapOf<String, String>() // person_id -> name

                try {
                    for (el in attendanceArr) {
                        val s = el.asJsonObject
                        val pidEl = s.get("person_id")
                        if (pidEl == null || pidEl.isJsonNull) continue
                        // person_id may arrive as a JSON number or string — normalise to String
                        val pid = pidEl.asString
                        currentAttendance[pid] = s.get("status")?.asString ?: "absent"
                        studentNames[pid] = s.get("name")?.asString ?: "Unknown"
                    }
                } catch (e: Exception) {
                    Log.e("FacultyHistory", "Error parsing attendance data", e)
                    Toast.makeText(ctx, "Error loading student data", Toast.LENGTH_SHORT).show()
                    return
                }

                // Build drill-down dialog with RecyclerView for performance
                val rvContainer = LinearLayout(ctx).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(0, 16, 0, 16)
                }
                
                val tvStats = TextView(ctx).apply {
                    textSize = 14f
                    setPadding(48, 16, 48, 16)
                    setTextColor(0xFFFFFFFF.toInt())
                }
                rvContainer.addView(tvStats)
                
                val rvAttendance = androidx.recyclerview.widget.RecyclerView(ctx).apply {
                    layoutManager = androidx.recyclerview.widget.LinearLayoutManager(ctx)
                }
                
                fun getSortedList(): List<String> {
                    val pList = currentAttendance.filter { it.value == "present" }.keys.sortedBy { studentNames[it] }
                    val aList = currentAttendance.filter { it.value == "absent" }.keys.sortedBy { studentNames[it] }
                    tvStats.text = "Present: ${pList.size}   |   Absent: ${aList.size}"
                    return pList + aList
                }

                var studentList = getSortedList()
                val adapter = AttendanceRowAdapter(studentList, currentAttendance, studentNames) { pid ->
                    currentAttendance[pid] = if (currentAttendance[pid] == "present") "absent" else "present"
                    studentList = getSortedList()
                    (rvAttendance.adapter as AttendanceRowAdapter).updateData(studentList)
                }
                rvAttendance.adapter = adapter
                rvContainer.addView(rvAttendance)

                val titleLabel = buildString {
                    append(subject)
                    if (classYear.isNotBlank()) append(" · $classYear")
                    if (division.isNotBlank())  append("-$division")
                }

                val dialog = AlertDialog.Builder(ctx)
                    .setTitle(titleLabel)
                    .setView(rvContainer)
                    .setNeutralButton("Update Attendance", null) // Will handle manually
                    .setPositiveButton("Done", null)
                    .show()

                // Special handling for Update button to prevent dialog close
                dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                    val batch = com.google.gson.JsonArray()
                    currentAttendance.forEach { (pid, stat) ->
                        batch.add(JsonObject().apply {
                            addProperty("person_id", pid)
                            addProperty("status",    stat)
                        })
                    }
                    val updateBody = JsonObject().apply { add("entries", batch) }
                    
                    it.isEnabled = false
                    Toast.makeText(ctx, "Updating…", Toast.LENGTH_SHORT).show()
                    
                    RetrofitClient.getService().markFacultyLectureAttendance(lectureId, updateBody)
                        .enqueue(object : Callback<JsonObject> {
                            override fun onResponse(c: Call<JsonObject>, r: Response<JsonObject>) {
                                if (!isAdded) return
                                dialog.getButton(AlertDialog.BUTTON_NEUTRAL).isEnabled = true
                                if (r.isSuccessful) {
                                    Toast.makeText(ctx, "Updated successfully!", Toast.LENGTH_SHORT).show()
                                    loadSessions() // Refresh main list
                                } else {
                                    Toast.makeText(ctx, "Failed to update (Server error)", Toast.LENGTH_SHORT).show()
                                }
                            }
                            override fun onFailure(c: Call<JsonObject>, t: Throwable) {
                                if (!isAdded) return
                                dialog.getButton(AlertDialog.BUTTON_NEUTRAL).isEnabled = true
                                Toast.makeText(ctx, "Network error", Toast.LENGTH_SHORT).show()
                            }
                        })
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) { loading.dismiss(); return }
                loading.dismiss()
                Toast.makeText(ctx, "Network error — could not load attendance", Toast.LENGTH_SHORT).show()
            }
        })
    }

    inner class AttendanceRowAdapter(
        private var items: List<String>,
        private val currentAttendance: MutableMap<String, String>,
        private val studentNames: Map<String, String>,
        private val onToggle: (String) -> Unit
    ) : androidx.recyclerview.widget.RecyclerView.Adapter<AttendanceRowAdapter.VH>() {

        fun updateData(newItems: List<String>) {
            items = newItems
            notifyDataSetChanged()
        }
        
        inner class VH(view: View) : androidx.recyclerview.widget.RecyclerView.ViewHolder(view) {
            val tvAvatar = view.findViewById<TextView>(android.R.id.text1)
            val tvName = view.findViewById<TextView>(android.R.id.text2)
            val tvStatus = view.findViewById<TextView>(android.R.id.summary)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val ctx = parent.context
            val row = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = android.view.Gravity.CENTER_VERTICAL
                setPadding(12, 16, 12, 16)
                isClickable = true
                isFocusable = true
                val tv = android.util.TypedValue()
                ctx.theme.resolveAttribute(android.R.attr.selectableItemBackground, tv, true)
                if (tv.resourceId != 0) background = ContextCompat.getDrawable(ctx, tv.resourceId)
            }
            
            val avatarSize = (36 * ctx.resources.displayMetrics.density).toInt()
            val tvAvatar = TextView(ctx).apply {
                id = android.R.id.text1
                layoutParams = LinearLayout.LayoutParams(avatarSize, avatarSize)
                gravity = android.view.Gravity.CENTER
                textSize = 14f
                setTextColor(android.graphics.Color.WHITE)
            }
            row.addView(tvAvatar)
            
            val tvName = TextView(ctx).apply {
                id = android.R.id.text2
                textSize = 15f
                setTextColor(0xFFFFFFFF.toInt())
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                setPadding(24, 0, 0, 0)
            }
            row.addView(tvName)
            
            val tvStatus = TextView(ctx).apply {
                id = android.R.id.summary
                textSize = 12f
                setPadding(12, 4, 12, 4)
            }
            row.addView(tvStatus)
            
            return VH(row)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val pid = items[position]
            val name = studentNames[pid] ?: "Unknown"
            val isPresent = currentAttendance[pid] == "present"
            
            holder.tvAvatar.text = if (name.isNotBlank()) name.first().uppercase() else "?"
            val bgColor = if (isPresent) 0xFF388E3C.toInt() else 0xFFD32F2F.toInt()
            holder.tvAvatar.background = android.graphics.drawable.GradientDrawable().apply {
                shape = android.graphics.drawable.GradientDrawable.OVAL
                setColor(bgColor)
            }
            
            holder.tvName.text = name
            holder.tvStatus.text = if (isPresent) "Present" else "Absent"
            holder.tvStatus.setTextColor(if (isPresent) 0xFF4CAF50.toInt() else 0xFFF44336.toInt())
            holder.tvStatus.background = android.graphics.drawable.GradientDrawable().apply {
                setStroke(2, if (isPresent) 0xFF4CAF50.toInt() else 0xFFF44336.toInt())
                cornerRadius = 8f
            }
            
            holder.itemView.setOnClickListener { onToggle(pid) }
        }

        override fun getItemCount() = items.size
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
            db.insertFacultyAttendance(lectureId, r.personId!!, r.personName, "", ts, r.status, r.confidence, r.faceBitmap)
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

    // ── Relabel and Save Embedding ────────────────────────────────────────────

    private fun showRelabelDialog(face: ScanResult) {
        val ctx = requireContext()

        // Use in-memory cached person list (loaded when students were synced)
        val ids   = mutableListOf<String>()
        val names = mutableListOf<String>()
        for (p in DBManager.personList) {
            val pid = p.id ?: p.localUid ?: continue
            if (pid.isBlank()) continue
            ids.add(pid)
            names.add(p.name ?: "Unknown")
        }

        if (ids.isEmpty()) {
            Toast.makeText(ctx, "No students cached — load students from Home tab first", Toast.LENGTH_LONG).show()
            return
        }

        val spinner = android.widget.Spinner(ctx).apply {
            setPadding(0, 24, 0, 24)
        }
        spinner.adapter = android.widget.ArrayAdapter(ctx, android.R.layout.simple_spinner_dropdown_item, names.toTypedArray())
        val currentIdx = ids.indexOfFirst { it == face.personId }.coerceAtLeast(0)
        spinner.setSelection(currentIdx)

        AlertDialog.Builder(ctx)
            .setTitle("Relabel Face")
            .setMessage("Select the correct student:")
            .setView(spinner)
            .setPositiveButton("Save") { _, _ ->
                val pickedIdx  = spinner.selectedItemPosition
                val pickedId   = ids[pickedIdx]
                val pickedName = names[pickedIdx]
                relabelAndSave(face, pickedId, pickedName)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun relabelAndSave(face: ScanResult, newPersonId: String, newPersonName: String) {
        val ctx = requireContext()
        
        // Update local state
        face.personId   = newPersonId
        face.personName = newPersonName
        resultsAdapter.notifyDataSetChanged()

        if (face.embVec.isBlank()) {
            Toast.makeText(ctx, "Relabeled (no embedding to save)", Toast.LENGTH_SHORT).show()
            return
        }

        val body = JsonObject().apply {
            addProperty("person_id", newPersonId)
            addProperty("emb_vec",   face.embVec)
        }
        
        RetrofitClient.getService().saveFaceEmbedding(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (!isAdded) return
                requireActivity().runOnUiThread {
                    if (resp.isSuccessful)
                        Toast.makeText(ctx, "Relabeled & embedding saved", Toast.LENGTH_SHORT).show()
                    else
                        Toast.makeText(ctx, "Relabeled locally (sync failed)", Toast.LENGTH_SHORT).show()
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                requireActivity().runOnUiThread {
                    Toast.makeText(ctx, "Relabeled locally (offline)", Toast.LENGTH_SHORT).show()
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
