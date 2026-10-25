package com.faceplugin.facerecognition.engine

import android.graphics.Bitmap
import android.graphics.Matrix
import kotlin.math.*

/**
 * Aligns a face crop to a canonical 112×112 frame using the 5-point
 * landmarks produced by SCRFD.
 *
 * Reference landmarks for ArcFace / MobileFaceNet 112×112 canonical space:
 *   left_eye  (38.29, 51.69)
 *   right_eye (73.53, 51.50)
 *   nose      (56.02, 71.74)
 *   left_mouth (41.55, 92.37)
 *   right_mouth(70.73, 92.20)
 */
object FaceAligner {

    const val OUT_SIZE = 112

    private val DST_POINTS = floatArrayOf(
        38.29f, 51.69f,  // left eye
        73.53f, 51.50f,  // right eye
        56.02f, 71.74f,  // nose
        41.55f, 92.37f,  // left mouth
        70.73f, 92.20f   // right mouth
    )

    /**
     * Crop and warp the face to 112×112 using the 5-point landmarks.
     * Falls back to a simple bounding-box crop if landmarks are all zero.
     */
    fun align(bitmap: Bitmap, faceBox: FaceBox): Bitmap {
        val lm = faceBox.landmarks
        val hasLandmarks = lm.any { it != 0f }

        return if (hasLandmarks) {
            warpAffine(bitmap, lm)
        } else {
            simpleCrop(bitmap, faceBox)
        }
    }

    private fun warpAffine(bitmap: Bitmap, landmarks: FloatArray): Bitmap {
        // Compute similarity transform (scale + rotation + translation)
        // from 5 src points to 5 dst points using least-squares approach
        val srcPts = landmarks  // [x0,y0, x1,y1, ...]
        val dstPts = DST_POINTS

        val matrix = estimateSimilarityTransform(srcPts, dstPts)

        val m = Matrix()
        m.setValues(floatArrayOf(
            matrix[0], matrix[1], matrix[2],
            matrix[3], matrix[4], matrix[5],
            0f,        0f,        1f
        ))

        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, m, true)
            .let { warped ->
                // Crop to OUT_SIZE × OUT_SIZE from top-left (the warp puts face at 0,0)
                val safe = Bitmap.createBitmap(
                    warped,
                    0.coerceAtLeast(0),
                    0.coerceAtLeast(0),
                    OUT_SIZE.coerceAtMost(warped.width),
                    OUT_SIZE.coerceAtMost(warped.height)
                )
                if (safe.width != OUT_SIZE || safe.height != OUT_SIZE)
                    Bitmap.createScaledBitmap(safe, OUT_SIZE, OUT_SIZE, true)
                else safe
            }
    }

    private fun simpleCrop(bitmap: Bitmap, faceBox: FaceBox): Bitmap {
        val margin = 0.2f
        val w = (faceBox.x2 - faceBox.x1).toFloat()
        val h = (faceBox.y2 - faceBox.y1).toFloat()
        val x1 = (faceBox.x1 - w * margin).toInt().coerceAtLeast(0)
        val y1 = (faceBox.y1 - h * margin).toInt().coerceAtLeast(0)
        val x2 = (faceBox.x2 + w * margin).toInt().coerceAtMost(bitmap.width)
        val y2 = (faceBox.y2 + h * margin).toInt().coerceAtMost(bitmap.height)
        val cropped = Bitmap.createBitmap(bitmap, x1, y1, x2 - x1, y2 - y1)
        return Bitmap.createScaledBitmap(cropped, OUT_SIZE, OUT_SIZE, true)
    }

    /**
     * Estimate 2D similarity transform (s*R + t) using the Umeyama algorithm
     * simplified for 5-point correspondence.
     * Returns [a, b, tx, -b, a, ty] (2×3 affine matrix row-major).
     */
    private fun estimateSimilarityTransform(src: FloatArray, dst: FloatArray): FloatArray {
        val n = src.size / 2
        var srcMx = 0f; var srcMy = 0f
        var dstMx = 0f; var dstMy = 0f
        for (i in 0 until n) {
            srcMx += src[i * 2]; srcMy += src[i * 2 + 1]
            dstMx += dst[i * 2]; dstMy += dst[i * 2 + 1]
        }
        srcMx /= n; srcMy /= n
        dstMx /= n; dstMy /= n

        var a = 0f; var b = 0f; var srcVar = 0f
        for (i in 0 until n) {
            val sx = src[i * 2] - srcMx; val sy = src[i * 2 + 1] - srcMy
            val dx = dst[i * 2] - dstMx; val dy = dst[i * 2 + 1] - dstMy
            a += sx * dx + sy * dy
            b += sx * dy - sy * dx
            srcVar += sx * sx + sy * sy
        }
        if (srcVar < 1e-6f) {
            // degenerate — just translate
            return floatArrayOf(1f, 0f, dstMx - srcMx, 0f, 1f, dstMy - srcMy)
        }
        a /= srcVar; b /= srcVar
        val tx = dstMx - a * srcMx + b * srcMy
        val ty = dstMy - b * srcMx - a * srcMy
        return floatArrayOf(a, -b, tx, b, a, ty)
    }
}
