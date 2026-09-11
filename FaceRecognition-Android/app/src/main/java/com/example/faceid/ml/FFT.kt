package com.example.faceid.ml

/**
 * Minimal iterative radix-2 Cooley-Tukey FFT, operating in-place on parallel
 * real/imaginary DoubleArrays of length N (N must be a power of two).
 *
 * Written from scratch rather than pulling in a third-party FFT library:
 * this sandbox has no compiler to verify a library's exact buffer-packing
 * convention against, and a subtly-wrong layout would silently corrupt the
 * spectrum. A basic radix-2 FFT is simple enough to get right by inspection.
 */
object FFT {

    /** In-place 1D FFT. Set [inverse] = true for the inverse transform (caller
     *  is responsible for dividing by N afterwards if a true inverse is needed;
     *  MoireDetector only needs magnitudes, so it never calls the inverse). */
    fun fft(re: DoubleArray, im: DoubleArray, inverse: Boolean = false) {
        val n = re.size
        require(n and (n - 1) == 0) { "FFT size must be a power of two, got $n" }
        if (n <= 1) return

        // Bit-reversal permutation.
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j xor bit
            if (i < j) {
                var tmp = re[i]; re[i] = re[j]; re[j] = tmp
                tmp = im[i]; im[i] = im[j]; im[j] = tmp
            }
        }

        val sign = if (inverse) 1.0 else -1.0
        var len = 2
        while (len <= n) {
            val ang = sign * 2.0 * Math.PI / len
            val wRe = Math.cos(ang)
            val wIm = Math.sin(ang)
            var i = 0
            while (i < n) {
                var curWRe = 1.0
                var curWIm = 0.0
                for (k in 0 until len / 2) {
                    val uRe = re[i + k]
                    val uIm = im[i + k]
                    val vRe = re[i + k + len / 2] * curWRe - im[i + k + len / 2] * curWIm
                    val vIm = re[i + k + len / 2] * curWIm + im[i + k + len / 2] * curWRe

                    re[i + k] = uRe + vRe
                    im[i + k] = uIm + vIm
                    re[i + k + len / 2] = uRe - vRe
                    im[i + k + len / 2] = uIm - vIm

                    val nextWRe = curWRe * wRe - curWIm * wIm
                    val nextWIm = curWRe * wIm + curWIm * wRe
                    curWRe = nextWRe
                    curWIm = nextWIm
                }
                i += len
            }
            len = len shl 1
        }
    }

    /** Separable 2D FFT on an NxN real matrix (row-major DoubleArray of size N*N).
     *  Returns magnitude spectrum, also NxN row-major, NOT yet fftshifted. */
    fun magnitude2D(realInput: DoubleArray, n: Int): DoubleArray {
        require(realInput.size == n * n)
        val re = realInput.copyOf()
        val im = DoubleArray(n * n)

        // Row-wise FFT.
        val rowRe = DoubleArray(n)
        val rowIm = DoubleArray(n)
        for (r in 0 until n) {
            for (c in 0 until n) {
                rowRe[c] = re[r * n + c]
                rowIm[c] = im[r * n + c]
            }
            fft(rowRe, rowIm)
            for (c in 0 until n) {
                re[r * n + c] = rowRe[c]
                im[r * n + c] = rowIm[c]
            }
        }
        // Column-wise FFT.
        val colRe = DoubleArray(n)
        val colIm = DoubleArray(n)
        for (c in 0 until n) {
            for (r in 0 until n) {
                colRe[r] = re[r * n + c]
                colIm[r] = im[r * n + c]
            }
            fft(colRe, colIm)
            for (r in 0 until n) {
                re[r * n + c] = colRe[r]
                im[r * n + c] = colIm[r]
            }
        }

        val mag = DoubleArray(n * n)
        for (i in 0 until n * n) mag[i] = Math.hypot(re[i], im[i])
        return mag
    }

    /** Swap quadrants so the zero-frequency (DC) component sits at the center,
     *  matching how frequency spectra are conventionally visualized/analyzed. */
    fun fftShift(mag: DoubleArray, n: Int): DoubleArray {
        val half = n / 2
        val out = DoubleArray(n * n)
        for (r in 0 until n) {
            for (c in 0 until n) {
                val sr = (r + half) % n
                val sc = (c + half) % n
                out[sr * n + sc] = mag[r * n + c]
            }
        }
        return out
    }
}
