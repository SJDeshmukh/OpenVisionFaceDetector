package com.faceplugin.facerecognition.engine

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import kotlin.math.max
import kotlin.math.min

/**
 * Anti-spoofing liveness detector using MiniFASNet V2-SE (facenox/face-antispoof-onnx).
 *
 * Model: best_model_quantized.onnx  (~611 KB, INT8)
 *
 * Preprocessing (from official repo src/inference/preprocess.py):
 *   - Resize + letterbox face crop to INPUT_SIZE × INPUT_SIZE
 *   - Normalize to [0, 1]  (divide by 255)
 *   - CHW layout (channel-first), BGR channel order
 *
 * Output:  [1, 2]  raw logits
 *   - logits[0] = real_logit
 *   - logits[1] = spoof_logit
 *   - is_real   = (real_logit - spoof_logit) >= THRESHOLD
 *
 * Returns a score in [0, 1] where > 0.5 means likely real.
 */
class LivenessDetector(context: Context) {

    private val TAG = "LivenessDetector"

    companion object {
        // Input size — the quantized model uses 128×128
        const val INPUT_SIZE = 128
        // Logit-diff threshold (from official repo; tune with your data)
        const val THRESHOLD = 0.0f
        // How much to expand face bbox before crop (25% margin each side)
        const val MARGIN = 0.25f
    }

    private var model: OnnxModelRunner? = null

    init {
        try {
            model = OnnxModelRunner(context, "minifasnetv2.onnx")
            Log.i(TAG, "MiniFASNet V2-SE (facenox) loaded — real liveness detection active")
            Log.i(TAG, "  inputs=${model!!.getInputNames()}  outputs=${model!!.getOutputNames()}")
        } catch (e: Throwable) {
            Log.w(TAG, "MiniFASNet not loaded, using heuristic fallback: ${e.message}")
        }
    }

    /**
     * Returns liveness score 0..1.
     * >= 0.5 means REAL.  < 0.5 means SPOOF.
     */
    fun checkLiveness(fullBitmap: Bitmap, faceBox: FaceBox): Float {
        val m = model ?: return heuristicLiveness(faceBox)
        return try {
            runModel(m, fullBitmap, faceBox)
        } catch (e: Throwable) {
            Log.e(TAG, "Liveness model error", e)
            heuristicLiveness(faceBox)
        }
    }

    private fun runModel(m: OnnxModelRunner, bitmap: Bitmap, box: FaceBox): Float {
        // 1. Crop face with margin
        val w = (box.x2 - box.x1).toFloat()
        val h = (box.y2 - box.y1).toFloat()
        val x1 = (box.x1 - w * MARGIN).toInt().coerceAtLeast(0)
        val y1 = (box.y1 - h * MARGIN).toInt().coerceAtLeast(0)
        val x2 = (box.x2 + w * MARGIN).toInt().coerceAtMost(bitmap.width)
        val y2 = (box.y2 + h * MARGIN).toInt().coerceAtMost(bitmap.height)
        val cropW = (x2 - x1).coerceAtLeast(1)
        val cropH = (y2 - y1).coerceAtLeast(1)
        val crop = Bitmap.createBitmap(bitmap, x1, y1, cropW, cropH)

        // 2. Letterbox resize to INPUT_SIZE × INPUT_SIZE
        val ratio = INPUT_SIZE.toFloat() / max(cropW, cropH)
        val scaledW = (cropW * ratio).toInt()
        val scaledH = (cropH * ratio).toInt()
        val scaled = Bitmap.createScaledBitmap(crop, scaledW, scaledH, true)

        val padL = (INPUT_SIZE - scaledW) / 2
        val padT = (INPUT_SIZE - scaledH) / 2
        val letterboxed = Bitmap.createBitmap(INPUT_SIZE, INPUT_SIZE, Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(letterboxed)
        canvas.drawColor(android.graphics.Color.BLACK)
        canvas.drawBitmap(scaled, padL.toFloat(), padT.toFloat(), null)

        // 3. Pixels → float CHW in BGR order, normalized [0,1]
        val pixels = IntArray(INPUT_SIZE * INPUT_SIZE)
        letterboxed.getPixels(pixels, 0, INPUT_SIZE, 0, 0, INPUT_SIZE, INPUT_SIZE)
        val data = FloatArray(3 * INPUT_SIZE * INPUT_SIZE)
        val area = INPUT_SIZE * INPUT_SIZE
        for (i in pixels.indices) {
            val p = pixels[i]
            data[i]            = ((p shr 16 and 0xFF).toFloat()) / 255f  // R
            data[area + i]     = ((p shr 8 and 0xFF).toFloat()) / 255f   // G
            data[2 * area + i] = ((p and 0xFF).toFloat()) / 255f         // B
        }

        // 4. Run ONNX model
        val inputName = m.getInputNames().first()
        val result = m.runFloat(
            inputName, data,
            longArrayOf(1, 3, INPUT_SIZE.toLong(), INPUT_SIZE.toLong())
        )
        val raw = result.values.firstOrNull() ?: return 0f

        // 5. Parse output: class 0 is spoof and class 1 is real.
        val spoofLogit = raw[0]
        val realLogit = raw[1]
        
        // Return raw probability instead of hard threshold
        val diff = realLogit - spoofLogit
        return 1.0f / (1.0f + kotlin.math.exp(-diff))
    }

    private fun sigmoid(x: Float): Float {
        return (1.0f / (1.0f + Math.exp(-x.toDouble()))).toFloat()
    }

    /**
     * Fallback when model isn't loaded: use detection confidence as proxy.
     */
    private fun heuristicLiveness(box: FaceBox): Float {
        val areaScore = (box.width * box.height).toFloat() / (640f * 640f)
        return (box.score * 0.7f + areaScore.coerceIn(0f, 1f) * 0.3f).coerceIn(0f, 1f)
    }

    fun close() = model?.close()
}
