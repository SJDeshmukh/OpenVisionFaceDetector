package com.example.faceid.ml

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.RectF

/** One detected face: box in ORIGINAL image coordinates, 5 landmarks (x,y)*5, and score. */
data class FaceBox(
    val box: RectF,
    val landmarks: FloatArray, // [lx,ly, rx,ry, nx,ny, mlx,mly, mrx,mry]
    val score: Float
)

/**
 * SCRFD (2.5G / 500M variants both work with this decoder as long as strides
 * match). Outputs are the standard SCRFD ONNX export: for each of 3 strides
 * (8, 16, 32) three tensors — score, bbox-distance, kps-distance — per anchor.
 *
 * Expects a model exported with input name "input.1" and shape [1,3,H,W];
 * adjust INPUT_NAME below if your particular export differs (check with
 * Netron before wiring up a downloaded .onnx file).
 */
class FaceDetector(context: Context, modelAsset: String = "models/scrfd_500m.onnx") {

    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    // The bundled buffalo_sc SCRFD-500M checkpoint is exported for a 640x640 grid.
    private val inputSize = 640
    private val strides = intArrayOf(8, 16, 32)
    private val numAnchors = 2

    init {
        val bytes = context.assets.open(modelAsset).use { it.readBytes() }
        session = env.createSession(bytes, OrtSession.SessionOptions())
        try {
            ModelContract.requireInput(session, modelAsset, 3, inputSize.toLong(), inputSize.toLong())
            ModelContract.requireScrfdOutputs(session, modelAsset, inputSize, strides, numAnchors)
        } catch (t: Throwable) {
            session.close()
            throw t
        }
    }

    fun detect(bitmap: Bitmap, scoreThreshold: Float = 0.5f, nmsIou: Float = 0.4f): List<FaceBox> {
        val lb = ImageUtils.letterbox(bitmap, inputSize)
        try {
            val inputBuffer = ImageUtils.bitmapToNCHW(
                lb.bitmap,
                mean = floatArrayOf(127.5f, 127.5f, 127.5f),
                std = floatArrayOf(128f, 128f, 128f)
            )
            val shape = longArrayOf(1, 3, inputSize.toLong(), inputSize.toLong())
            OnnxTensor.createTensor(env, inputBuffer, shape).use { inputTensor ->
                val inputName = session.inputNames.iterator().next()
                session.run(mapOf(inputName to inputTensor)).use { results ->
                    val candidates = decode(results, scoreThreshold)
                    val kept = nms(candidates, nmsIou)
                    // Map boxes/landmarks from letterboxed space back to the original bitmap.
                    return kept.map { fb ->
                        val box = RectF(
                            (fb.box.left - lb.padX) / lb.scale,
                            (fb.box.top - lb.padY) / lb.scale,
                            (fb.box.right - lb.padX) / lb.scale,
                            (fb.box.bottom - lb.padY) / lb.scale
                        )
                        val lm = FloatArray(10)
                        for (i in 0 until 5) {
                            lm[2 * i] = (fb.landmarks[2 * i] - lb.padX) / lb.scale
                            lm[2 * i + 1] = (fb.landmarks[2 * i + 1] - lb.padY) / lb.scale
                        }
                        FaceBox(box, lm, fb.score)
                    }
                }
            }
        } finally {
            if (lb.bitmap !== bitmap && !lb.bitmap.isRecycled) lb.bitmap.recycle()
        }
    }

    /** Decode raw SCRFD outputs into boxes in the *letterboxed* input's pixel space. */
    private fun decode(results: OrtSession.Result, scoreThreshold: Float): List<FaceBox> {
        val out = mutableListOf<FaceBox>()
        // SCRFD ONNX exports 9 outputs: score_8, score_16, score_32, bbox_8, bbox_16,
        // bbox_32, kps_8, kps_16, kps_32 (order can vary by export tool — this assumes
        // the common insightface export ordering; verify with Netron for your file).
        for ((idx, stride) in strides.withIndex()) {
            val scores = (results[idx].value as Array<*>).let { flattenFloat(it) }
            val bboxes = (results[3 + idx].value as Array<*>).let { flattenFloat(it) }
            val kps = (results[6 + idx].value as Array<*>).let { flattenFloat(it) }

            val featW = inputSize / stride
            val featH = inputSize / stride
            var anchorIdx = 0
            for (y in 0 until featH) {
                for (x in 0 until featW) {
                    for (a in 0 until numAnchors) {
                        val score = scores[anchorIdx]
                        if (score >= scoreThreshold) {
                            val cx = x * stride.toFloat()
                            val cy = y * stride.toFloat()
                            val bOff = anchorIdx * 4
                            val left = cx - bboxes[bOff] * stride
                            val top = cy - bboxes[bOff + 1] * stride
                            val right = cx + bboxes[bOff + 2] * stride
                            val bottom = cy + bboxes[bOff + 3] * stride

                            val kOff = anchorIdx * 10
                            val lm = FloatArray(10)
                            for (i in 0 until 5) {
                                lm[2 * i] = cx + kps[kOff + 2 * i] * stride
                                lm[2 * i + 1] = cy + kps[kOff + 2 * i + 1] * stride
                            }
                            out.add(FaceBox(RectF(left, top, right, bottom), lm, score))
                        }
                        anchorIdx++
                    }
                }
            }
        }
        return out
    }

    private fun flattenFloat(arr: Array<*>): FloatArray {
        val list = mutableListOf<Float>()
        fun rec(a: Any?) {
            when (a) {
                is FloatArray -> a.forEach { list.add(it) }
                is Array<*> -> a.forEach { rec(it) }
            }
        }
        rec(arr)
        return list.toFloatArray()
    }

    private fun nms(boxes: List<FaceBox>, iouThreshold: Float): List<FaceBox> {
        val sorted = boxes.sortedByDescending { it.score }.toMutableList()
        val keep = mutableListOf<FaceBox>()
        while (sorted.isNotEmpty()) {
            val best = sorted.removeAt(0)
            keep.add(best)
            sorted.removeAll { iou(it.box, best.box) > iouThreshold }
        }
        return keep
    }

    private fun iou(a: RectF, b: RectF): Float {
        val interLeft = maxOf(a.left, b.left)
        val interTop = maxOf(a.top, b.top)
        val interRight = minOf(a.right, b.right)
        val interBottom = minOf(a.bottom, b.bottom)
        val interArea = maxOf(0f, interRight - interLeft) * maxOf(0f, interBottom - interTop)
        val union = a.width() * a.height() + b.width() * b.height() - interArea
        return if (union <= 0f) 0f else interArea / union
    }

    fun close() = session.close()
}
