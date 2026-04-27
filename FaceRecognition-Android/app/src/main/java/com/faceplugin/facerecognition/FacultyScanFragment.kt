package com.faceplugin.facerecognition

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.Image
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.util.Size
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.floatingactionbutton.FloatingActionButton
import com.ocp.facesdk.FaceBox
import com.ocp.facesdk.FaceDetectionParam
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Faculty live camera scan fragment.
 *
 * Flow:
 *  1. Camera shows live preview with real-time face boxes.
 *  2. Tap Capture → freeze frame, enhance, detect + recognise all faces.
 *  3. Results list with per-face name/confidence and present/absent toggle.
 *  4. Tap "Mark Attendance" → saves to local DB + tries server sync.
 *  5. Retake resets to live preview.
 */
class FacultyScanFragment : Fragment() {

    companion object {
        private const val TAG = "FacultyScan"
    }

    // ── Camera state ──────────────────────────────────────────────────────────
    private var cameraProvider: ProcessCameraProvider? = null
    private var cameraExecutor: ExecutorService         = Executors.newSingleThreadExecutor()
    private var latestBitmap: Bitmap?                  = null  // most recent camera frame
    private var capturedBitmap: Bitmap?                = null  // frozen frame for processing
    private var scanResults: MutableList<ScanResult>   = mutableListOf()
    private var isCapturing = false

    // ── Views ─────────────────────────────────────────────────────────────────
    private lateinit var previewView:      PreviewView
    private lateinit var faceView:         FaceView
    private lateinit var fabCapture:       FloatingActionButton
    private lateinit var layoutProcessing: LinearLayout
    private lateinit var tvProcessing:     TextView
    private lateinit var tvScanSession:    TextView
    private lateinit var tvResultsHeader:  TextView
    private lateinit var tvResultsCount:   TextView
    private lateinit var tvNoResults:      TextView
    private lateinit var rvResults:        RecyclerView
    private lateinit var rowActions:       LinearLayout
    private lateinit var btnRetake:        android.widget.Button
    private lateinit var btnMark:          android.widget.Button

    private lateinit var adapter: ScanResultAdapter

    // ── Data class for scan results ───────────────────────────────────────────
    data class ScanResult(
        val faceBox:    FaceBox,
        val faceBitmap: Bitmap?,
        val personId:   String?,
        val personName: String,
        val confidence: Float,
        var status:     String = "present"
    )

    // ── Fragment lifecycle ────────────────────────────────────────────────────

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View = inflater.inflate(R.layout.fragment_faculty_scan, container, false)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        bindViews(view)
        adapter = ScanResultAdapter(scanResults) { result, newStatus ->
            result.status = newStatus
        }
        rvResults.layoutManager = LinearLayoutManager(requireContext())
        rvResults.adapter       = adapter

        updateSessionLabel()

        fabCapture.setOnClickListener { captureAndProcess() }
        btnRetake.setOnClickListener  { resetToLivePreview() }
        btnMark.setOnClickListener    { markAttendance() }

        // Check if launched with a gallery image URI
        val uriStr = arguments?.getString("image_uri")
        if (uriStr != null) {
            processGalleryImage(Uri.parse(uriStr))
        } else {
            startCamera()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        cameraProvider?.unbindAll()
        cameraExecutor.shutdown()
        capturedBitmap?.recycle()
        capturedBitmap = null
    }

    // ── Camera setup ──────────────────────────────────────────────────────────

    private fun startCamera() {
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 1)
            return
        }
        val future = ProcessCameraProvider.getInstance(requireContext())
        future.addListener({
            cameraProvider = future.get()
            bindCamera()
        }, ContextCompat.getMainExecutor(requireContext()))
    }

    @SuppressLint("RestrictedApi")
    private fun bindCamera() {
        val rotation = previewView.display?.rotation ?: 0
        val target   = Utils.getOptimalResolution(requireContext())

        val selector = CameraSelector.Builder()
            .requireLensFacing(SettingsActivity.getCameraLens(requireContext()))
            .build()

        val preview = Preview.Builder()
            .setTargetResolution(target)
            .setTargetRotation(rotation)
            .build()
            .also { it.setSurfaceProvider(previewView.surfaceProvider) }

        val analyzer = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setTargetResolution(target)
            .setTargetRotation(rotation)
            .build()
            .also { it.setAnalyzer(cameraExecutor, FaceAnalyzer()) }

        try {
            cameraProvider?.unbindAll()
            cameraProvider?.bindToLifecycle(viewLifecycleOwner, selector, preview, analyzer)
        } catch (e: Exception) {
            Log.e(TAG, "Camera bind failed", e)
        }
    }

    inner class FaceAnalyzer : ImageAnalysis.Analyzer {
        @OptIn(ExperimentalGetImage::class)
        override fun analyze(proxy: ImageProxy) {
            if (isCapturing) { proxy.close(); return }
            try {
                val img = proxy.image ?: return
                val nv21 = Utils.yuv420ToNv21(img)
                val rotDeg = proxy.imageInfo.rotationDegrees
                val mode   = Utils.getCameraMode(rotDeg, SettingsActivity.getCameraLens(requireContext()))
                val bmp    = FaceSDKWrapper.yuv2Bitmap(nv21, img.width, img.height, mode)
                if (bmp != null) {
                    latestBitmap?.recycle()
                    latestBitmap = bmp

                    if (FaceSDKWrapper.isInitialized) {
                        val param = FaceDetectionParam()
                        val boxes = FaceSDKWrapper.faceDetection(bmp, param)
                        requireActivity().runOnUiThread {
                            faceView.setFrameSize(Size(bmp.width, bmp.height))
                            faceView.setFaceBoxes(boxes)
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Frame error: ${e.message}")
            } finally {
                proxy.close()
            }
        }
    }

    // ── Capture & process ─────────────────────────────────────────────────────

    private fun captureAndProcess() {
        if (isCapturing) return
        val bmp = latestBitmap ?: run {
            Toast.makeText(context, "No frame available yet", Toast.LENGTH_SHORT).show()
            return
        }
        if (!FaceSDKWrapper.isInitialized) {
            Toast.makeText(context, "Face model not ready yet, please wait…", Toast.LENGTH_SHORT).show()
            return
        }
        isCapturing = true
        capturedBitmap = bmp.copy(bmp.config, false)
        showProcessing(true, "Detecting faces…")

        Thread {
            processImage(capturedBitmap!!)
        }.start()
    }

    private fun processGalleryImage(uri: Uri) {
        showProcessing(true, "Loading image…")
        Thread {
            try {
                val stream = requireContext().contentResolver.openInputStream(uri)
                val bmp    = BitmapFactory.decodeStream(stream)
                stream?.close()
                if (bmp == null) {
                    requireActivity().runOnUiThread {
                        showProcessing(false)
                        Toast.makeText(context, "Failed to load image", Toast.LENGTH_SHORT).show()
                    }
                    return@Thread
                }
                capturedBitmap = bmp
                processImage(bmp)
            } catch (e: Exception) {
                Log.e(TAG, "Gallery image error", e)
                requireActivity().runOnUiThread { showProcessing(false) }
            }
        }.start()
    }

    private fun processImage(raw: Bitmap) {
        requireActivity().runOnUiThread { showProcessing(true, "Enhancing image…") }

        // Apply image enhancement (adaptive contrast + sharpening)
        val enhanced = ImageEnhancer.enhance(raw)

        requireActivity().runOnUiThread { showProcessing(true, "Detecting faces…") }

        val param = FaceDetectionParam().also {
            it.check_liveness = true
            it.check_liveness_level = SettingsActivity.getLivenessLevel(requireContext())
        }
        val boxes = FaceSDKWrapper.faceDetection(enhanced, param)

        requireActivity().runOnUiThread { showProcessing(true, "Recognising ${boxes.size} face(s)…") }

        val results = mutableListOf<ScanResult>()
        val threshold = SettingsActivity.getIdentifyThreshold(requireContext())

        for (box in boxes) {
            val template = FaceSDKWrapper.templateExtraction(enhanced, box) ?: continue
            var bestPerson: Person? = null
            var bestSim = 0f

            synchronized(DBManager.personList) {
                for (person in DBManager.personList) {
                    if (person.templates == null) continue
                    val sim = FaceSDKWrapper.similarityCalculation(template, person.templates)
                    if (sim > bestSim) { bestSim = sim; bestPerson = person }
                }
            }

            val faceCrop = try { Utils.cropFace(enhanced, box) } catch (_: Exception) { null }

            val result = if (bestPerson != null && bestSim >= threshold) {
                ScanResult(
                    faceBox    = box,
                    faceBitmap = faceCrop,
                    personId   = bestPerson!!.id,
                    personName = bestPerson!!.name ?: "Unknown",
                    confidence = bestSim,
                    status     = "present"
                )
            } else {
                ScanResult(
                    faceBox    = box,
                    faceBitmap = faceCrop,
                    personId   = null,
                    personName = "Unknown (${(bestSim * 100).toInt()}%)",
                    confidence = bestSim,
                    status     = "present"
                )
            }
            results.add(result)
        }

        requireActivity().runOnUiThread {
            showProcessing(false)
            showResults(results, enhanced)
            isCapturing = false
        }
    }

    // ── Results display ───────────────────────────────────────────────────────

    private fun showResults(results: List<ScanResult>, bitmap: Bitmap) {
        scanResults.clear()
        scanResults.addAll(results)
        adapter.notifyDataSetChanged()

        val count = results.size
        tvResultsCount.text = "$count face${if (count == 1) "" else "s"}"

        // Show face boxes on the preview as a still
        faceView.setFrameSize(Size(bitmap.width, bitmap.height))
        faceView.setFaceBoxes(results.map { it.faceBox })

        tvNoResults.visibility    = if (count == 0) View.VISIBLE else View.GONE
        rvResults.visibility      = if (count > 0) View.VISIBLE else View.GONE
        rowActions.visibility     = View.VISIBLE
        fabCapture.visibility     = View.GONE
    }

    private fun resetToLivePreview() {
        scanResults.clear()
        adapter.notifyDataSetChanged()
        capturedBitmap?.recycle(); capturedBitmap = null
        isCapturing         = false

        tvResultsCount.text = "0 faces"
        tvNoResults.visibility = View.VISIBLE
        rvResults.visibility   = View.GONE
        rowActions.visibility  = View.GONE
        fabCapture.visibility  = View.VISIBLE

        faceView.setFaceBoxes(null)

        if (arguments?.getString("image_uri") == null) {
            bindCamera()
        }
    }

    // ── Mark attendance ───────────────────────────────────────────────────────

    private fun markAttendance() {
        val session = FacultySessionManager.currentSession
        if (session == null) {
            Toast.makeText(context, "No session selected — please start a session first", Toast.LENGTH_SHORT).show()
            return
        }

        val toMark = scanResults.filter { !it.personId.isNullOrBlank() }
        if (toMark.isEmpty()) {
            Toast.makeText(context, "No recognised students to mark", Toast.LENGTH_SHORT).show()
            return
        }

        val db    = DBManager(requireContext())
        val ts    = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date())

        toMark.forEach { result ->
            db.insertFacultyAttendance(
                session.lectureId,
                result.personId!!,
                result.personName,
                "",
                ts,
                result.status,
                result.confidence
            )
        }

        Toast.makeText(context, "Marked ${toMark.size} students — syncing…", Toast.LENGTH_SHORT).show()

        // Attempt immediate server sync
        val online = try { NetworkUtils.isOnline(requireContext()) } catch (_: Exception) { false }
        if (online && session.lectureId > 0) {
            syncDirectToServer(session.lectureId, toMark, ts)
        } else {
            Toast.makeText(context, "Saved offline — will sync when connected", Toast.LENGTH_SHORT).show()
            resetToLivePreview()
        }
    }

    private fun syncDirectToServer(lectureId: Int, results: List<ScanResult>, ts: String) {
        val arr = com.google.gson.JsonArray()
        results.forEach { r ->
            com.google.gson.JsonObject().also { o ->
                o.addProperty("person_id", r.personId)
                o.addProperty("status",    r.status)
            }.let { arr.add(it) }
        }
        val body = com.google.gson.JsonObject().apply {
            add("attendance", arr)
        }

        com.faceplugin.facerecognition.api.RetrofitClient.getService()
            .markFacultyLectureAttendance(lectureId, body)
            .enqueue(object : retrofit2.Callback<com.google.gson.JsonObject> {
                override fun onResponse(
                    call: retrofit2.Call<com.google.gson.JsonObject>,
                    resp: retrofit2.Response<com.google.gson.JsonObject>
                ) {
                    if (resp.isSuccessful) {
                        // Mark rows as synced in local DB
                        val db = DBManager(requireContext())
                        for (pair in db.unsyncedFacultyAttendance) {
                            db.markFacultyAttendanceSynced(pair.first)
                        }
                        requireActivity().runOnUiThread {
                            Toast.makeText(context, "Attendance synced!", Toast.LENGTH_SHORT).show()
                            resetToLivePreview()
                        }
                    } else {
                        requireActivity().runOnUiThread {
                            Toast.makeText(context, "Saved offline (server error ${resp.code()})", Toast.LENGTH_SHORT).show()
                            resetToLivePreview()
                        }
                    }
                }
                override fun onFailure(call: retrofit2.Call<com.google.gson.JsonObject>, t: Throwable) {
                    requireActivity().runOnUiThread {
                        Toast.makeText(context, "Saved offline — no network", Toast.LENGTH_SHORT).show()
                        resetToLivePreview()
                    }
                }
            })
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun showProcessing(show: Boolean, label: String = "") {
        layoutProcessing.visibility = if (show) View.VISIBLE else View.GONE
        if (label.isNotBlank()) tvProcessing.text = label
    }

    private fun updateSessionLabel() {
        val session = FacultySessionManager.currentSession
        tvScanSession.text = session?.displayLabel ?: "No session — tap Home to create one"
    }

    private fun bindViews(v: View) {
        previewView      = v.findViewById(R.id.faculty_preview)
        faceView         = v.findViewById(R.id.faculty_face_view)
        fabCapture       = v.findViewById(R.id.fab_capture)
        layoutProcessing = v.findViewById(R.id.layout_processing)
        tvProcessing     = v.findViewById(R.id.tv_processing_label)
        tvScanSession    = v.findViewById(R.id.tv_scan_session)
        tvResultsHeader  = v.findViewById(R.id.tv_results_header)
        tvResultsCount   = v.findViewById(R.id.tv_results_count)
        tvNoResults      = v.findViewById(R.id.tv_no_results)
        rvResults        = v.findViewById(R.id.rv_scan_results)
        rowActions       = v.findViewById(R.id.row_action_buttons)
        btnRetake        = v.findViewById(R.id.btn_retake)
        btnMark          = v.findViewById(R.id.btn_mark_attendance)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            startCamera()
        }
    }
}

// ── RecyclerView Adapter ──────────────────────────────────────────────────────

class ScanResultAdapter(
    private val items: List<FacultyScanFragment.ScanResult>,
    private val onStatusChanged: (FacultyScanFragment.ScanResult, String) -> Unit
) : RecyclerView.Adapter<ScanResultAdapter.VH>() {

    inner class VH(view: View) : RecyclerView.ViewHolder(view) {
        val ivFace:      android.widget.ImageView = view.findViewById(R.id.iv_face_thumb)
        val tvName:      TextView                 = view.findViewById(R.id.tv_person_name)
        val tvConf:      TextView                 = view.findViewById(R.id.tv_confidence)
        val tvStatus:    TextView                 = view.findViewById(R.id.tv_status_badge)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_scan_result, parent, false))

    override fun onBindViewHolder(holder: VH, pos: Int) {
        val item = items[pos]
        holder.tvName.text  = item.personName
        holder.tvConf.text  = "${(item.confidence * 100).toInt()}% match"
        holder.tvStatus.text = if (item.status == "present") "Present" else "Absent"
        holder.tvStatus.setTextColor(
            if (item.status == "present") 0xFF4CAF50.toInt() else 0xFFF44336.toInt()
        )
        if (item.personId == null) {
            holder.tvName.setTextColor(0xFFFF5555.toInt())
        } else {
            holder.tvName.setTextColor(0xFFFFFFFF.toInt())
        }
        if (item.faceBitmap != null) {
            holder.ivFace.setImageBitmap(item.faceBitmap)
        } else {
            holder.ivFace.setImageResource(R.drawable.openvision_logo)
        }
        // Tap to toggle present/absent
        holder.itemView.setOnClickListener {
            val newStatus = if (item.status == "present") "absent" else "present"
            onStatusChanged(item, newStatus)
            notifyItemChanged(pos)
        }
    }

    override fun getItemCount(): Int = items.size
}
