package com.faceplugin.facerecognition

import android.app.AlertDialog
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.WorkManager
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

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

        view.findViewById<LinearLayout>(R.id.btn_new_session).setOnClickListener { showNewSessionDialog() }
        view.findViewById<LinearLayout>(R.id.btn_scan).setOnClickListener {
            val session = FacultySessionManager.currentSession
            if (session == null) {
                Toast.makeText(context, "Please start a session first", Toast.LENGTH_SHORT).show()
                showNewSessionDialog()
            } else {
                (activity as? FacultyActivity)?.navigateToScan()
            }
        }
        view.findViewById<LinearLayout>(R.id.btn_upload).setOnClickListener { pickImageFromGallery() }
        view.findViewById<LinearLayout>(R.id.btn_load_students).setOnClickListener { loadStudents() }
        view.findViewById<LinearLayout>(R.id.btn_sync).setOnClickListener { syncNow() }
        view.findViewById<LinearLayout>(R.id.btn_end_session).setOnClickListener { endSession() }
        view.findViewById<android.widget.Button>(R.id.btn_sync_now).setOnClickListener { syncNow() }
    }

    override fun onResume() {
        super.onResume()
        updateSessionDisplay()
        updateStats()
    }

    // ── UI helpers ────────────────────────────────────────────────────────────

    private fun updateSessionDisplay() {
        val session = FacultySessionManager.currentSession
        if (session != null) {
            tvSessionLabel.text  = session.displayLabel
            tvSessionDetail.text = "Date: ${session.date} · Teacher: ${session.teacher.ifBlank { "You" }}"
        } else {
            tvSessionLabel.text  = "No session selected"
            tvSessionDetail.text = "Tap 'New Session' to begin"
        }
    }

    private fun updateStats() {
        val db = DBManager(requireContext())

        val studentCount = DBManager.personList.size
        tvStudentCount.text = "Students loaded: $studentCount"

        tvModelStatus.text = if (FaceSDKWrapper.isInitialized) "Model: Ready ✓" else "Model: Loading…"

        val unsyncedCount = db.unsyncedFacultyCount
        if (unsyncedCount > 0) {
            rowUnsynced.visibility  = View.VISIBLE
            tvUnsyncedCount.text    = "$unsyncedCount record${if (unsyncedCount == 1) "" else "s"} pending sync"
        } else {
            rowUnsynced.visibility = View.GONE
        }
    }

    // ── Session dialog ────────────────────────────────────────────────────────

    private fun showNewSessionDialog() {
        val ctx = requireContext()

        // Try to load existing lectures from server first
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        RetrofitClient.getService().getFacultyLectures("", "", today).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (resp.isSuccessful) {
                    val lecturesArr = resp.body()?.getAsJsonArray("lectures")
                    val lectures = mutableListOf<FacultySessionManager.LectureSession>()
                    lecturesArr?.forEach { el ->
                        try {
                            val o = el.asJsonObject
                            lectures.add(FacultySessionManager.LectureSession(
                                lectureId = o.get("id").asInt,
                                subject   = o.get("subject")?.asString ?: "",
                                classYear = o.get("class_year")?.asString ?: "",
                                division  = o.get("division")?.asString ?: "",
                                date      = o.get("lecture_date")?.asString ?: today,
                                teacher   = o.get("teacher")?.asString ?: ""
                            ))
                        } catch (_: Exception) {}
                    }
                    showSessionPickerOrCreate(lectures)
                } else {
                    showCreateSessionDialog()
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                showCreateSessionDialog()
            }
        })
    }

    private fun showSessionPickerOrCreate(existing: List<FacultySessionManager.LectureSession>) {
        val ctx = requireContext()
        val options = existing.map { "${it.displayLabel} (${it.date})" }.toMutableList()
        options.add("+ Create New Session")

        AlertDialog.Builder(ctx)
            .setTitle("Select or Create Session")
            .setItems(options.toTypedArray()) { _, idx ->
                if (idx < existing.size) {
                    FacultySessionManager.setSession(ctx, existing[idx])
                    updateSessionDisplay()
                    Toast.makeText(ctx, "Session: ${existing[idx].displayLabel}", Toast.LENGTH_SHORT).show()
                } else {
                    showCreateSessionDialog()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showCreateSessionDialog() {
        val ctx  = requireContext()
        val form = LayoutInflater.from(ctx).inflate(R.layout.dialog_new_session, null, false)
        AlertDialog.Builder(ctx)
            .setTitle("New Session")
            .setView(form)
            .setPositiveButton("Create") { _, _ ->
                val subject   = form.findViewById<EditText>(R.id.et_subject).text.toString().trim()
                val classYear = form.findViewById<EditText>(R.id.et_class_year).text.toString().trim()
                val division  = form.findViewById<EditText>(R.id.et_division).text.toString().trim()
                if (subject.isBlank()) {
                    Toast.makeText(ctx, "Subject is required", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                createLecture(subject, classYear, division)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun createLecture(subject: String, classYear: String, division: String) {
        val ctx   = requireContext()
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val now   = SimpleDateFormat("HH:mm", Locale.US).format(Date())
        val prefs = ctx.getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE)
        val teacher = prefs.getString("faculty_display_name", null)
            ?: prefs.getString("username", "") ?: ""

        val body = JsonObject().apply {
            addProperty("subject",      subject)
            addProperty("class_year",   classYear)
            addProperty("division",     division)
            addProperty("lecture_date", today)
            addProperty("start_time",   now)
            addProperty("teacher",      teacher)
        }

        RetrofitClient.getService().createFacultyLecture(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (resp.isSuccessful) {
                    val lectureId = resp.body()?.get("lecture_id")?.asInt ?: -1
                    if (lectureId > 0) {
                        val session = FacultySessionManager.LectureSession(
                            lectureId = lectureId,
                            subject   = subject,
                            classYear = classYear,
                            division  = division,
                            date      = today,
                            teacher   = teacher
                        )
                        FacultySessionManager.setSession(ctx, session)
                        updateSessionDisplay()
                        Toast.makeText(ctx, "Session created: $subject", Toast.LENGTH_SHORT).show()
                    }
                } else {
                    Toast.makeText(ctx, "Failed to create session (offline?)", Toast.LENGTH_SHORT).show()
                    // Create a local-only session with id=-1 for offline tracking
                    val session = FacultySessionManager.LectureSession(
                        lectureId = -1,
                        subject   = subject,
                        classYear = classYear,
                        division  = division,
                        date      = today,
                        teacher   = teacher
                    )
                    FacultySessionManager.setSession(ctx, session)
                    updateSessionDisplay()
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                Toast.makeText(ctx, "Network error — session saved offline", Toast.LENGTH_SHORT).show()
                val session = FacultySessionManager.LectureSession(
                    lectureId = -1, subject = subject, classYear = classYear,
                    division = division, date = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date()),
                    teacher = ""
                )
                FacultySessionManager.setSession(ctx, session)
                updateSessionDisplay()
            }
        })
    }

    // ── Other actions ─────────────────────────────────────────────────────────

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
                    Toast.makeText(context, "Students loaded: ${DBManager.personList.size}", Toast.LENGTH_SHORT).show()
                }
            }
    }

    private fun syncNow() {
        Toast.makeText(context, "Syncing attendance…", Toast.LENGTH_SHORT).show()
        FacultySessionManager.syncPendingAttendance(requireContext()) { synced, errors ->
            activity?.runOnUiThread {
                updateStats()
                if (errors == 0) {
                    Toast.makeText(context, "Synced $synced records", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(context, "Synced: $synced, Errors: $errors", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun endSession() {
        val ctx = requireContext()
        AlertDialog.Builder(ctx)
            .setTitle("End Session")
            .setMessage("Mark session as complete and sync attendance?")
            .setPositiveButton("End & Sync") { _, _ ->
                syncNow()
                FacultySessionManager.clearSession(ctx)
                updateSessionDisplay()
            }
            .setNegativeButton("Just End") { _, _ ->
                FacultySessionManager.clearSession(ctx)
                updateSessionDisplay()
            }
            .setNeutralButton("Cancel", null)
            .show()
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
    }
}
