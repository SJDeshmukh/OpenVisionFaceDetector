package com.faceplugin.facerecognition

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

    fun setActivation(license: String): Int {
        return try {
            FaceSDK.setActivation(license)
        } catch (e: Exception) {
            Log.e(TAG, "Exception during setActivation", e)
            FaceSDK.SDK_INIT_ERROR
        }
    }

    fun init(assets: AssetManager): Int {
        return try {
            FaceSDK.init(assets)
        } catch (e: Exception) {
            Log.e(TAG, "Exception during init", e)
            FaceSDK.SDK_INIT_ERROR
        }
    }

    fun faceDetection(bitmap: Bitmap?, param: FaceDetectionParam?): List<FaceBox> {
        if (bitmap == null || bitmap.isRecycled) {
            Log.w(TAG, "faceDetection: bitmap is null or recycled")
            return emptyList()
        }
        
        return try {
            val result = FaceSDK.faceDetection(bitmap, param)
            result ?: emptyList()
        } catch (e: Exception) {
            Log.e(TAG, "Exception during faceDetection", e)
            emptyList()
        }
    }

    fun templateExtraction(bitmap: Bitmap?, faceBox: FaceBox?): ByteArray? {
        if (bitmap == null || bitmap.isRecycled || faceBox == null) {
            Log.w(TAG, "templateExtraction: invalid inputs")
            return null
        }
        
        return try {
            FaceSDK.templateExtraction(bitmap, faceBox)
        } catch (e: Exception) {
            Log.e(TAG, "Exception during templateExtraction", e)
            null
        }
    }

    fun similarityCalculation(templates1: ByteArray?, templates2: ByteArray?): Float {
        if (templates1 == null || templates2 == null) {
            return 0.0f
        }
        
        // Basic length check for templates (SDK expects ~2056 bytes)
        if (templates1.isEmpty() || templates2.isEmpty()) {
            return 0.0f
        }

        return try {
            FaceSDK.similarityCalculation(templates1, templates2)
        } catch (e: Exception) {
            Log.e(TAG, "Exception during similarityCalculation", e)
            0.0f
        }
    }

    fun yuv2Bitmap(yuv: ByteArray?, width: Int, height: Int, mode: Int): Bitmap? {
        if (yuv == null) return null
        return try {
            FaceSDK.yuv2Bitmap(yuv, width, height, mode)
        } catch (e: Exception) {
            Log.e(TAG, "Exception during yuv2Bitmap", e)
            null
        }
    }
}
