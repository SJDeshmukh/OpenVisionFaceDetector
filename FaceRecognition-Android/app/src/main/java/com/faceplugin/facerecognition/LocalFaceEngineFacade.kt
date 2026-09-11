package com.faceplugin.facerecognition

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import com.faceplugin.faceengine.FaceBox
import com.faceplugin.faceengine.FaceDetectionParam
import com.faceplugin.faceengine.LocalFaceEngine

/** Defensive application facade for the in-repository FaceIDApp ONNX engine. */
object LocalFaceEngineFacade {
    const val SUCCESS = LocalFaceEngine.SUCCESS
    const val INIT_FAILED = LocalFaceEngine.INIT_FAILED
    private const val TAG = "LocalFaceEngine"

    @Volatile
    var isInitialized: Boolean = false
        private set

    @Volatile
    var lastInitializationResult: Int = INIT_FAILED
        private set

    @Synchronized
    fun ensureInitialized(context: Context): Int {
        if (isInitialized && LocalFaceEngine.isInitialized()) return SUCCESS
        val result = try {
            LocalFaceEngine.initialize(context.applicationContext)
        } catch (error: Throwable) {
            Log.e(TAG, "Unable to initialize local face models", error)
            INIT_FAILED
        }
        lastInitializationResult = result
        isInitialized = result == SUCCESS
        if (isInitialized) Log.i(TAG, "Local FaceIDApp models initialized")
        else Log.e(TAG, "Local face model initialization failed: $result; ${LocalFaceEngine.lastInitializationError}")
        return result
    }

    @Synchronized
    fun faceDetection(bitmap: Bitmap?, param: FaceDetectionParam?): List<FaceBox> {
        if (!isInitialized || bitmap == null || bitmap.isRecycled) return emptyList()
        return try {
            LocalFaceEngine.detect(bitmap, param).filter { box ->
                box.x1 >= 0 && box.y1 >= 0 && box.x2 > box.x1 && box.y2 > box.y1 &&
                    box.x2 <= bitmap.width && box.y2 <= bitmap.height
            }
        } catch (error: Throwable) {
            Log.e(TAG, "Local face detection failed", error)
            emptyList()
        }
    }

    @Synchronized
    fun templateExtraction(bitmap: Bitmap?, faceBox: FaceBox?): ByteArray? {
        if (!isInitialized || bitmap == null || bitmap.isRecycled || faceBox == null) return null
        if (faceBox.x1 < 0 || faceBox.y1 < 0 || faceBox.x2 <= faceBox.x1 ||
            faceBox.y2 <= faceBox.y1 || faceBox.x2 > bitmap.width || faceBox.y2 > bitmap.height) return null
        return try {
            LocalFaceEngine.extractTemplate(bitmap, faceBox)
        } catch (error: Throwable) {
            Log.e(TAG, "Local template extraction failed", error)
            null
        }
    }

    fun aggregateTemplates(templates: List<ByteArray>): ByteArray? {
        return try {
            LocalFaceEngine.aggregateTemplates(templates)
        } catch (error: Throwable) {
            Log.e(TAG, "Template aggregation failed", error)
            null
        }
    }

    @Synchronized
    fun similarityCalculation(first: ByteArray?, second: ByteArray?): Float {
        if (!isInitialized || first == null || first.isEmpty()
            || second == null || second.isEmpty()) return 0f
        return try {
            LocalFaceEngine.similarity(first, second).takeIf { it.isFinite() }?.coerceIn(0f, 1f) ?: 0f
        } catch (error: Throwable) {
            Log.e(TAG, "Local similarity calculation failed", error)
            0f
        }
    }

    @Synchronized
    fun yuv2Bitmap(yuv: ByteArray?, width: Int, height: Int, mode: Int): Bitmap? {
        if (yuv == null || width <= 0 || height <= 0) return null
        val minimumBytes = width.toLong() * height * 3L / 2L
        if (minimumBytes > Int.MAX_VALUE || yuv.size < minimumBytes) return null
        return try {
            LocalFaceEngine.nv21ToBitmap(yuv, width, height, mode)
        } catch (error: Throwable) {
            Log.e(TAG, "NV21 conversion failed", error)
            null
        }
    }
}
