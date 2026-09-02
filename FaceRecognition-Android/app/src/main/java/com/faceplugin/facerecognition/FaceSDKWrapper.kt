package com.faceplugin.facerecognition

import android.content.Context
import android.content.res.AssetManager
import android.graphics.Bitmap
import android.util.Log
import com.ocp.facesdk.FaceBox
import com.ocp.facesdk.FaceDetectionParam
import com.ocp.facesdk.FaceSDK

/**
 * A safe wrapper around the FaceSDK to prevent native crashes and null pointer exceptions.
 * It provides defensive checks and fallback values for all SDK operations.
 */
object FaceSDKWrapper {
    private const val TAG = "FaceSDKWrapper"

    @Volatile
    var isInitialized: Boolean = false
        private set

    @Volatile
    var lastInitializationResult: Int = FaceSDK.SDK_NO_ACTIVATED
        private set

    private val LICENSE = "Fqk7LKLbzfSCBor1Oidf0+aPu7OsAJgjxU5m6EQMP3WQ4JZ0Rt44C8T7auT27jjx9iwYmG/8l3TB\n" +
            "9MBZuaQKCKMiBvwu+JGfbyrQPrs0vyunAZplg0qUm3MUjz/ko1oJNDzh90jOvsdy8C+SGFWgLULQ\n" +
            "rA6K0dipo5B0v8uPXHkGliNVRuxdKg86iaGHpVzE9V+oqecdXqiuJyRloIqC+vWEYObQkJAocnwR\n" +
            "M51gg1HHqFYZ0RS9PI5DVzRNHHT4X/ws7e1tc2R0LgU22gd/4SHDYfoV8gHtyi/QdMthKgyzcJrN\n" +
            "p0lS+CrpoQuOzWl1toECPoSfcrbmmNP6v67ISA=="

    /**
     * Ensures the SDK is initialized. Safe to call multiple times — only initializes once.
     * @return SDK_SUCCESS if already initialized or newly initialized successfully, error code otherwise.
     */
    @Synchronized
    fun ensureInitialized(context: Context): Int {
        if (isInitialized) return FaceSDK.SDK_SUCCESS
        val appContext = context.applicationContext
        if (!hasRequiredModels(appContext.assets)) {
            Log.e(TAG, "FaceSDK model assets are missing from the APK")
            lastInitializationResult = FaceSDK.SDK_INIT_ERROR
            return lastInitializationResult
        }

        var ret = setActivation(LICENSE)
        if (ret == FaceSDK.SDK_SUCCESS) {
            ret = init(appContext.assets)
        }
        lastInitializationResult = ret
        if (ret == FaceSDK.SDK_SUCCESS) {
            isInitialized = true
            Log.i(TAG, "FaceSDK initialized successfully")
        } else {
            Log.e(TAG, "FaceSDK initialization failed: $ret")
        }
        return ret
    }

    private fun hasRequiredModels(assets: AssetManager): Boolean {
        return try {
            val names = assets.list("data")?.toSet().orEmpty()
            names.containsAll(setOf("detection.bin", "detection.param", "landmark.bin", "mfn.bin"))
        } catch (t: Throwable) {
            Log.e(TAG, "Unable to inspect FaceSDK model assets", t)
            false
        }
    }

    fun setActivation(license: String): Int {
        return try {
            FaceSDK.setActivation(license)
        } catch (e: Throwable) {
            Log.e(TAG, "Unable to activate FaceSDK", e)
            FaceSDK.SDK_INIT_ERROR
        }
    }

    fun init(assets: AssetManager): Int {
        return try {
            FaceSDK.init(assets)
        } catch (e: Throwable) {
            Log.e(TAG, "Unable to load FaceSDK models/native libraries", e)
            FaceSDK.SDK_INIT_ERROR
        }
    }

    fun faceDetection(bitmap: Bitmap?, param: FaceDetectionParam?): List<FaceBox> {
        if (!isInitialized) {
            Log.w(TAG, "faceDetection called before SDK is initialized — skipping")
            return emptyList()
        }
        if (bitmap == null || bitmap.isRecycled) {
            Log.w(TAG, "faceDetection: bitmap is null or recycled")
            return emptyList()
        }
        
        return try {
            val result = FaceSDK.faceDetection(bitmap, param)
            result ?: emptyList()
        } catch (e: Throwable) {
            Log.e(TAG, "Exception during faceDetection", e)
            emptyList()
        }
    }

    fun templateExtraction(bitmap: Bitmap?, faceBox: FaceBox?): ByteArray? {
        if (!isInitialized) {
            Log.w(TAG, "templateExtraction called before SDK is initialized — skipping")
            return null
        }
        if (bitmap == null || bitmap.isRecycled || faceBox == null) {
            Log.w(TAG, "templateExtraction: invalid inputs")
            return null
        }
        
        return try {
            FaceSDK.templateExtraction(bitmap, faceBox)
        } catch (e: Throwable) {
            Log.e(TAG, "Exception during templateExtraction", e)
            null
        }
    }

    fun similarityCalculation(templates1: ByteArray?, templates2: ByteArray?): Float {
        if (!isInitialized) {
            Log.w(TAG, "similarityCalculation called before SDK is initialized — skipping")
            return 0.0f
        }
        if (templates1 == null || templates2 == null) {
            return 0.0f
        }
        
        // Basic length check for templates (SDK expects ~2056 bytes)
        if (templates1.isEmpty() || templates2.isEmpty()) {
            return 0.0f
        }

        return try {
            FaceSDK.similarityCalculation(templates1, templates2)
        } catch (e: Throwable) {
            Log.e(TAG, "Exception during similarityCalculation", e)
            0.0f
        }
    }

    fun yuv2Bitmap(yuv: ByteArray?, width: Int, height: Int, mode: Int): Bitmap? {
        if (yuv == null) return null
        return try {
            FaceSDK.yuv2Bitmap(yuv, width, height, mode)
        } catch (e: Throwable) {
            Log.e(TAG, "Exception during yuv2Bitmap", e)
            null
        }
    }
}
