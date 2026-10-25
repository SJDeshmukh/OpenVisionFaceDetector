package com.faceplugin.facerecognition.engine

import android.content.Context
import android.graphics.Bitmap
import kotlin.math.sqrt

/**
 * Face embedding extractor using MobileFaceNet (w600k_mbf.onnx).
 *
 * Input:  [1, 3, 112, 112] float32 RGB normalized with mean=127.5 std=128
 * Output: [1, 512]  L2-normalized embedding
 *
 * Model: InsightFace buffalo_sc w600k_mbf.onnx (~13 MB)
 */
class EmbeddingExtractor(context: Context) {

    private val TAG = "EmbeddingExtractor"
    private val model = OnnxModelRunner(context, "mobilefacenet.onnx")

    companion object {
        const val EMBED_SIZE = 512
        private const val MEAN = 127.5f
        private const val STD = 128f
    }

    /**
     * Extract a 512-d embedding from an already-aligned 112×112 face crop.
     * The returned array is L2-normalized.
     */
    fun extract(alignedFace: Bitmap): FloatArray? {
        return try {
            val resized = if (alignedFace.width != 112 || alignedFace.height != 112)
                Bitmap.createScaledBitmap(alignedFace, 112, 112, true)
            else alignedFace

            val data = bitmapToFloat(resized)
            val inputName = model.getInputNames().first()
            val result = model.runFloat(
                inputName, data,
                longArrayOf(1, 3, 112, 112)
            )
            val raw = result.values.firstOrNull() ?: return null
            l2Normalize(raw)
        } catch (e: Throwable) {
            android.util.Log.e(TAG, "Embedding extraction failed", e)
            null
        }
    }

    /** Cosine similarity between two L2-normalized embeddings. Range [-1, 1]. */
    fun cosineSimilarity(a: FloatArray, b: FloatArray): Float {
        if (a.size != b.size) return 0f
        var dot = 0f
        for (i in a.indices) dot += a[i] * b[i]
        return dot.coerceIn(-1f, 1f)
    }

    private fun bitmapToFloat(bmp: Bitmap): FloatArray {
        val w = bmp.width; val h = bmp.height
        val pixels = IntArray(w * h)
        bmp.getPixels(pixels, 0, w, 0, 0, w, h)
        val out = FloatArray(3 * h * w)
        for (i in pixels.indices) {
            val p = pixels[i]
            out[i]           = ((p shr 16 and 0xFF) - MEAN) / STD  // R
            out[w * h + i]   = ((p shr 8  and 0xFF) - MEAN) / STD  // G
            out[2*w*h + i]   = ((p and 0xFF)        - MEAN) / STD  // B
        }
        return out
    }

    private fun l2Normalize(v: FloatArray): FloatArray {
        var norm = 0f
        for (x in v) norm += x * x
        norm = sqrt(norm)
        if (norm < 1e-10f) return v
        return FloatArray(v.size) { v[it] / norm }
    }

    fun close() = model.close()
}
