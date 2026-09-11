package com.example.faceid.ml

import ai.onnxruntime.OnnxJavaType
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo

/** Fail-fast checks for the exact tensor contracts used by this sample app. */
internal object ModelContract {
    fun requireInput(session: OrtSession, model: String, channels: Long, height: Long, width: Long) {
        require(session.inputInfo.size == 1) { "$model must have exactly one input" }
        val (name, node) = session.inputInfo.entries.single()
        val info = node.info as? TensorInfo
            ?: error("$model input '$name' is not a tensor")
        require(info.type == OnnxJavaType.FLOAT) { "$model input '$name' must be FLOAT, got ${info.type}" }
        require(shapeMatches(info.shape, longArrayOf(1, channels, height, width))) {
            "$model input '$name' must be [1,$channels,$height,$width], got ${info.shape.contentToString()}"
        }
    }

    fun requireOutputWidth(session: OrtSession, model: String, width: Long) {
        require(session.outputInfo.size == 1) { "$model must have exactly one output" }
        val (name, node) = session.outputInfo.entries.single()
        val info = node.info as? TensorInfo
            ?: error("$model output '$name' is not a tensor")
        require(info.type == OnnxJavaType.FLOAT && info.shape.lastOrNull() == width) {
            "$model output '$name' must be FLOAT with last dimension $width, got ${info.shape.contentToString()}"
        }
    }

    fun requireScrfdOutputs(session: OrtSession, model: String, inputSize: Int, strides: IntArray, anchors: Int) {
        val outputs = session.outputInfo.entries.toList()
        require(outputs.size == strides.size * 3) { "$model must have 9 SCRFD outputs, got ${outputs.size}" }
        val expectedWidths = listOf(1L, 1L, 1L, 4L, 4L, 4L, 10L, 10L, 10L)
        outputs.forEachIndexed { index, (name, node) ->
            val info = node.info as? TensorInfo ?: error("$model output '$name' is not a tensor")
            val expectedRows = (inputSize / strides[index % strides.size]).let { it * it * anchors }.toLong()
            val knownProduct = info.shape.filter { it > 0 }.fold(1L) { acc, value -> acc * value }
            require(info.type == OnnxJavaType.FLOAT &&
                info.shape.lastOrNull() == expectedWidths[index] &&
                (info.shape.any { it < 0 } || knownProduct == expectedRows * expectedWidths[index])) {
                "$model output #$index '$name' has incompatible shape ${info.shape.contentToString()}; " +
                    "expected $expectedRows x ${expectedWidths[index]} in score/bbox/keypoint group order"
            }
        }
    }

    private fun shapeMatches(actual: LongArray, expected: LongArray): Boolean =
        actual.size == expected.size && actual.indices.all { actual[it] < 0 || actual[it] == expected[it] }
}
