package com.faceplugin.facerecognition

import android.Manifest
import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Log
import android.view.GestureDetector
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.appcompat.app.AlertDialog
import androidx.camera.core.CameraControl
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.android.material.floatingactionbutton.FloatingActionButton
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class FacultyScanFragment : Fragment() {

    companion object {
        private const val TAG = "FacultyScan"
    }

    // Camera
    private var cameraProvider: ProcessCameraProvider? = null
    private val cameraExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    @Volatile private var latestNv21: ByteArray? = null
    @Volatile private var latestWidth = 0
    @Volatile private var latestHeight = 0
    private var useFrontCamera = false
    private var cameraControl: CameraControl? = null
    private var currentZoom = 0f

    // Views
    private lateinit var previewView: PreviewView
    private lateinit var fabCapture: FloatingActionButton
    private lateinit var fabFlip: FloatingActionButton
    private lateinit var viewCaptureRing: View
    private lateinit var seekbarZoom: SeekBar
    private lateinit var tvScanSession: TextView
    private lateinit var btnEndSession: Button
    private lateinit var tvPhotosHeader: TextView
    private lateinit var rvPhotoGrid: RecyclerView

    // Data
    private val photoCards = mutableListOf<PhotoCard>()
    private lateinit var photoAdapter: PhotoCardAdapter
    private val allFaces = mutableListOf<ScanResult>()
    @Volatile private var isCapturing = false

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View = inflater.inflate(R.layout.fragment_faculty_scan, container, false)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        bindViews(view)

        // Re-attach adapter to new RecyclerView (view is recreated on tab switch, data persists)
        photoAdapter = PhotoCardAdapter(photoCards) { card -> showCardDetail(card) }
        rvPhotoGrid.layoutManager = GridLayoutManager(requireContext(), 3)
        rvPhotoGrid.adapter = photoAdapter

        updateSessionLabel()
        updatePhotosHeader()
        setupZoom()
        setupPinchZoom()

        fabCapture.setOnClickListener { capturePhoto() }
        fabFlip.setOnClickListener { flipCamera() }
        btnEndSession.setOnClickListener { confirmEndSession() }

        val uriStr = arguments?.getString("image_uri")
        if (uriStr != null) {
            if (FacultySessionManager.currentSession == null) {
                showSessionPicker { importGalleryImage(android.net.Uri.parse(uriStr)) }
            } else {
                startCamera()
                importGalleryImage(android.net.Uri.parse(uriStr))
            }
        } else if (FacultySessionManager.currentSession == null) {
            showSessionPicker(null)
        } else {
            startCamera()
        }
    }

    override fun onHiddenChanged(hidden: Boolean) {
        super.onHiddenChanged(hidden)
        if (hidden) {
            cameraProvider?.unbindAll()
        } else {
            // Resume camera or show picker when fragment becomes visible again
            val ctx = context ?: return
            if (FacultySessionManager.currentSession != null) {
                startCamera()
            } else {
                showSessionPicker(null)
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        cameraProvider?.unbindAll()
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
        photoCards.forEach { it.thumbnail?.recycle() }
        photoCards.clear()
        allFaces.clear()
    }

    // ── Session picker ────────────────────────────────────────────────────────

    private fun showSessionPicker(afterStart: (() -> Unit)? = null) {
        val ctx = requireContext()
        val loading = ProgressBar(ctx)
        val dlg = AlertDialog.Builder(ctx)
            .setTitle("Select Session")
            .setView(loading)
            .setCancelable(false)
            .show()

        RetrofitClient.getService().getFacultyClasses().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (!isAdded) { dlg.dismiss(); return }
                dlg.dismiss()
                val arr = resp.body()?.getAsJsonArray("classes")
                if (resp.isSuccessful && arr != null && arr.size() > 0) {
                    buildSpinnerDialog(arr, afterStart)
                } else {
                    buildFallbackDialog(afterStart)
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) { dlg.dismiss(); return }
                dlg.dismiss()
                buildFallbackDialog(afterStart)
            }
        })
    }

    private data class ClassOpt(
        val classYear: String,
        val division: String,
        val label: String,
        val subjects: List<String>
    )

    private fun buildSpinnerDialog(arr: com.google.gson.JsonArray, afterStart: (() -> Unit)? = null) {
        val ctx = requireContext()
        val classes = mutableListOf<ClassOpt>()
        for (el in arr) {
            val o = el.asJsonObject
            val subjects = mutableListOf<String>()
            o.getAsJsonArray("subjects")?.forEach { s -> subjects.add(s.asString) }
            classes.add(ClassOpt(
                classYear = o.get("class_year")?.asString ?: "",
                division  = o.get("division")?.asString ?: "",
                label     = o.get("label")?.asString?.ifBlank {
                    "${o.get("class_year")?.asString}-${o.get("division")?.asString}"
                } ?: "",
                subjects  = subjects
            ))
        }

        val layout = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL; setPadding(48, 24, 48, 8)
        }

        TextView(ctx).apply { text = "Class"; textSize = 13f; setTextColor(0xFF888888.toInt()) }
            .also { layout.addView(it) }

        val spinnerClass = Spinner(ctx)
        ArrayAdapter(ctx, android.R.layout.simple_spinner_item, classes.map { it.label })
            .also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); spinnerClass.adapter = it }
        layout.addView(spinnerClass)

        TextView(ctx).apply {
            text = "Subject"; textSize = 13f; setTextColor(0xFF888888.toInt()); setPadding(0, 20, 0, 0)
        }.also { layout.addView(it) }

        val spinnerSubject = Spinner(ctx)
        var currentSubjects = classes.firstOrNull()?.subjects ?: emptyList()

        fun rebuildSubs(subjects: List<String>) {
            val items = if (subjects.isEmpty()) listOf("(none assigned)") else subjects
            ArrayAdapter(ctx, android.R.layout.simple_spinner_item, items)
                .also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); spinnerSubject.adapter = it }
        }
        rebuildSubs(currentSubjects)
        layout.addView(spinnerSubject)

        spinnerClass.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                currentSubjects = classes[pos].subjects; rebuildSubs(currentSubjects)
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        AlertDialog.Builder(ctx)
            .setTitle("New Session")
            .setView(layout)
            .setCancelable(false)
            .setPositiveButton("Start") { _, _ ->
                val sel = classes.getOrNull(spinnerClass.selectedItemPosition) ?: return@setPositiveButton
                val subject = currentSubjects.getOrNull(spinnerSubject.selectedItemPosition) ?: ""
                if (subject.isBlank()) {
                    Toast.makeText(ctx, "No subject available for this class", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                createAndStart(subject, sel.classYear, sel.division, afterStart)
            }
            .setNegativeButton("Cancel") { _, _ ->
                (activity as? FacultyActivity)?.navigateToHome()
            }
            .show()
    }

    private fun buildFallbackDialog(afterStart: (() -> Unit)? = null) {
        val ctx = requireContext()
        val layout = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 24, 48, 8) }
        val etSubject = EditText(ctx).apply { hint = "Subject (e.g. Maths)" }
        val etClass   = EditText(ctx).apply { hint = "Class year (e.g. FE)"; setPadding(0, 12, 0, 0) }
        val etDiv     = EditText(ctx).apply { hint = "Division (e.g. A)"; setPadding(0, 12, 0, 0) }
        layout.addView(etSubject); layout.addView(etClass); layout.addView(etDiv)

        AlertDialog.Builder(ctx)
            .setTitle("New Session")
            .setView(layout)
            .setCancelable(false)
            .setPositiveButton("Start") { _, _ ->
                val subject = etSubject.text.toString().trim()
                if (subject.isBlank()) {
                    Toast.makeText(ctx, "Subject is required", Toast.LENGTH_SHORT).show(); return@setPositiveButton
                }
                createAndStart(subject, etClass.text.toString().trim(), etDiv.text.toString().trim(), afterStart)
            }
            .setNegativeButton("Cancel") { _, _ ->
                (activity as? FacultyActivity)?.navigateToHome()
            }
            .show()
    }

    private fun createAndStart(subject: String, classYear: String, division: String, afterStart: (() -> Unit)? = null) {
        val ctx     = requireContext()
        val today   = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val now     = SimpleDateFormat("HH:mm", Locale.US).format(Date())
        val prefs   = ctx.getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE)
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
                if (!isAdded) return
                val lectureId = if (resp.isSuccessful) resp.body()?.get("lecture_id")?.asInt ?: -1 else -1
                val session = FacultySessionManager.LectureSession(
                    lectureId = lectureId, subject = subject,
                    classYear = classYear, division = division, date = today, teacher = teacher
                )
                FacultySessionManager.setSession(ctx, session)
                requireActivity().runOnUiThread {
                    clearScanState()
                    updateSessionLabel(); startCamera(); afterStart?.invoke()
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                val session = FacultySessionManager.LectureSession(
                    lectureId = -1, subject = subject, classYear = classYear,
                    division = division, date = today, teacher = teacher
                )
                FacultySessionManager.setSession(ctx, session)
                requireActivity().runOnUiThread {
                    Toast.makeText(ctx, "Offline — session saved locally", Toast.LENGTH_SHORT).show()
                    clearScanState()
                    updateSessionLabel(); startCamera(); afterStart?.invoke()
                }
            }
        })
    }

    private fun importGalleryImage(uri: android.net.Uri) {
        val session = FacultySessionManager.currentSession ?: return
        Thread {
            try {
                val stream = requireContext().contentResolver.openInputStream(uri)
                val bmp    = BitmapFactory.decodeStream(stream)
                stream?.close()
                if (bmp == null) return@Thread
                val jpeg  = bitmapToJpeg(bmp)
                val thumb = Bitmap.createScaledBitmap(bmp, 150, 150, true)
                bmp.recycle()
                val ts    = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())
                val file  = saveJpeg(jpeg, ts)
                val db    = DBManager(requireContext())
                val rowId = if (file != null) db.insertPendingImage(session.lectureId, file.absolutePath, ts) else -1L
                val card  = PhotoCard(rowId, file?.absolutePath ?: "", thumb, PhotoStatus.PROCESSING)
                requireActivity().runOnUiThread {
                    photoCards.add(0, card)
                    photoAdapter.notifyItemInserted(0)
                    rvPhotoGrid.scrollToPosition(0)
                    updatePhotosHeader()
                }
                uploadCard(card, jpeg, rowId, db)
            } catch (e: Exception) { Log.e(TAG, "Gallery import error", e) }
        }.start()
    }

    // ── Camera ────────────────────────────────────────────────────────────────

    private fun startCamera() {
        val ctx = context ?: return
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            @Suppress("DEPRECATION")
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 1)
            return
        }
        ProcessCameraProvider.getInstance(ctx).also { future ->
            future.addListener({
                try {
                    cameraProvider = future.get()
                    bindCamera()
                } catch (e: Exception) {
                    Log.e(TAG, "Error getting camera provider", e)
                }
            }, ContextCompat.getMainExecutor(ctx))
        }
    }

    @SuppressLint("RestrictedApi")
    private fun bindCamera() {
        val provider = cameraProvider ?: return
        val rotation = previewView.display?.rotation ?: 0
        val target   = Utils.getOptimalResolution(requireContext())
        val selector = CameraSelector.Builder()
            .requireLensFacing(if (useFrontCamera) CameraSelector.LENS_FACING_FRONT else CameraSelector.LENS_FACING_BACK)
            .build()
        val preview = Preview.Builder()
            .setTargetResolution(target).setTargetRotation(rotation).build()
            .also { it.setSurfaceProvider(previewView.surfaceProvider) }
        val analyzer = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setTargetResolution(target).setTargetRotation(rotation).build()
            .also { it.setAnalyzer(cameraExecutor, FrameGrabber()) }
        try {
            provider.unbindAll()
            val cam = provider.bindToLifecycle(viewLifecycleOwner, selector, preview, analyzer)
            cameraControl = cam.cameraControl
            cameraControl?.setLinearZoom(currentZoom)
        } catch (e: Exception) { Log.e(TAG, "Camera bind failed", e) }
    }

    private fun flipCamera() { useFrontCamera = !useFrontCamera; bindCamera() }

    private fun setupZoom() {
        seekbarZoom.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar, progress: Int, fromUser: Boolean) {
                if (fromUser) { currentZoom = progress / 100f; cameraControl?.setLinearZoom(currentZoom) }
            }
            override fun onStartTrackingTouch(sb: SeekBar) {}
            override fun onStopTrackingTouch(sb: SeekBar) {}
        })
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun setupPinchZoom() {
        val detector = ScaleGestureDetector(requireContext(),
            object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
                override fun onScale(det: ScaleGestureDetector): Boolean {
                    currentZoom = (currentZoom + (det.scaleFactor - 1f) * 0.5f).coerceIn(0f, 1f)
                    cameraControl?.setLinearZoom(currentZoom)
                    seekbarZoom.progress = (currentZoom * 100).toInt()
                    return true
                }
            })
        previewView.setOnTouchListener { v, ev ->
            val consumed = detector.onTouchEvent(ev)
            if (ev.action == MotionEvent.ACTION_UP && !detector.isInProgress) v.performClick()
            consumed
        }
    }

    inner class FrameGrabber : ImageAnalysis.Analyzer {
        @OptIn(ExperimentalGetImage::class)
        override fun analyze(proxy: ImageProxy) {
            if (isCapturing) { proxy.close(); return }
            try {
                val img = proxy.image ?: return
                latestNv21   = Utils.yuv420ToNv21(img)
                latestWidth  = img.width
                latestHeight = img.height
            } catch (_: Exception) {
            } finally { proxy.close() }
        }
    }

    // ── Capture & upload ──────────────────────────────────────────────────────

    private fun capturePhoto() {
        if (isCapturing) return
        val session = FacultySessionManager.currentSession
        if (session == null) { showSessionPicker(); return }

        isCapturing = true
        animateCaptureRing()

        // Wait 700 ms so the camera can stabilise after button press before grabbing the frame
        Handler(Looper.getMainLooper()).postDelayed({
            if (!isAdded) { isCapturing = false; return@postDelayed }
            val nv21 = latestNv21; val w = latestWidth; val h = latestHeight
            if (nv21 == null || w == 0) {
                Toast.makeText(context, "No frame — point camera at students", Toast.LENGTH_SHORT).show()
                isCapturing = false
                return@postDelayed
            }
            doCaptureFromFrame(nv21, w, h, session)
        }, 700L)
    }

    private fun doCaptureFromFrame(nv21: ByteArray, w: Int, h: Int, session: FacultySessionManager.LectureSession) {
        Thread {
            val bmp = nv21ToBitmap(nv21, w, h) ?: run {
                requireActivity().runOnUiThread { isCapturing = false }; return@Thread
            }
            val jpeg  = bitmapToJpeg(bmp)
            val thumb = Bitmap.createScaledBitmap(bmp, 150, 150, true)
            bmp.recycle()

            val ts   = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())
            val file = saveJpeg(jpeg, ts)
            val db   = DBManager(requireContext())
            val rowId = if (file != null) db.insertPendingImage(session.lectureId, file.absolutePath, ts) else -1L

            val card = PhotoCard(rowId, file?.absolutePath ?: "", thumb, PhotoStatus.PROCESSING)

            requireActivity().runOnUiThread {
                photoCards.add(0, card)
                photoAdapter.notifyItemInserted(0)
                rvPhotoGrid.scrollToPosition(0)
                updatePhotosHeader()
                isCapturing = false
            }

            uploadCard(card, jpeg, rowId, db)
        }.start()
    }

    private fun uploadCard(card: PhotoCard, jpeg: ByteArray, rowId: Long, db: DBManager) {
        val session = FacultySessionManager.currentSession ?: return
        val b64  = Base64.encodeToString(jpeg, Base64.NO_WRAP)
        val body = JsonObject().apply {
            addProperty("image",      "data:image/jpeg;base64,$b64")
            addProperty("lecture_id", session.lectureId)
        }

        RetrofitClient.getService().scanFacultyImage(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                if (!isAdded) return
                val respBody = resp.body()
                val jobId    = respBody?.get("job_id")?.takeIf { !it.isJsonNull }?.asString
                when {
                    resp.isSuccessful && jobId != null -> pollScanResult(card, jobId, db, rowId, 0)
                    resp.isSuccessful && respBody?.has("faces") == true ->
                        processDirectResponse(card, respBody, db, rowId)
                    else ->
                        requireActivity().runOnUiThread { card.status = PhotoStatus.ERROR; updateCard(card) }
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                requireActivity().runOnUiThread { card.status = PhotoStatus.ERROR; updateCard(card) }
            }
        })
    }

    private fun pollScanResult(card: PhotoCard, jobId: String, db: DBManager, rowId: Long, attempt: Int) {
        if (!isAdded) return
        if (attempt >= 90) {  // 90 × 2 s = 3 min max
            requireActivity().runOnUiThread { card.status = PhotoStatus.ERROR; updateCard(card) }
            return
        }
        Handler(Looper.getMainLooper()).postDelayed({
            if (!isAdded) return@postDelayed
            RetrofitClient.getService().getScanStatus(jobId).enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                    if (!isAdded) return
                    val body   = resp.body()
                    val status = body?.get("status")?.asString
                    when {
                        status == "done" -> processDirectResponse(card, body!!, db, rowId)
                        status == "processing" -> pollScanResult(card, jobId, db, rowId, attempt + 1)
                        else -> requireActivity().runOnUiThread { card.status = PhotoStatus.ERROR; updateCard(card) }
                    }
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                    if (!isAdded) return
                    // Retry on transient network errors
                    pollScanResult(card, jobId, db, rowId, attempt + 1)
                }
            })
        }, 2000L)
    }

    private fun processDirectResponse(card: PhotoCard, body: JsonObject, db: DBManager, rowId: Long) {
        if (rowId >= 0) db.updatePendingImageStatus(rowId, "uploaded")
        val facesArr = body.getAsJsonArray("faces") ?: com.google.gson.JsonArray()
        val newFaces = mutableListOf<ScanResult>()
        for (el in facesArr) {
            val face       = el.asJsonObject
            val personId   = face.get("person_id")?.takeIf { !it.isJsonNull }?.asString
            val name       = face.get("name")?.asString ?: "Unknown"
            val confidence = face.get("confidence")?.asFloat ?: 0f
            val thumbB64   = face.get("face_thumb")?.asString ?: ""
            val embVec     = face.get("emb_vec")?.takeIf { !it.isJsonNull }?.asString ?: ""
            val faceThumb  = decodeThumb(thumbB64)
            newFaces.add(ScanResult(faceThumb, personId, name, confidence,
                if (personId != null) "present" else "unknown", embVec))
            mergeIntoAllFaces(personId, name, confidence, faceThumb, embVec)
        }
        requireActivity().runOnUiThread {
            card.faces.addAll(newFaces)
            card.status = PhotoStatus.DONE
            updateCard(card)
        }
    }

    private fun updateCard(card: PhotoCard) {
        val idx = photoCards.indexOf(card)
        if (idx >= 0) photoAdapter.notifyItemChanged(idx)
    }

    @Synchronized
    private fun mergeIntoAllFaces(personId: String?, name: String, confidence: Float, thumb: Bitmap?, embVec: String = "") {
        if (personId == null) return
        val idx = allFaces.indexOfFirst { it.personId == personId }
        if (idx >= 0) {
            if (confidence > allFaces[idx].confidence) {
                val updated = allFaces[idx].copy(faceBitmap = thumb ?: allFaces[idx].faceBitmap, confidence = confidence)
                if (embVec.isNotBlank()) updated.embVec = embVec
                allFaces[idx] = updated
            }
        } else {
            allFaces.add(ScanResult(thumb, personId, name, confidence, "present", embVec))
        }
    }

    // ── Capture animation ─────────────────────────────────────────────────────

    private fun animateCaptureRing() {
        viewCaptureRing.visibility = View.VISIBLE
        viewCaptureRing.alpha  = 1f
        viewCaptureRing.scaleX = 1f
        viewCaptureRing.scaleY = 1f
        AnimatorSet().apply {
            playTogether(
                ObjectAnimator.ofFloat(viewCaptureRing, "scaleX", 1f, 2.8f),
                ObjectAnimator.ofFloat(viewCaptureRing, "scaleY", 1f, 2.8f),
                ObjectAnimator.ofFloat(viewCaptureRing, "alpha",  1f, 0f)
            )
            duration = 480
            start()
        }
    }

    // ── Card detail ───────────────────────────────────────────────────────────

    private fun showCardDetail(card: PhotoCard) {
        val ctx = requireContext()
        when (card.status) {
            PhotoStatus.PROCESSING -> {
                Toast.makeText(ctx, "Still processing…", Toast.LENGTH_SHORT).show(); return
            }
            PhotoStatus.ERROR -> {
                AlertDialog.Builder(ctx)
                    .setTitle("Upload failed")
                    .setMessage("Server could not process this photo. Retry?")
                    .setPositiveButton("Retry") { _, _ ->
                        card.status = PhotoStatus.PROCESSING
                        updateCard(card)
                        Thread {
                            val file = File(card.filePath)
                            if (file.exists()) {
                                val jpeg = file.readBytes()
                                uploadCard(card, jpeg, card.id, DBManager(ctx))
                            }
                        }.start()
                    }
                    .setNegativeButton("Dismiss", null).show()
                return
            }
            PhotoStatus.DONE -> { /* fall through */ }
        }
        if (card.faces.isEmpty()) {
            Toast.makeText(ctx, "No faces detected in this photo", Toast.LENGTH_SHORT).show(); return
        }

        val scroll = android.widget.ScrollView(ctx)
        val inner  = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 16, 24, 16) }
        scroll.addView(inner)

        for (face in card.faces) {
            val row = LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, 10, 0, 10)
            }

            val topRow = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity     = android.view.Gravity.CENTER_VERTICAL
            }

            val thumbPx = (56 * resources.displayMetrics.density).toInt()
            val iv = android.widget.ImageView(ctx).apply {
                layoutParams = LinearLayout.LayoutParams(thumbPx, thumbPx)
                scaleType    = android.widget.ImageView.ScaleType.CENTER_CROP
                if (face.faceBitmap != null) setImageBitmap(face.faceBitmap)
                else setImageResource(R.drawable.openvision_logo)
            }
            topRow.addView(iv)

            val col = LinearLayout(ctx).apply {
                orientation  = LinearLayout.VERTICAL
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                setPadding(16, 0, 0, 0)
            }
            col.addView(TextView(ctx).apply {
                text = face.personName; textSize = 14f
                setTextColor(if (face.personId != null) 0xFFFFFFFF.toInt() else 0xFFFF5555.toInt())
            })
            col.addView(TextView(ctx).apply {
                text = "${face.confidence.toInt()}% confidence"; textSize = 11f
                setTextColor(0x99FFFFFF.toInt())
            })
            topRow.addView(col)
            row.addView(topRow)

            // Action buttons row
            val btnRow = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity     = android.view.Gravity.CENTER_VERTICAL
                setPadding(0, 8, 0, 0)
            }

            fun makeBtn(label: String, bgColor: Int, action: () -> Unit): Button {
                return Button(ctx).apply {
                    text = label
                    textSize = 11f
                    setTextColor(0xFFFFFFFF.toInt())
                    backgroundTintList = android.content.res.ColorStateList.valueOf(bgColor)
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
                    ).also { it.setMargins(0, 0, 8, 0) }
                    setPadding(24, 8, 24, 8)
                    setOnClickListener { action() }
                }
            }

            var btnPresent: Button? = null
            var btnAbsent:  Button? = null

            fun refreshBtnColors() {
                val isPresent = face.status == "present"
                btnPresent?.backgroundTintList = android.content.res.ColorStateList.valueOf(
                    if (isPresent) 0xFF388E3C.toInt() else 0x44388E3C.toInt())
                btnAbsent?.backgroundTintList  = android.content.res.ColorStateList.valueOf(
                    if (!isPresent) 0xFFD32F2F.toInt() else 0x44D32F2F.toInt())
            }

            btnPresent = makeBtn("Present", if (face.status == "present") 0xFF388E3C.toInt() else 0x44388E3C.toInt()) {
                face.status = "present"
                allFaces.indexOfFirst { it.personId == face.personId }.takeIf { it >= 0 }
                    ?.let { i -> allFaces[i] = allFaces[i].copy(status = "present") }
                refreshBtnColors()
            }
            btnAbsent = makeBtn("Absent", if (face.status == "absent") 0xFFD32F2F.toInt() else 0x44D32F2F.toInt()) {
                face.status = "absent"
                allFaces.indexOfFirst { it.personId == face.personId }.takeIf { it >= 0 }
                    ?.let { i -> allFaces[i] = allFaces[i].copy(status = "absent") }
                refreshBtnColors()
            }
            val btnRelabel = makeBtn("Relabel", 0xFF1565C0.toInt()) { showRelabelDialog(face) }

            btnRow.addView(btnPresent)
            btnRow.addView(btnAbsent)
            btnRow.addView(btnRelabel)
            row.addView(btnRow)
            inner.addView(row)

            // Divider
            View(ctx).apply {
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 1).also { it.setMargins(0, 4, 0, 4) }
                setBackgroundColor(0x22FFFFFF)
            }.also { inner.addView(it) }
        }

        AlertDialog.Builder(ctx)
            .setTitle("Detected Faces (${card.faces.size})")
            .setView(scroll)
            .setPositiveButton("Done", null)
            .show()
    }

    private fun showRelabelDialog(face: ScanResult) {
        val ctx     = requireContext()
        val session = FacultySessionManager.currentSession ?: return
        val loading = Toast.makeText(ctx, "Loading students…", Toast.LENGTH_SHORT)
        loading.show()

        RetrofitClient.getService().getClassStudents(session.classYear, session.division)
            .enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                    if (!isAdded) return
                    loading.cancel()
                    val arr   = resp.body()?.getAsJsonArray("students") ?: com.google.gson.JsonArray()
                    val ids   = mutableListOf<String>()
                    val names = mutableListOf<String>()
                    for (el in arr) {
                        val s   = el.asJsonObject
                        val sid = s.get("id")?.asString ?: ""
                        if (sid.isNotBlank()) { ids.add(sid); names.add(s.get("name")?.asString ?: "") }
                    }
                    // Merge in locally cached students not already present (API may return only those with photos)
                    for (p in DBManager.personList) {
                        val pid = p.id ?: p.localUid ?: continue
                        if (pid.isBlank() || ids.contains(pid)) continue
                        ids.add(pid)
                        names.add(p.name ?: "Unknown")
                    }
                    if (ids.isEmpty()) {
                        requireActivity().runOnUiThread {
                            Toast.makeText(ctx, "No students found — try loading students from Home first", Toast.LENGTH_SHORT).show()
                        }
                        return
                    }
                    showRelabelSpinner(ctx, face, ids, names)
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                    if (!isAdded) return
                    loading.cancel()
                    val ids   = mutableListOf<String>()
                    val names = mutableListOf<String>()
                    for (p in DBManager.personList) {
                        val pid = p.id ?: p.localUid ?: continue
                        if (pid.isBlank()) continue
                        ids.add(pid)
                        names.add(p.name ?: "Unknown")
                    }
                    if (ids.isEmpty()) {
                        requireActivity().runOnUiThread {
                            Toast.makeText(ctx, "Could not load students (offline)", Toast.LENGTH_SHORT).show()
                        }
                        return
                    }
                    showRelabelSpinner(ctx, face, ids, names)
                }
            })
    }

    private fun showRelabelSpinner(ctx: android.content.Context, face: ScanResult,
                                   ids: List<String>, names: List<String>) {
        requireActivity().runOnUiThread {
            // Sort alphabetically by name while keeping id/name in sync
            val sorted = ids.zip(names).sortedBy { it.second }
            val sortedIds   = sorted.map { it.first }
            val sortedNames = sorted.map { it.second }

            val spinner = Spinner(ctx)
            spinner.adapter = ArrayAdapter(ctx, android.R.layout.simple_spinner_dropdown_item, sortedNames)
            val currentIdx = sortedIds.indexOfFirst { it == face.personId }.coerceAtLeast(0)
            spinner.setSelection(currentIdx)

            AlertDialog.Builder(ctx)
                .setTitle("Relabel Face")
                .setMessage("Select the correct student:")
                .setView(spinner)
                .setPositiveButton("Save") { _, _ ->
                    val pickedIdx  = spinner.selectedItemPosition
                    val pickedId   = sortedIds[pickedIdx]
                    val pickedName = sortedNames[pickedIdx]
                    relabelAndSave(face, pickedId, pickedName)
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun relabelAndSave(face: ScanResult, newPersonId: String, newPersonName: String) {
        val ctx = requireContext()
        val oldId = face.personId

        // Update local state immediately
        face.personId   = newPersonId
        face.personName = newPersonName
        val idx = allFaces.indexOfFirst { it.personId == oldId || it.personId == newPersonId }
        if (idx >= 0) {
            allFaces[idx] = allFaces[idx].copy().also {
                it.personId   = newPersonId
                it.personName = newPersonName
            }
        } else {
            allFaces.add(face)
        }

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

    // ── End session ───────────────────────────────────────────────────────────

    private fun confirmEndSession() {
        val ctx     = requireContext()
        val session = FacultySessionManager.currentSession
        if (session == null) { clearScanState(); showSessionPicker(null); return }

        val identified = allFaces.count { !it.personId.isNullOrBlank() }
        AlertDialog.Builder(ctx)
            .setTitle("End Session")
            .setMessage("Mark attendance for $identified identified student(s) and end the session?")
            .setPositiveButton("End & Mark") { _, _ -> markAndEnd() }
            .setNegativeButton("Discard") { _, _ ->
                FacultySessionManager.clearSession(ctx)
                clearScanState()
                showSessionPicker(null)
            }
            .setNeutralButton("Cancel", null)
            .show()
    }

    private fun markAndEnd() {
        val ctx     = requireContext()
        val session = FacultySessionManager.currentSession ?: return
        val toMark  = allFaces.filter { !it.personId.isNullOrBlank() }

        val db = DBManager(ctx)
        val ts = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date())
        toMark.forEach { r ->
            db.insertFacultyAttendance(session.lectureId, r.personId!!, r.personName, "", ts, r.status, r.confidence, r.faceBitmap)
        }

        if (toMark.isEmpty()) {
            FacultySessionManager.clearSession(ctx)
            clearScanState()
            showSessionPicker(null)
            return
        }

        val arr = com.google.gson.JsonArray()
        toMark.forEach { r ->
            arr.add(JsonObject().apply {
                addProperty("person_id",  r.personId)
                addProperty("status",     r.status)
                addProperty("timestamp",  ts)
                addProperty("confidence", r.confidence / 100f)
                r.faceBitmap?.let { bmp ->
                    val bos = ByteArrayOutputStream()
                    bmp.compress(Bitmap.CompressFormat.JPEG, 60, bos)
                    val b64 = "data:image/jpeg;base64," + Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP)
                    addProperty("image", b64)
                }
            })
        }

        RetrofitClient.getService().markFacultyLectureAttendance(session.lectureId,
            JsonObject().apply { add("attendance", arr) })
            .enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, resp: Response<JsonObject>) {
                    if (!isAdded) return
                    requireActivity().runOnUiThread {
                        if (resp.isSuccessful) {
                            for (p in db.unsyncedFacultyAttendance) db.markFacultyAttendanceSynced(p.first)
                            Toast.makeText(ctx, "✓ Attendance marked for ${toMark.size} student(s)", Toast.LENGTH_LONG).show()
                        } else {
                            Toast.makeText(ctx, "Saved locally — will sync later", Toast.LENGTH_SHORT).show()
                        }
                        FacultySessionManager.clearSession(ctx)
                        clearScanState()
                        showSessionPicker(null)
                    }
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                    if (!isAdded) return
                    requireActivity().runOnUiThread {
                        Toast.makeText(ctx, "Saved offline — will sync when connected", Toast.LENGTH_SHORT).show()
                        FacultySessionManager.clearSession(ctx)
                        clearScanState()
                        showSessionPicker(null)
                    }
                }
            })
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun clearScanState() {
        photoCards.forEach { it.thumbnail?.recycle() }
        photoCards.clear()
        allFaces.clear()
        photoAdapter.notifyDataSetChanged()
        updatePhotosHeader()
    }

    private fun updateSessionLabel() {
        tvScanSession.text = FacultySessionManager.currentSession?.displayLabel ?: "No session"
    }

    private fun updatePhotosHeader() {
        tvPhotosHeader.text = if (photoCards.isEmpty())
            "No photos yet — tap the camera to capture"
        else
            "${photoCards.size} photo${if (photoCards.size == 1) "" else "s"} captured"
    }

    private fun nv21ToBitmap(nv21: ByteArray, width: Int, height: Int): Bitmap? = try {
        val yuv = YuvImage(nv21, ImageFormat.NV21, width, height, null)
        val out = ByteArrayOutputStream()
        yuv.compressToJpeg(Rect(0, 0, width, height), 90, out)
        val bytes = out.toByteArray()
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
    } catch (_: Exception) { null }

    private fun bitmapToJpeg(bmp: Bitmap, quality: Int = 85): ByteArray {
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, quality, out)
        return out.toByteArray()
    }

    private fun saveJpeg(jpeg: ByteArray, ts: String): File? = try {
        val dir  = File(requireContext().filesDir, "faculty_pending").also { it.mkdirs() }
        val file = File(dir, "scan_$ts.jpg")
        FileOutputStream(file).use { it.write(jpeg) }
        file
    } catch (e: Exception) { Log.e(TAG, "Save JPEG failed", e); null }

    private fun decodeThumb(b64: String): Bitmap? = try {
        if (b64.isBlank()) null
        else {
            val payload = if (',' in b64) b64.substringAfter(',') else b64
            val bytes   = Base64.decode(payload, Base64.DEFAULT)
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }
    } catch (_: Exception) { null }

    private fun bindViews(v: View) {
        previewView     = v.findViewById(R.id.faculty_preview)
        fabCapture      = v.findViewById(R.id.fab_capture)
        fabFlip         = v.findViewById(R.id.fab_flip_camera)
        viewCaptureRing = v.findViewById(R.id.view_capture_ring)
        seekbarZoom     = v.findViewById(R.id.seekbar_zoom)
        tvScanSession   = v.findViewById(R.id.tv_scan_session)
        btnEndSession   = v.findViewById(R.id.btn_end_session)
        tvPhotosHeader  = v.findViewById(R.id.tv_photos_header)
        rvPhotoGrid     = v.findViewById(R.id.rv_photo_grid)
    }

    @Deprecated("Deprecated in Java")
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        @Suppress("DEPRECATION")
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) startCamera()
    }
}

// ── Photo card data model ─────────────────────────────────────────────────────

enum class PhotoStatus { PROCESSING, DONE, ERROR }

data class PhotoCard(
    val id: Long,
    val filePath: String,
    var thumbnail: Bitmap?,
    var status: PhotoStatus,
    val faces: MutableList<ScanResult> = mutableListOf()
)

// ── Photo card adapter (3-column grid) ───────────────────────────────────────

class PhotoCardAdapter(
    private val items: MutableList<PhotoCard>,
    private val onClick: (PhotoCard) -> Unit
) : RecyclerView.Adapter<PhotoCardAdapter.VH>() {

    inner class VH(view: View) : RecyclerView.ViewHolder(view) {
        val ivThumb:       android.widget.ImageView = view.findViewById(R.id.iv_photo_thumb)
        val overlayProc:   View                     = view.findViewById(R.id.overlay_processing)
        val tvFaceCount:   TextView                 = view.findViewById(R.id.tv_face_count)
        val tvErrorBadge:  TextView                 = view.findViewById(R.id.tv_error_badge)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_photo_card, parent, false))

    override fun onBindViewHolder(holder: VH, pos: Int) {
        val card = items[pos]
        if (card.thumbnail != null) holder.ivThumb.setImageBitmap(card.thumbnail)
        else holder.ivThumb.setImageResource(R.drawable.openvision_logo)

        holder.overlayProc.visibility  = if (card.status == PhotoStatus.PROCESSING) View.VISIBLE else View.GONE
        holder.tvErrorBadge.visibility = if (card.status == PhotoStatus.ERROR) View.VISIBLE else View.GONE
        if (card.status == PhotoStatus.DONE) {
            holder.tvFaceCount.visibility = View.VISIBLE
            holder.tvFaceCount.text = "${card.faces.size} face${if (card.faces.size == 1) "" else "s"}"
        } else {
            holder.tvFaceCount.visibility = View.GONE
        }
        holder.itemView.setOnClickListener { onClick(card) }
    }

    override fun getItemCount() = items.size
}

// ── ScanResult + ScanResultAdapter (used by FacultyHistoryFragment) ───────────

data class ScanResult(
    val faceBitmap: Bitmap?,
    var personId:   String?,
    var personName: String,
    val confidence: Float,
    var status:     String = "present",
    var embVec:     String = ""
)

class ScanResultAdapter(
    private val items: MutableList<ScanResult>,
    private val onStatusChanged: (ScanResult, String) -> Unit
    ) : RecyclerView.Adapter<ScanResultAdapter.VH>() {

    private var onRelabel: ((ScanResult) -> Unit)? = null
    private var onSaveEmbedding: ((ScanResult) -> Unit)? = null

    fun setRelabelCallback(cb: (ScanResult) -> Unit) { onRelabel = cb }
    fun setSaveEmbeddingCallback(cb: (ScanResult) -> Unit) { onSaveEmbedding = cb }

    inner class VH(view: View) : RecyclerView.ViewHolder(view) {
        val ivFace:   android.widget.ImageView = view.findViewById(R.id.iv_face_thumb)
        val tvName:   TextView                 = view.findViewById(R.id.tv_person_name)
        val tvConf:   TextView                 = view.findViewById(R.id.tv_confidence)
        val tvStatus: TextView                 = view.findViewById(R.id.tv_status_badge)
        val tvRelabel: TextView                = view.findViewById(R.id.tv_relabel)
        val tvSaveFace: TextView               = view.findViewById(R.id.tv_save_face)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_scan_result, parent, false))

    override fun onBindViewHolder(holder: VH, pos: Int) {
        val item = items[pos]
        holder.tvName.text = item.personName
        holder.tvConf.text = "${item.confidence.toInt()}% match"
        holder.tvStatus.text = if (item.status == "present") "Present" else "Absent"
        holder.tvStatus.setTextColor(if (item.status == "present") 0xFF4CAF50.toInt() else 0xFFF44336.toInt())
        holder.tvName.setTextColor(if (item.personId == null) 0xFFFF5555.toInt() else 0xFFFFFFFF.toInt())
        if (item.faceBitmap != null) holder.ivFace.setImageBitmap(item.faceBitmap) else holder.ivFace.setImageResource(R.drawable.openvision_logo)
        // Relabel button always visible
        holder.tvRelabel.setOnClickListener { onRelabel?.invoke(item) }
        // Save face button visible only if embedding exists
        if (item.embVec.isNotBlank()) {
            holder.tvSaveFace.visibility = View.VISIBLE
            holder.tvSaveFace.setOnClickListener { onSaveEmbedding?.invoke(item) }
        } else {
            holder.tvSaveFace.visibility = View.GONE
        }
        holder.itemView.setOnClickListener {
            val newStatus = if (item.status == "present") "absent" else "present"
            item.status = newStatus
            onStatusChanged(item, newStatus)
            notifyItemChanged(pos)
        }

    }

    override fun getItemCount() = items.size
}
