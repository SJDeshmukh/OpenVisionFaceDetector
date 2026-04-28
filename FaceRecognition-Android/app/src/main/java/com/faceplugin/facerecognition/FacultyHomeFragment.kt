package com.faceplugin.facerecognition

import android.app.AlertDialog
import android.graphics.Bitmap
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.faceplugin.facerecognition.api.RetrofitClient

class FacultyHomeFragment : Fragment() {

    private lateinit var tvFacultyName:  TextView
    private lateinit var tvSessionLabel: TextView
    private lateinit var tvSessionDetail: TextView
    private lateinit var rowUnsynced:    LinearLayout
    private lateinit var tvUnsyncedCount: TextView
    private lateinit var tvStudentCount: TextView
    private lateinit var tvModelStatus:  TextView

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View = inflater.inflate(R.layout.fragment_faculty_home, container, false)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        tvFacultyName   = view.findViewById(R.id.tv_faculty_name)
        tvSessionLabel  = view.findViewById(R.id.tv_session_label)
        tvSessionDetail = view.findViewById(R.id.tv_session_detail)
        rowUnsynced     = view.findViewById(R.id.row_unsynced)
        tvUnsyncedCount = view.findViewById(R.id.tv_unsynced_count)
        tvStudentCount  = view.findViewById(R.id.tv_student_count)
        tvModelStatus   = view.findViewById(R.id.tv_model_status)

        val prefs = requireContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE)
        val name  = prefs.getString("faculty_display_name", null)
            ?: prefs.getString("username", "Faculty")
        tvFacultyName.text = name ?: "Faculty"

        updateSessionDisplay()
        updateStats()
        autoSyncStudentsIfNeeded()

        view.findViewById<LinearLayout>(R.id.btn_scan).setOnClickListener {
            (activity as? FacultyActivity)?.navigateToScan()
        }
        view.findViewById<LinearLayout>(R.id.btn_upload).setOnClickListener { pickImageFromGallery() }
        view.findViewById<LinearLayout>(R.id.btn_load_students).setOnClickListener { loadStudents() }
        view.findViewById<android.widget.Button>(R.id.btn_sync_now).setOnClickListener { syncNow() }
    }

    override fun onResume() {
        super.onResume()
        updateSessionDisplay()
        updateStats()
    }

    override fun onHiddenChanged(hidden: Boolean) {
        super.onHiddenChanged(hidden)
        if (!hidden) {
            updateSessionDisplay()
            updateStats()
        }
    }

    // ── UI helpers ────────────────────────────────────────────────────────────

    private fun updateSessionDisplay() {
        val session = FacultySessionManager.currentSession
        if (session != null) {
            tvSessionLabel.text  = session.displayLabel
            tvSessionDetail.text = "Date: ${session.date} · Teacher: ${session.teacher.ifBlank { "You" }}"
        } else {
            tvSessionLabel.text  = "No session selected"
            tvSessionDetail.text = "Tap Scan to start a session"
        }
    }

    private fun updateStats() {
        val db = DBManager(requireContext())

        val studentCount = DBManager.personList.size
        tvStudentCount.text = "Students loaded: $studentCount"

        tvModelStatus.text = if (BuildConfig.IS_ATTENDX) "Detection: Server-side ✓" else if (FaceSDKWrapper.isInitialized) "Model: Ready ✓" else "Model: Loading…"

        val unsyncedCount = db.unsyncedFacultyCount
        val offlineCount  = db.offlineSessionCount
        val totalPending  = unsyncedCount + offlineCount
        if (totalPending > 0) {
            rowUnsynced.visibility  = View.VISIBLE
            val parts = mutableListOf<String>()
            if (unsyncedCount > 0) parts.add("$unsyncedCount attendance record${if (unsyncedCount == 1) "" else "s"}")
            if (offlineCount  > 0) parts.add("$offlineCount offline session${if (offlineCount == 1) "" else "s"}")
            tvUnsyncedCount.text = parts.joinToString(" · ") + " pending sync"
        } else {
            rowUnsynced.visibility = View.GONE
        }
    }

    // ── Actions ───────────────────────────────────────────────────────────────

    private fun autoSyncStudentsIfNeeded() {
        val prefs     = requireContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE)
        val lastSync  = prefs.getLong("faculty_student_last_sync", 0L)
        val oneHourMs = 60 * 60 * 1000L
        if (System.currentTimeMillis() - lastSync < oneHourMs) return
        // Use faculty-scoped download in background
        Thread {
            try {
                var resp = RetrofitClient.getService().downloadFacultyStudents().execute()
                // Fallback to generic if faculty endpoint not deployed (404)
                if (!resp.isSuccessful && resp.code() == 404) {
                    resp = RetrofitClient.getService().downloadFaces().execute()
                }
                if (resp.isSuccessful) {
                    importFacesToDb(resp.body()?.faces ?: emptyList())
                    prefs.edit().putLong("faculty_student_last_sync", System.currentTimeMillis()).apply()
                    activity?.runOnUiThread { updateStats() }
                }
            } catch (_: Exception) {}
        }.start()
    }

    private fun loadStudents() {
        Toast.makeText(context, "Syncing students for your classes…", Toast.LENGTH_SHORT).show()
        Thread {
            try {
                // Try faculty-scoped endpoint first
                var resp = RetrofitClient.getService().downloadFacultyStudents().execute()
                // Fallback to generic download if endpoint not deployed yet (404)
                if (!resp.isSuccessful && resp.code() == 404) {
                    val fallback = RetrofitClient.getService().downloadFaces().execute()
                    if (fallback.isSuccessful) {
                        importFacesToDb(fallback.body()?.faces ?: emptyList())
                        activity?.runOnUiThread { updateStats(); showStudentListDialog() }
                        return@Thread
                    }
                }
                if (resp.isSuccessful) {
                    importFacesToDb(resp.body()?.faces ?: emptyList())
                    activity?.runOnUiThread { updateStats(); showStudentListDialog() }
                } else {
                    val code = resp.code()
                    activity?.runOnUiThread {
                        Toast.makeText(context, "Sync failed (HTTP $code)", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                activity?.runOnUiThread {
                    Toast.makeText(context, "Sync error: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    private fun importFacesToDb(faces: List<com.faceplugin.facerecognition.api.SyncRequest>) {
        val db = DBManager(requireContext())
        for (faceData in faces) {
            try {
                val id = faceData.id ?: ""
                if (id.isBlank()) continue
                val name = faceData.name ?: ""
                val phone = faceData.phone ?: ""
                val dept = faceData.department ?: ""
                val desig = faceData.designation ?: ""
                val shift = faceData.shift ?: ""
                val customDataStr = faceData.customData?.toString() ?: ""
                val templatesB64 = faceData.templates

                // Resolve face image
                var faceBitmap: android.graphics.Bitmap? = null
                val faceB64 = faceData.faceImage
                val imageUrl = faceData.imageUrl

                if (!faceB64.isNullOrBlank() && !faceB64.startsWith("http") && !faceB64.startsWith("s3://")) {
                    try {
                        val bytes = android.util.Base64.decode(faceB64, android.util.Base64.NO_WRAP)
                        faceBitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    } catch (_: Exception) {}
                }
                if (faceBitmap == null && !imageUrl.isNullOrBlank()) {
                    try {
                        val conn = java.net.URL(imageUrl).openConnection()
                        conn.connectTimeout = 10000; conn.readTimeout = 15000
                        val stream = conn.getInputStream()
                        val bytes = stream.readBytes()
                        stream.close()
                        faceBitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    } catch (_: Exception) {}
                }

                val templates: ByteArray? = if (!templatesB64.isNullOrBlank()) {
                    try { android.util.Base64.decode(templatesB64, android.util.Base64.NO_WRAP) } catch (_: Exception) { null }
                } else null

                db.insertPerson(id, name, faceBitmap, templates ?: ByteArray(0), phone, dept, desig, shift, customDataStr, true)
            } catch (_: Exception) {}
        }
        db.loadPerson()
    }

    private fun showStudentListDialog() {
        val ctx = requireContext()
        val persons = DBManager.personList.toList()
        if (persons.isEmpty()) {
            Toast.makeText(ctx, "No students loaded", Toast.LENGTH_SHORT).show()
            return
        }

        val rv = RecyclerView(ctx).apply {
            layoutManager = LinearLayoutManager(ctx)
            adapter = StudentListAdapter(persons, DBManager(ctx))
            setPadding(0, 16, 0, 16)
        }

        AlertDialog.Builder(ctx)
            .setTitle("Students (${persons.size})")
            .setView(rv)
            .setPositiveButton("Done", null)
            .show()
    }

    private fun syncNow() {
        val db = DBManager(requireContext())
        val offlineSessions = db.offlineSessions
        if (offlineSessions.isNotEmpty()) {
            showPendingSessionsDialog(offlineSessions)
        } else {
            // No offline sessions — sync attendance records
            Toast.makeText(context, "Syncing attendance…", Toast.LENGTH_SHORT).show()
            FacultySessionManager.syncPendingAttendance(requireContext()) { synced, errors ->
                activity?.runOnUiThread {
                    updateStats()
                    val msg = if (errors == 0) "Synced $synced records" else "Synced: $synced, Errors: $errors"
                    Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun showPendingSessionsDialog(sessions: List<DBManager.OfflineSession>) {
        val ctx = requireContext()
        val items = sessions.map { s ->
            "${s.classYear ?: ""}-${s.division ?: ""} · ${s.subject ?: ""}\n${s.date ?: ""} · ${s.imageCount} image(s)"
        }.toTypedArray()

        AlertDialog.Builder(ctx)
            .setTitle("Pending Offline Sessions (${sessions.size})")
            .setItems(items) { _, which ->
                val session = sessions[which]
                showOfflineSessionDetail(session)
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showOfflineSessionDetail(session: DBManager.OfflineSession) {
        val ctx = requireContext()
        val db = DBManager(ctx)
        val imagePaths = db.getOfflineSessionImagePaths(session.id)

        val layout = android.widget.LinearLayout(ctx).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(24, 16, 24, 8)
        }

        // Session info
        android.widget.TextView(ctx).apply {
            text = "${session.classYear}-${session.division} · ${session.subject}\n${session.date} · ${imagePaths.size} images"
            textSize = 14f
            setPadding(0, 0, 0, 16)
        }.also { layout.addView(it) }

        // Thumbnail grid
        val scroll = android.widget.HorizontalScrollView(ctx)
        val row = android.widget.LinearLayout(ctx).apply {
            orientation = android.widget.LinearLayout.HORIZONTAL
            setPadding(0, 8, 0, 8)
        }
        for (path in imagePaths) {
            val file = java.io.File(path)
            if (!file.exists()) continue
            val iv = android.widget.ImageView(ctx).apply {
                val opts = android.graphics.BitmapFactory.Options().apply { inSampleSize = 4 }
                val bmp = android.graphics.BitmapFactory.decodeFile(path, opts)
                if (bmp != null) setImageBitmap(bmp)
                layoutParams = android.widget.LinearLayout.LayoutParams(200, 200).apply {
                    marginEnd = 8
                }
                scaleType = android.widget.ImageView.ScaleType.CENTER_CROP
            }
            row.addView(iv)
        }
        scroll.addView(row)
        layout.addView(scroll)

        val isOnline = NetworkUtils.isOnline(ctx)
        val dlg = AlertDialog.Builder(ctx)
            .setTitle("Offline Session")
            .setView(layout)
            .setNegativeButton("Close", null)
            .setNeutralButton("Delete") { _, _ ->
                db.deleteOfflineSession(session.id)
                updateStats()
                Toast.makeText(ctx, "Session deleted", Toast.LENGTH_SHORT).show()
            }

        if (isOnline) {
            dlg.setPositiveButton("Upload & Process") { _, _ ->
                uploadOfflineSession(session, imagePaths)
            }
        } else {
            dlg.setPositiveButton("Offline — Can't Upload") { d, _ -> d.dismiss() }
        }

        dlg.show()
    }

    private fun uploadOfflineSession(session: DBManager.OfflineSession, imagePaths: List<String>) {
        Toast.makeText(context, "Uploading ${imagePaths.size} images…", Toast.LENGTH_SHORT).show()
        Thread {
            val db = DBManager(requireContext())
            var uploaded = 0
            var errors = 0
            for (path in imagePaths) {
                try {
                    val file = java.io.File(path)
                    if (!file.exists()) { errors++; continue }
                    val bytes = file.readBytes()
                    val b64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
                    val body = com.google.gson.JsonObject().apply {
                        addProperty("image", "data:image/jpeg;base64,$b64")
                        addProperty("lecture_id", session.lectureId)
                    }
                    val resp = RetrofitClient.getService().scanFacultyImage(body).execute()
                    if (resp.isSuccessful) {
                        uploaded++
                        // Process scan results — store attendance
                        val respBody = resp.body()
                        val jobId = respBody?.get("job_id")?.takeIf { !it.isJsonNull }?.asString
                        if (jobId != null) {
                            // Poll until done (blocking)
                            pollUntilDone(jobId, session.lectureId, db)
                        } else if (respBody?.has("faces") == true) {
                            processOfflineResults(respBody, session.lectureId, db)
                        }
                    } else { errors++ }
                } catch (_: Exception) { errors++ }
            }
            db.markOfflineSessionUploaded(session.id)
            activity?.runOnUiThread {
                updateStats()
                val msg = "Uploaded $uploaded/${imagePaths.size} images" +
                    if (errors > 0) " ($errors failed)" else ""
                Toast.makeText(context, msg, Toast.LENGTH_LONG).show()
            }
        }.start()
    }

    private fun pollUntilDone(jobId: String, lectureId: Int, db: DBManager) {
        for (attempt in 0 until 90) {
            Thread.sleep(2000)
            try {
                val resp = RetrofitClient.getService().getScanStatus(jobId).execute()
                val body = resp.body() ?: continue
                val status = body.get("status")?.asString
                if (status == "done") {
                    processOfflineResults(body, lectureId, db)
                    return
                }
                if (status != "processing") return
            } catch (_: Exception) {}
        }
    }

    private fun processOfflineResults(body: com.google.gson.JsonObject, lectureId: Int, db: DBManager) {
        val facesArr = body.getAsJsonArray("faces") ?: return
        val ts = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US).format(java.util.Date())
        for (el in facesArr) {
            val face = el.asJsonObject
            val personId = face.get("person_id")?.takeIf { !it.isJsonNull }?.asString ?: continue
            val name = face.get("name")?.asString ?: "Unknown"
            val confidence = face.get("confidence")?.asFloat ?: 0f
            db.insertFacultyAttendance(lectureId, personId, name, "", ts, "present", confidence)
        }
    }

    private fun pickImageFromGallery() {
        val intent = android.content.Intent(android.content.Intent.ACTION_GET_CONTENT)
        intent.type = "image/*"
        startActivityForResult(intent, REQUEST_PICK_IMAGE)
    }

    @Deprecated("Use ActivityResultLauncher in future refactor")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_PICK_IMAGE && resultCode == android.app.Activity.RESULT_OK) {
            val uri = data?.data ?: return
            // Pass the URI to the scan fragment for processing
            val args = Bundle().apply { putString("image_uri", uri.toString()) }
            val scanFrag = FacultyScanFragment().also { it.arguments = args }
            parentFragmentManager.beginTransaction()
                .replace(R.id.faculty_fragment_container, scanFrag)
                .addToBackStack(null)
                .commit()
        }
    }

    companion object {
        private const val REQUEST_PICK_IMAGE = 4001

        // Palette for initial-letter avatars
        private val AVATAR_COLORS = intArrayOf(
            0xFF5C6BC0.toInt(), 0xFF26A69A.toInt(), 0xFFAB47BC.toInt(),
            0xFFEF5350.toInt(), 0xFF42A5F5.toInt(), 0xFFFF7043.toInt(),
            0xFF66BB6A.toInt(), 0xFFEC407A.toInt(), 0xFF7E57C2.toInt(),
            0xFF29B6F6.toInt()
        )
    }

    // ── Student List Adapter ──────────────────────────────────────────────────

    private class StudentListAdapter(
        private val persons: List<Person>,
        private val db: DBManager
    ) : RecyclerView.Adapter<StudentListAdapter.VH>() {

        class VH(view: View) : RecyclerView.ViewHolder(view) {
            val ivPhoto:     ImageView = view.findViewById(R.id.iv_student_photo)
            val tvInitial:   TextView  = view.findViewById(R.id.tv_student_initial)
            val tvName:      TextView  = view.findViewById(R.id.tv_student_name)
            val tvSubtitle:  TextView  = view.findViewById(R.id.tv_student_subtitle)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_student_card, parent, false))

        override fun onBindViewHolder(holder: VH, pos: Int) {
            val p = persons[pos]
            holder.tvName.text = p.name ?: "Unknown"

            // Subtitle: department / designation
            val subtitle = buildString {
                if (!p.department.isNullOrBlank()) append(p.department)
                if (!p.designation.isNullOrBlank()) {
                    if (isNotEmpty()) append(" · ")
                    append(p.designation)
                }
            }
            if (subtitle.isNotBlank()) {
                holder.tvSubtitle.text = subtitle
                holder.tvSubtitle.visibility = View.VISIBLE
            } else {
                holder.tvSubtitle.visibility = View.GONE
            }

            // Try to load face photo from DB
            val faceBitmap: Bitmap? = try {
                if (!p.localUid.isNullOrBlank()) db.getPersonFace(p.localUid) else null
            } catch (_: Exception) { null }

            if (faceBitmap != null) {
                holder.ivPhoto.setImageBitmap(faceBitmap)
                holder.ivPhoto.visibility = View.VISIBLE
                // Make it circular via clip
                holder.ivPhoto.clipToOutline = true
                holder.ivPhoto.outlineProvider = object : android.view.ViewOutlineProvider() {
                    override fun getOutline(view: View, outline: android.graphics.Outline) {
                        outline.setOval(0, 0, view.width, view.height)
                    }
                }
                holder.tvInitial.visibility = View.GONE
            } else {
                holder.ivPhoto.visibility = View.GONE
                holder.tvInitial.visibility = View.VISIBLE
                val initial = if (!p.name.isNullOrBlank()) p.name.first().uppercase() else "?"
                holder.tvInitial.text = initial
                val colorIdx = (p.name?.hashCode()?.and(0x7FFFFFFF) ?: 0) % AVATAR_COLORS.size
                val gd = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(AVATAR_COLORS[colorIdx])
                }
                holder.tvInitial.background = gd
            }
        }

        override fun getItemCount() = persons.size
    }
}
