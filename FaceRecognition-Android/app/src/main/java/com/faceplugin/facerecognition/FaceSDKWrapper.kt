package com.faceplugin.facerecognition

import android.content.Context
import android.graphics.Bitmap
import com.faceplugin.facerecognition.engine.FaceBox
import com.faceplugin.facerecognition.engine.FaceEngine

/**
 * Backward-compatibility shim.
 * All code that previously called FaceSDKWrapper now routes to FaceEngine.
 *
 * Old API  →  New API
 * ─────────────────────────────────────────────────────────────────
 * ensureInitialized(ctx)   →  FaceEngine.init(ctx) (returns 0 = SUCCESS)
 * faceDetection(bmp, param)→  FaceEngine.detectFaces(bmp)
 * templateExtraction(bmp,box)→ FaceEngine.extractEmbedding(bmp, box)
 * similarityCalculation(a,b)→  FaceEngine.cosineSimilarity(a, b)
 * yuv2Bitmap(yuv,w,h,mode) →  FaceEngine.yuv2Bitmap(yuv, w, h, rotation)
 */
object FaceSDKWrapper {

    val isInitialized: Boolean get() = FaceEngine.isInitialized

    /** Returns 0 on success (matching old SDK_SUCCESS = 0). */
    fun ensureInitialized(context: Context): Int {
        FaceEngine.init(context)
        return if (FaceEngine.isInitialized) 0 else -1
    }

    fun faceDetection(bitmap: Bitmap?, param: Any? = null): List<FaceBox> {
        if (bitmap == null || bitmap.isRecycled) return emptyList()
        return FaceEngine.detectFaces(bitmap)
    }

    fun templateExtraction(bitmap: Bitmap?, faceBox: FaceBox?): ByteArray? {
        if (bitmap == null || bitmap.isRecycled || faceBox == null) return null
        val emb = FaceEngine.extractEmbedding(bitmap, faceBox) ?: return null
        return FaceEngine.embeddingToBytes(emb)
    }

    /** Returns similarity 0..1. */
    fun similarityCalculation(t1: ByteArray?, t2: ByteArray?): Float {
        if (t1 == null || t2 == null || t1.isEmpty() || t2.isEmpty()) return 0f
        val e1 = FaceEngine.bytesToEmbedding(t1) ?: return 0f
        val e2 = FaceEngine.bytesToEmbedding(t2) ?: return 0f
        return FaceEngine.cosineSimilarity(e1, e2)
    }

    fun yuv2Bitmap(yuv: ByteArray?, width: Int, height: Int, rotation: Int): Bitmap? {
        if (yuv == null) return null
        return FaceEngine.yuv2Bitmap(yuv, width, height, rotation)
    }
}
