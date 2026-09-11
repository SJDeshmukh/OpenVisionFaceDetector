package com.example.faceid.ml

import android.graphics.Bitmap
import android.graphics.Matrix
import java.nio.FloatBuffer

/**
 * Shared preprocessing helpers. Every model in the pipeline (SCRFD, MiniFASNet,
 * MobileFaceNet/ArcFace) wants a differently-sized, differently-normalized NCHW
 * float tensor, so we keep one small conversion utility instead of duplicating
 * bitmap math in three places.
 */
object ImageUtils {

    /** Resize (no letterboxing) to exactly [w]x[h]. Callers that need aspect-ratio
     *  preserving letterboxing (SCRFD) should use [letterbox] instead. */
    fun resize(src: Bitmap, w: Int, h: Int): Bitmap =
        Bitmap.createScaledBitmap(src, w, h, true)

    /**
     * Letterbox-resize into a [target]x[target] canvas, preserving aspect ratio and
     * padding with gray (114,114,114) — this is the standard SCRFD/YOLO-style input
     * prep. Returns the resulting bitmap plus the scale + padding needed to map
     * detection boxes back into the original image's coordinate space.
     */
    data class LetterboxResult(val bitmap: Bitmap, val scale: Float, val padX: Float, val padY: Float)

    fun letterbox(src: Bitmap, target: Int): LetterboxResult {
        val scale = minOf(target.toFloat() / src.width, target.toFloat() / src.height)
        val newW = (src.width * scale).toInt()
        val newH = (src.height * scale).toInt()
        val resized = Bitmap.createScaledBitmap(src, newW, newH, true)

        val canvas = Bitmap.createBitmap(target, target, Bitmap.Config.ARGB_8888)
        val c = android.graphics.Canvas(canvas)
        c.drawColor(android.graphics.Color.rgb(114, 114, 114))
        val padX = (target - newW) / 2f
        val padY = (target - newH) / 2f
        c.drawBitmap(resized, padX, padY, null)
        if (resized !== src && !resized.isRecycled) resized.recycle()

        return LetterboxResult(canvas, scale, padX, padY)
    }

    /**
     * Convert a bitmap into an NCHW float tensor.
     * @param mean per-channel mean subtracted before scaling (RGB order)
     * @param std per-channel std divided after mean subtraction (RGB order)
     * @param swapRB if true, feed BGR instead of RGB (some ONNX exports expect this)
     */
    fun bitmapToNCHW(
        bmp: Bitmap,
        mean: FloatArray = floatArrayOf(127.5f, 127.5f, 127.5f),
        std: FloatArray = floatArrayOf(128f, 128f, 128f),
        swapRB: Boolean = false
    ): FloatBuffer {
        val w = bmp.width
        val h = bmp.height
        val pixels = IntArray(w * h)
        bmp.getPixels(pixels, 0, w, 0, 0, w, h)

        val buffer = FloatBuffer.allocate(3 * w * h)
        // Channel-planar layout: [R plane][G plane][B plane] (or swapped).
        val rPlane = FloatArray(w * h)
        val gPlane = FloatArray(w * h)
        val bPlane = FloatArray(w * h)

        for (i in pixels.indices) {
            val p = pixels[i]
            val r = ((p shr 16) and 0xFF).toFloat()
            val g = ((p shr 8) and 0xFF).toFloat()
            val b = (p and 0xFF).toFloat()
            rPlane[i] = (r - mean[0]) / std[0]
            gPlane[i] = (g - mean[1]) / std[1]
            bPlane[i] = (b - mean[2]) / std[2]
        }

        if (swapRB) {
            buffer.put(bPlane); buffer.put(gPlane); buffer.put(rPlane)
        } else {
            buffer.put(rPlane); buffer.put(gPlane); buffer.put(bPlane)
        }
        buffer.rewind()
        return buffer
    }

    /** Crop + align a face to [outSize]x[outSize] using a similarity transform
     *  computed from 5-point landmarks (left eye, right eye, nose, left mouth,
     *  right mouth), matching the canonical ArcFace alignment template. */
    fun alignFace(src: Bitmap, landmarks: FloatArray, outSize: Int = 112): Bitmap {
        // Canonical ArcFace 112x112 reference landmark positions.
        val ref = floatArrayOf(
            38.2946f, 51.6963f,
            73.5318f, 51.5014f,
            56.0252f, 71.7366f,
            41.5493f, 92.3655f,
            70.7299f, 92.2041f
        )
        val scale = outSize / 112f
        val dst = FloatArray(10) { ref[it] * scale }

        // Solve a similarity transform (rotation+scale+translation) mapping
        // landmarks -> dst via least squares (Umeyama), then apply with a Matrix.
        val transform = estimateSimilarityTransform(landmarks, dst)
        val out = Bitmap.createBitmap(outSize, outSize, Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(out)
        canvas.drawBitmap(src, transform, null)
        return out
    }

    private fun estimateSimilarityTransform(src: FloatArray, dst: FloatArray): Matrix {
        val n = src.size / 2
        var srcMeanX = 0f; var srcMeanY = 0f
        var dstMeanX = 0f; var dstMeanY = 0f
        for (i in 0 until n) {
            srcMeanX += src[2 * i]; srcMeanY += src[2 * i + 1]
            dstMeanX += dst[2 * i]; dstMeanY += dst[2 * i + 1]
        }
        srcMeanX /= n; srcMeanY /= n; dstMeanX /= n; dstMeanY /= n

        var sxx = 0f; var sxy = 0f; var syx = 0f; var syy = 0f
        var srcVar = 0f
        for (i in 0 until n) {
            val sx = src[2 * i] - srcMeanX
            val sy = src[2 * i + 1] - srcMeanY
            val dx = dst[2 * i] - dstMeanX
            val dy = dst[2 * i + 1] - dstMeanY
            sxx += dx * sx; sxy += dx * sy
            syx += dy * sx; syy += dy * sy
            srcVar += sx * sx + sy * sy
        }
        srcVar /= n

        // Rotation+scale from the 2x2 cross-covariance (closed-form for similarity fit).
        val a = (sxx + syy) / n
        val b = (syx - sxy) / n
        val rotScale = Math.sqrt((a * a + b * b).toDouble()).toFloat()
        val angle = Math.atan2(b.toDouble(), a.toDouble()).toFloat()
        val cos = Math.cos(angle.toDouble()).toFloat()
        val sin = Math.sin(angle.toDouble()).toFloat()

        val m = Matrix()
        m.postTranslate(-srcMeanX, -srcMeanY)
        m.postConcat(Matrix().apply { setValues(floatArrayOf(cos, -sin, 0f, sin, cos, 0f, 0f, 0f, 1f)) })
        val scaleFactor = if (srcVar > 1e-6f) rotScale / srcVar else 1f
        m.postScale(scaleFactor, scaleFactor)
        m.postTranslate(dstMeanX, dstMeanY)
        return m
    }
}
