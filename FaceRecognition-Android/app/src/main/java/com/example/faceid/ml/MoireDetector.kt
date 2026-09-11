package com.example.faceid.ml

import android.graphics.Bitmap

data class MoireResult(val score: Float, val flagged: Boolean)

/**
 * Detects screen-replay (recapture) attacks by looking for Moiré interference:
 * when a camera photographs/films a digital display, the display's pixel grid
 * aliases against the camera sensor's pixel grid, producing periodic patterns
 * that don't occur when photographing a real face directly. This shows up in
 * the frequency domain as anomalous peaks — energy concentrated at specific
 * frequencies well above what a natural image's spectrum predicts there —
 * rather than the smooth, roughly-monotonic falloff natural images have.
 *
 * This is a classical signal-processing heuristic, not a trained classifier —
 * it's meant to run alongside AntiSpoofDetector's MiniFASNet ensemble as an
 * independent, complementary signal (see LivenessGate), not replace it.
 *
 * Known limitations (be realistic about these, don't oversell the gate):
 * - Weak against high-end displays/cameras where the pixel pitches barely
 *   alias (large phone screen recorded by another high-res phone, in focus).
 * - Can false-positive on real faces against finely patterned backgrounds
 *   (window blinds, mesh fabric, checkered clothing) — that's *why* this is
 *   fused with the CNN ensemble rather than used as a sole gate.
 * - Needs threshold tuning against your own real attack samples, same as
 *   every other threshold in this pipeline.
 */
class MoireDetector(
    private val size: Int = 128, // power of two, required by FFT.magnitude2D
    private val threshold: Float = 1.8f
) {

    fun score(bitmap: Bitmap): MoireResult {
        val gray = toGrayscaleMatrix(bitmap, size)
        applyHannWindow(gray, size)

        val mag = FFT.magnitude2D(gray, size)
        val shifted = FFT.fftShift(mag, size)

        val radialProfile = radialAverage(shifted, size)
        val anomaly = peakAnomaly(radialProfile)

        return MoireResult(score = anomaly, flagged = anomaly >= threshold)
    }

    /** Resize to [n]x[n] and convert to a row-major luminance matrix (0-255 range as Double). */
    private fun toGrayscaleMatrix(bitmap: Bitmap, n: Int): DoubleArray {
        val resized = ImageUtils.resize(bitmap, n, n)
        return try {
            val pixels = IntArray(n * n)
            resized.getPixels(pixels, 0, n, 0, 0, n, n)
            val out = DoubleArray(n * n)
            for (i in pixels.indices) {
                val p = pixels[i]
                val r = (p shr 16) and 0xFF
                val g = (p shr 8) and 0xFF
                val b = p and 0xFF
                out[i] = 0.299 * r + 0.587 * g + 0.114 * b
            }
            out
        } finally {
            if (resized !== bitmap && !resized.isRecycled) resized.recycle()
        }
    }

    /** Tapers the crop's edges to near-zero before the FFT. Without this, the
     *  sharp discontinuity at the image border leaks energy into every
     *  frequency (spectral leakage) and is easily mistaken for a genuine
     *  periodic pattern — this is the single most important step for keeping
     *  the false-positive rate sane. */
    private fun applyHannWindow(matrix: DoubleArray, n: Int) {
        val w = DoubleArray(n) { 0.5 * (1 - Math.cos(2 * Math.PI * it / (n - 1))) }
        for (r in 0 until n) {
            for (c in 0 until n) {
                matrix[r * n + c] *= w[r] * w[c]
            }
        }
    }

    /** Average magnitude at each integer radius from the (now-centered) DC bin. */
    private fun radialAverage(shiftedMag: DoubleArray, n: Int): DoubleArray {
        val center = n / 2
        val maxRadius = center
        val sums = DoubleArray(maxRadius + 1)
        val counts = IntArray(maxRadius + 1)
        for (r in 0 until n) {
            for (c in 0 until n) {
                val dr = r - center
                val dc = c - center
                val radius = Math.round(Math.sqrt((dr * dr + dc * dc).toDouble())).toInt()
                if (radius <= maxRadius) {
                    // log-compress: natural-image spectra span orders of magnitude,
                    // and moire peaks are relative outliers, not necessarily huge in
                    // absolute terms once low frequencies dominate.
                    sums[radius] += Math.log(1.0 + shiftedMag[r * n + c])
                    counts[radius] += 1
                }
            }
        }
        return DoubleArray(maxRadius + 1) { if (counts[it] > 0) sums[it] / counts[it] else 0.0 }
    }

    /**
     * Natural-image radial spectra fall off smoothly with radius. A moire
     * pattern shows up as a bump that sticks up above a locally-smoothed
     * baseline. We build that baseline with a wide moving average (so it
     * follows the overall falloff but not a single sharp peak), then report
     * the largest relative excess in the band that excludes near-DC content
     * (low frequencies = normal image structure, always present) and
     * near-Nyquist noise (highest frequencies = sensor noise floor).
     */
    private fun peakAnomaly(profile: DoubleArray): Float {
        val n = profile.size
        val loCut = (n * 0.08).toInt()
        val hiCut = (n * 0.85).toInt()
        if (hiCut <= loCut) return 0f

        val window = 7
        val baseline = DoubleArray(n)
        for (i in profile.indices) {
            var sum = 0.0; var count = 0
            for (k in -window..window) {
                val idx = i + k
                if (idx in profile.indices) { sum += profile[idx]; count++ }
            }
            baseline[i] = sum / count
        }

        var maxExcess = 0.0
        for (i in loCut..hiCut) {
            if (baseline[i] > 1e-6) {
                val excess = (profile[i] - baseline[i]) / baseline[i]
                if (excess > maxExcess) maxExcess = excess
            }
        }
        return maxExcess.toFloat()
    }
}
