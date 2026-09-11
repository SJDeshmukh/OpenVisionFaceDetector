package com.example.faceid.ml

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import kotlin.math.sqrt

/**
 * MobileFaceNet backbone trained with ArcFace loss. Takes an ALIGNED 112x112
 * face crop (see ImageUtils.alignFace) and returns a 512-d L2-normalized
 * embedding suitable for cosine-similarity matching.
 */
class FaceRecognizer(context: Context, modelAsset: String = "models/mobilefacenet_arcface.onnx") {

    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private val inputSize = 112

    init {
        val bytes = context.assets.open(modelAsset).use { it.readBytes() }
        session = env.createSession(bytes, OrtSession.SessionOptions())
        try {
            ModelContract.requireInput(session, modelAsset, 3, inputSize.toLong(), inputSize.toLong())
            ModelContract.requireOutputWidth(session, modelAsset, 512)
        } catch (t: Throwable) {
            session.close()
            throw t
        }
    }

    fun getEmbedding(alignedFace: Bitmap): FloatArray {
        require(alignedFace.width == inputSize && alignedFace.height == inputSize) {
            "FaceRecognizer expects a pre-aligned ${inputSize}x$inputSize crop"
        }
        val input = ImageUtils.bitmapToNCHW(
            alignedFace,
            mean = floatArrayOf(127.5f, 127.5f, 127.5f),
            std = floatArrayOf(127.5f, 127.5f, 127.5f)
        )
        val shape = longArrayOf(1, 3, inputSize.toLong(), inputSize.toLong())
        OnnxTensor.createTensor(env, input, shape).use { tensor ->
            val inputName = session.inputNames.iterator().next()
            session.run(mapOf(inputName to tensor)).use { result ->
                val raw = (result[0].value as Array<*>)[0] as FloatArray
                return l2Normalize(raw)
            }
        }
    }

    private fun l2Normalize(v: FloatArray): FloatArray {
        var norm = 0f
        for (x in v) norm += x * x
        norm = sqrt(norm.toDouble()).toFloat().coerceAtLeast(1e-8f)
        return FloatArray(v.size) { v[it] / norm }
    }

    fun close() = session.close()

    companion object {
        fun cosineSimilarity(a: FloatArray, b: FloatArray): Float {
            require(a.size == b.size)
            var dot = 0f
            for (i in a.indices) dot += a[i] * b[i]
            // a and b are already L2-normalized, so dot product == cosine similarity.
            return dot
        }

        /** Aggregate several enrollment-frame embeddings (Section 8 of the design doc)
         *  into one template by averaging and re-normalizing, rather than storing one
         *  embedding per frame or relying on a single captured photo. */
        fun aggregate(embeddings: List<FloatArray>): FloatArray {
            require(embeddings.isNotEmpty())
            val dim = embeddings[0].size
            val mean = FloatArray(dim)
            for (e in embeddings) for (i in 0 until dim) mean[i] += e[i]
            for (i in 0 until dim) mean[i] = mean[i] / embeddings.size.toFloat()
            var norm = 0f
            for (x in mean) norm += x * x
            norm = sqrt(norm.toDouble()).toFloat().coerceAtLeast(1e-8f)
            return FloatArray(dim) { mean[it] / norm }
        }
    }
}
