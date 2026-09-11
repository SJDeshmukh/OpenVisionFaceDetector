package com.example.faceid.ml

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap

enum class LivenessLabel { LIVE, PRINT_ATTACK, REPLAY_ATTACK }

data class LivenessResult(val label: LivenessLabel, val liveScore: Float)

/**
 * Ensembles MiniFASNet V1SE (crop scale ~2.7x the face box) and MiniFASNet V2
 * (crop scale ~4x) as recommended in the Silent-Face-Anti-Spoofing project —
 * the two scales catch different presentation-attack artefacts, and averaging
 * their softmax scores is a simple, effective fusion rule for a first build.
 *
 * Both models take an 80x80 RGB crop and output 3 class logits:
 * [0]=fake/print, [1]=live... (label order should be verified against the
 * exact checkpoint's training config. This reference profile requires
 * [print, live, replay]; pass a different explicit liveIndex only after verifying
 * the checkpoint documentation and updating the README contract.
 */
class AntiSpoofDetector(
    context: Context,
    /** This sample targets checkpoints whose class order is [print, live, replay]. */
    private val liveIndex: Int = 1
) {

    private val env = OrtEnvironment.getEnvironment()
    private val v1se: OrtSession
    private val v2: OrtSession
    private val cropSize = 80

    init {
        v1se = env.createSession(
            context.assets.open("models/minifasnet_v1se.onnx").use { it.readBytes() },
            OrtSession.SessionOptions()
        )
        try {
            v2 = env.createSession(
                context.assets.open("models/minifasnet_v2.onnx").use { it.readBytes() },
                OrtSession.SessionOptions()
            )
        } catch (t: Throwable) {
            v1se.close()
            throw t
        }
        try {
            require(liveIndex in 0..2) { "MiniFASNet liveIndex must be 0, 1, or 2" }
            ModelContract.requireInput(v1se, "minifasnet_v1se.onnx", 3, cropSize.toLong(), cropSize.toLong())
            ModelContract.requireInput(v2, "minifasnet_v2.onnx", 3, cropSize.toLong(), cropSize.toLong())
            ModelContract.requireOutputWidth(v1se, "minifasnet_v1se.onnx", 3)
            ModelContract.requireOutputWidth(v2, "minifasnet_v2.onnx", 3)
        } catch (t: Throwable) {
            v1se.close()
            v2.close()
            throw t
        }
    }

    /** The bundled checkpoints require different crop scales and raw BGR 0..255 pixels. */
    fun check(v1seCrop4x: Bitmap, v2Crop2_7x: Bitmap): LivenessResult {
        val shape = longArrayOf(1, 3, cropSize.toLong(), cropSize.toLong())
        val score1 = runSoftmax(v1se, modelInput(v1seCrop4x), shape)
        val score2 = runSoftmax(v2, modelInput(v2Crop2_7x), shape)
        val fused = FloatArray(score1.size) { (score1[it] + score2[it]) / 2f }

        val liveScore = fused[liveIndex]
        val label = if (liveScore == fused.max()) LivenessLabel.LIVE
            else if (fused.indices.maxByOrNull { fused[it] } == 0) LivenessLabel.PRINT_ATTACK
            else LivenessLabel.REPLAY_ATTACK

        return LivenessResult(label, liveScore)
    }

    private fun modelInput(crop: Bitmap): java.nio.FloatBuffer {
        val resized = ImageUtils.resize(crop, cropSize, cropSize)
        return try {
            ImageUtils.bitmapToNCHW(
                resized,
                mean = floatArrayOf(0f, 0f, 0f),
                std = floatArrayOf(1f, 1f, 1f),
                swapRB = true
            )
        } finally {
            if (resized !== crop && !resized.isRecycled) resized.recycle()
        }
    }

    private fun runSoftmax(session: OrtSession, input: java.nio.FloatBuffer, shape: LongArray): FloatArray {
        input.rewind()
        OnnxTensor.createTensor(env, input, shape).use { tensor ->
            val inputName = session.inputNames.iterator().next()
            session.run(mapOf(inputName to tensor)).use { result ->
                val logits = (result[0].value as Array<*>)[0] as FloatArray
                return softmax(logits)
            }
        }
    }

    private fun softmax(logits: FloatArray): FloatArray {
        val max = logits.max()
        val exps = logits.map { Math.exp((it - max).toDouble()).toFloat() }
        val sum = exps.sum()
        return exps.map { it / sum }.toFloatArray()
    }

    /** Simple threshold helper — tune experimentally per Section 14 of the design doc;
     *  0.9 is a conservative starting point that favors rejecting borderline live faces
     *  over letting spoofs through. */
    fun isLive(result: LivenessResult, threshold: Float = 0.9f) =
        result.label == LivenessLabel.LIVE && result.liveScore >= threshold

    fun close() {
        v1se.close()
        v2.close()
    }
}
