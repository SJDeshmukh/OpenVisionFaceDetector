package com.faceplugin.facerecognition.engine

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.util.Log
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer

/**
 * Generic helper that loads an ONNX model from assets and runs inference.
 */
class OnnxModelRunner(context: Context, assetName: String) {

    private val TAG = "OnnxModelRunner[$assetName]"
    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val session: OrtSession

    init {
        val modelBytes = loadAsset(context, assetName)
        val opts = OrtSession.SessionOptions()
        session = env.createSession(modelBytes, opts)
        Log.i(TAG, "Loaded ONNX model: $assetName  inputs=${session.inputNames}  outputs=${session.outputNames}")
    }

    fun getInputNames(): Set<String> = session.inputNames
    fun getOutputNames(): Set<String> = session.outputNames

    /**
     * Run inference on a float input tensor.
     * @param inputName  ONNX input node name
     * @param data       flat float array
     * @param shape      tensor shape e.g. [1, 3, 112, 112]
     * @return map of output node name → float array
     */
    fun runFloat(
        inputName: String,
        data: FloatArray,
        shape: LongArray
    ): Map<String, FloatArray> {
        val buffer = FloatBuffer.wrap(data)
        val tensor = OnnxTensor.createTensor(env, buffer, shape)
        val inputs = mapOf(inputName to tensor)
        val results = mutableMapOf<String, FloatArray>()
        session.run(inputs).use { output ->
            for (name in session.outputNames) {
                val t = output[name].get() as OnnxTensor
                val fb = t.floatBuffer
                val arr = FloatArray(fb.remaining())
                fb.get(arr)
                results[name] = arr
            }
        }
        tensor.close()
        return results
    }

    fun close() {
        session.close()
    }

    private fun loadAsset(context: Context, name: String): ByteArray {
        val stream: InputStream = context.assets.open(name)
        return stream.readBytes().also { stream.close() }
    }
}
