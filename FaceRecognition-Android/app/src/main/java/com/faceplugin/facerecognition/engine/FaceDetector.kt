package com.faceplugin.facerecognition.engine

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import kotlin.math.max
import kotlin.math.min

/**
 * Face detector using SCRFD 500M ONNX model.
 *
 * Input:  [1, 3, 640, 640] float32 RGB normalized image
 * Output: 9 tensors with numeric names (score*3, bbox*3, kps*3).
 *
 * Parsing strategy: group all outputs by their flat size.
 *   stride 8  ? anchorCount=12800 ? score=12800, bbox=51200, kps=128000
 *   stride 16 ? anchorCount=3200  ? score=3200,  bbox=12800, kps=32000
 *   stride 32 ? anchorCount=800   ? score=800,   bbox=3200,  kps=8000
 *
 * Disambiguation: score arrays have ALL values in [0,1].
 *                 bbox arrays have at least one value > 1.
 */
class FaceDetector(context: Context) {

    private val TAG = "FaceDetector"
    private val model = OnnxModelRunner(context, "scrfd_500m.onnx")
    private val ctx = context.applicationContext

    companion object {
        const val INPUT_SIZE = 640
        const val SCORE_THRESHOLD = 0.45f
        const val NMS_THRESHOLD   = 0.45f
        private val MEAN = floatArrayOf(127.5f, 127.5f, 127.5f)
        private val STD  = floatArrayOf(128f,   128f,   128f  )
        private val STRIDES     = intArrayOf(8, 16, 32)
        private val NUM_ANCHORS = 2
    }

    /**
     * Detect faces in a bitmap. Returns list of FaceBox in original image coordinates.
     */
    fun detect(bitmap: Bitmap): List<FaceBox> {
        val origW = bitmap.width
        val origH = bitmap.height

        // -- Letterbox resize to INPUT_SIZE × INPUT_SIZE -----------------------
        val scale = min(INPUT_SIZE.toFloat() / origW, INPUT_SIZE.toFloat() / origH)
        val newW  = (origW * scale).toInt()
        val newH  = (origH * scale).toInt()
        val padX  = (INPUT_SIZE - newW) / 2
        val padY  = (INPUT_SIZE - newH) / 2

        val scaled = Bitmap.createScaledBitmap(bitmap, newW, newH, true)
        val input  = Bitmap.createBitmap(INPUT_SIZE, INPUT_SIZE, Bitmap.Config.ARGB_8888)
        android.graphics.Canvas(input).apply {
            drawColor(android.graphics.Color.rgb(127, 127, 127))
            drawBitmap(scaled, padX.toFloat(), padY.toFloat(), null)
        }

        val floatData = bitmapToFloat(input)
        val inputName = model.getInputNames().first()
        val outputMap = model.runFloat(
            inputName, floatData,
            longArrayOf(1, 3, INPUT_SIZE.toLong(), INPUT_SIZE.toLong())
        )

        // -- Log all outputs so we can debug with: adb logcat -s FaceDetector -
        val sb = StringBuilder("SCRFD outputs [${outputMap.size}]:\n")
        for ((name, arr) in outputMap) {
            val maxV = arr.maxOrNull() ?: 0f
            val allIn01 = arr.all { it in 0f..1f }
            sb.append("  '$name'  size=${arr.size}  max=${"%.4f".format(maxV)}  allIn01=$allIn01\n")
        }
        Log.d(TAG, sb.toString())
        writeDebugToInternalStorage(sb.toString())

        // -- Group outputs by flat size -----------------------------------------
        val bySize = outputMap.values.groupBy { it.size }

        // -- Parse each stride --------------------------------------------------
        val boxes   = mutableListOf<FloatArray>()
        val scores  = mutableListOf<Float>()
        val kpsList = mutableListOf<FloatArray>()

        for (stride in STRIDES) {
            val fmW         = INPUT_SIZE / stride
            val fmH         = INPUT_SIZE / stride
            val anchorCount = fmW * fmH * NUM_ANCHORS  // 12800 / 3200 / 800

            // Try named outputs first (if model was exported with names)
            val scoreArrNamed = outputMap["score_$stride"] ?: outputMap["scores_$stride"]
            val bboxArrNamed  = outputMap["bbox_$stride"]  ?: outputMap["bboxes_$stride"]
            val kpsArrNamed   = outputMap["kps_$stride"]   ?: outputMap["kpss_$stride"]

            val scoreArr: FloatArray
            val bboxArr: FloatArray
            val kpsArr: FloatArray?

            if (scoreArrNamed != null && bboxArrNamed != null) {
                // Named outputs found — use them directly
                scoreArr = scoreArrNamed
                bboxArr  = bboxArrNamed
                kpsArr   = kpsArrNamed
            } else {
                // -- Positional fallback using size + value range --------------
                // Score candidates: size == anchorCount AND all values in [0,1]
                val scoreCandidates = (bySize[anchorCount] ?: emptyList())
                    .filter { arr -> arr.all { v -> v in 0f..1f } }
                if (scoreCandidates.isEmpty()) {
                    Log.w(TAG, "stride $stride: no score array found (anchorCount=$anchorCount)")
                    continue
                }
                scoreArr = scoreCandidates.first()

                // Bbox candidates: size == anchorCount*4, NOT the score array
                val bboxCandidates = (bySize[anchorCount * 4] ?: emptyList())
                    .filter { it !== scoreArr }
                if (bboxCandidates.isEmpty()) {
                    Log.w(TAG, "stride $stride: no bbox array found (size=${anchorCount*4})")
                    continue
                }
                bboxArr = bboxCandidates.first()

                // Kps candidates: size == anchorCount*10
                kpsArr = (bySize[anchorCount * 10] ?: emptyList()).firstOrNull()
            }

            Log.d(TAG, "stride=$stride  scoreMax=${scoreArr.maxOrNull()?.let{"%.3f".format(it)}}  bboxMax=${bboxArr.maxOrNull()?.let{"%.3f".format(it)}}")

            // -- Decode anchors ------------------------------------------------
            for (h in 0 until fmH) {
                for (w in 0 until fmW) {
                    for (a in 0 until NUM_ANCHORS) {
                        val i = (h * fmW + w) * NUM_ANCHORS + a

                        val score = scoreArr.getOrElse(i) { 0f }
                        if (score < SCORE_THRESHOLD) continue

                        val cx = (w + 0.5f) * stride
                        val cy = (h + 0.5f) * stride

                        val base = i * 4
                        val x1 = cx - bboxArr.getOrElse(base)     { 0f } * stride
                        val y1 = cy - bboxArr.getOrElse(base + 1) { 0f } * stride
                        val x2 = cx + bboxArr.getOrElse(base + 2) { 0f } * stride
                        val y2 = cy + bboxArr.getOrElse(base + 3) { 0f } * stride

                        val kps = FloatArray(10)
                        if (kpsArr != null) {
                            val kb = i * 10
                            for (k in 0 until 5) {
                                kps[k * 2]     = cx + kpsArr.getOrElse(kb + k * 2)     { 0f } * stride
                                kps[k * 2 + 1] = cy + kpsArr.getOrElse(kb + k * 2 + 1) { 0f } * stride
                            }
                        }
                        boxes.add(floatArrayOf(x1, y1, x2, y2))
                        scores.add(score)
                        kpsList.add(kps)
                    }
                }
            }
        }

        Log.d(TAG, "Pre-NMS faces: ${boxes.size}")
        val kept = nms(boxes, scores, NMS_THRESHOLD)
        Log.d(TAG, "Post-NMS faces: ${kept.size}")

        return kept.map { i ->
            val b   = boxes[i]
            val ox1 = ((b[0] - padX) / scale).toInt().coerceIn(0, origW)
            val oy1 = ((b[1] - padY) / scale).toInt().coerceIn(0, origH)
            val ox2 = ((b[2] - padX) / scale).toInt().coerceIn(0, origW)
            val oy2 = ((b[3] - padY) / scale).toInt().coerceIn(0, origH)
            val kps = kpsList[i].let { k ->
                FloatArray(10) { j ->
                    if (j % 2 == 0) ((k[j] - padX) / scale)
                    else            ((k[j] - padY) / scale)
                }
            }
            FaceBox(ox1, oy1, ox2, oy2, kps, scores[i])
        }
    }

    // -- Debug helpers ----------------------------------------------------------

    private fun writeDebugToInternalStorage(msg: String) {
        try {
            val f = java.io.File(ctx.filesDir, "face_debug_logs.txt")
            java.io.FileWriter(f, true).use { it.write(msg) }
        } catch (_: Throwable) {}
    }

    // -- Image helpers ----------------------------------------------------------

    private fun bitmapToFloat(bmp: Bitmap): FloatArray {
        val w      = bmp.width
        val h      = bmp.height
        val pixels = IntArray(w * h)
        bmp.getPixels(pixels, 0, w, 0, 0, w, h)
        val out = FloatArray(3 * h * w)
        for (i in pixels.indices) {
            val p = pixels[i]
            out[i]             = ((p shr 16 and 0xFF) - MEAN[0]) / STD[0]  // R
            out[w * h + i]     = ((p shr 8  and 0xFF) - MEAN[1]) / STD[1]  // G
            out[2 * w * h + i] = ((p and 0xFF)        - MEAN[2]) / STD[2]  // B
        }
        return out
    }

    // -- NMS -------------------------------------------------------------------

    private fun nms(boxes: List<FloatArray>, scores: List<Float>, threshold: Float): List<Int> {
        val order      = scores.indices.sortedByDescending { scores[it] }
        val suppressed = BooleanArray(boxes.size)
        val kept       = mutableListOf<Int>()
        for (idxI in order.indices) {
            val i = order[idxI]
            if (suppressed[i]) continue
            kept.add(i)
            val bi = boxes[i]
            for (idxJ in (idxI + 1) until order.size) {
                val j = order[idxJ]
                if (suppressed[j]) continue
                if (iou(bi, boxes[j]) > threshold) suppressed[j] = true
            }
        }
        return kept
    }

    private fun iou(a: FloatArray, b: FloatArray): Float {
        val ix1   = max(a[0], b[0]); val iy1 = max(a[1], b[1])
        val ix2   = min(a[2], b[2]); val iy2 = min(a[3], b[3])
        val inter = max(0f, ix2 - ix1) * max(0f, iy2 - iy1)
        val aA    = (a[2] - a[0]) * (a[3] - a[1])
        val bA    = (b[2] - b[0]) * (b[3] - b[1])
        return inter / (aA + bA - inter + 1e-6f)
    }

    fun close() = model.close()
}
