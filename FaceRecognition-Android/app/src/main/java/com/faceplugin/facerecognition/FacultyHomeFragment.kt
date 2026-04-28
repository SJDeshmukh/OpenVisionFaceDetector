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
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.WorkManager

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
        if (unsyncedCount > 0) {
            rowUnsynced.visibility  = View.VISIBLE
            tvUnsyncedCount.text    = "$unsyncedCount record${if (unsyncedCount == 1) "" else "s"} pending sync"
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
        val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val req = OneTimeWorkRequest.Builder(FaceDownloadWorker::class.java)
            .setConstraints(constraints).build()
        WorkManager.getInstance(requireContext())
            .enqueueUniqueWork("faculty-face-download-auto",
                androidx.work.ExistingWorkPolicy.KEEP, req)
        WorkManager.getInstance(requireContext())
            .getWorkInfoByIdLiveData(req.id)
            .observe(viewLifecycleOwner) { info ->
                if (info?.state?.isFinished == true) {
                    DBManager(requireContext()).loadPerson()
                    prefs.edit().putLong("faculty_student_last_sync", System.currentTimeMillis()).apply()
                    updateStats()
                }
            }
    }

    private fun loadStudents() {
        Toast.makeText(context, "Syncing student list…", Toast.LENGTH_SHORT).show()
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED).build()
        val req = OneTimeWorkRequest.Builder(FaceDownloadWorker::class.java)
            .setConstraints(constraints).build()
        WorkManager.getInstance(requireContext())
            .enqueueUniqueWork("faculty-face-download",
                androidx.work.ExistingWorkPolicy.REPLACE, req)
        WorkManager.getInstance(requireContext())
            .getWorkInfoByIdLiveData(req.id)
            .observe(viewLifecycleOwner) { info ->
                if (info?.state?.isFinished == true) {
                    DBManager(requireContext()).loadPerson()
                    updateStats()
                    showStudentListDialog()
                }
            }
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
        Toast.makeText(context, "Syncing attendance…", Toast.LENGTH_SHORT).show()
        FacultySessionManager.syncPendingAttendance(requireContext()) { synced, errors ->
            activity?.runOnUiThread {
                updateStats()
                val msg = if (errors == 0) "Synced $synced records" else "Synced: $synced, Errors: $errors"
                Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
            }
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
