package com.faceplugin.facerecognition.engine

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.util.Log
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/**
 * Top-level face recognition engine singleton.
 *
 * Replaces FaceSDKWrapper + the proprietary facesdk.aar entirely.
 *
 * Pipeline:
 *   Camera frame (YUV/NV21)
 *     → yuv2Bitmap()
 *     → detectFaces()     [SCRFD 500M]
 *     → checkLiveness()   [MiniFASNet-V2 or heuristic]
 *     → alignFace()       [5-point affine warp → 112×112]
 *     → extractEmbedding() [MobileFaceNet → 512-d float]
 *     → cosineSimilarity() [vs stored embeddings]
 */
object FaceEngine {

    private const val TAG = "FaceEngine"

    @Volatile private var detector: FaceDetector? = null
    @Volatile private var liveness: LivenessDetector? = null
    @Volatile private var extractor: EmbeddingExtractor? = null
    @Volatile var isInitialized = false
        private set

    /** Call once from SplashActivity on a background thread. */
    @Synchronized
    fun init(context: Context) {
        if (isInitialized) return
        var debugMsg = "Starting init...\n"
        try {
            val ctx = context.applicationContext
            debugMsg += "Loading FaceDetector...\n"
            detector  = FaceDetector(ctx)
            debugMsg += "Loading LivenessDetector...\n"
            liveness  = LivenessDetector(ctx)
            debugMsg += "Loading EmbeddingExtractor...\n"
            extractor = EmbeddingExtractor(ctx)
            isInitialized = true
            debugMsg += "Init SUCCESS\n"
            Log.i(TAG, "FaceEngine initialized — SCRFD + MobileFaceNet + liveness ready")
        } catch (e: Throwable) {
            debugMsg += "Init FAILED: ${e.message}\n"
            debugMsg += android.util.Log.getStackTraceString(e) + "\n"
            Log.e(TAG, "FaceEngine init failed", e)
        }
        try {
            val f = java.io.File(android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS), "face_engine_init.txt")
            val fos = java.io.FileOutputStream(f, true)
            fos.write(debugMsg.toByteArray())
            fos.close()
        } catch(ignored: Throwable) {}
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Public API  (mirrors the old FaceSDKWrapper interface)
    // ─────────────────────────────────────────────────────────────────────────

    /** Detect all faces in a bitmap. Returns empty list if not initialized. */
    fun detectFaces(bitmap: Bitmap): List<FaceBox> {
        if (!isInitialized) return emptyList()
        return try {
            detector?.detect(bitmap) ?: emptyList()
        } catch (e: Throwable) {
            try {
                val f = java.io.File(android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS), "face_engine_detect.txt")
                val fos = java.io.FileOutputStream(f, true)
                fos.write(("Detect FAILED: ${e.message}\n" + android.util.Log.getStackTraceString(e)).toByteArray())
                fos.close()
            } catch(ignored: Throwable) {}
            Log.e(TAG, "detectFaces error", e)
            emptyList()
        }
    }

    /**
     * Run liveness check on a face.
     * @return score 0..1; >= 0.5 means likely real.
     */
    fun checkLiveness(fullBitmap: Bitmap, faceBox: FaceBox): Float {
        if (!isInitialized) return 0f
        return try {
            val score = liveness?.checkLiveness(fullBitmap, faceBox) ?: 0.5f
            faceBox.liveness = score
            score
        } catch (e: Throwable) {
            Log.e(TAG, "checkLiveness error", e)
            0f
        }
    }

    /**
     * Align face to 112×112 canonical frame using 5-point landmarks.
     */
    fun alignFace(bitmap: Bitmap, faceBox: FaceBox): Bitmap {
        return try {
            FaceAligner.align(bitmap, faceBox)
        } catch (e: Throwable) {
            Log.e(TAG, "alignFace error", e)
            Bitmap.createScaledBitmap(bitmap, 112, 112, true)
        }
    }

    /**
     * Extract 512-d L2-normalized embedding from a face bitmap.
     * Use [alignFace] first for best accuracy.
     */
    fun extractEmbedding(bitmap: Bitmap, faceBox: FaceBox): FloatArray? {
        if (!isInitialized) return null
        return try {
            val aligned = FaceAligner.align(bitmap, faceBox)
            val emb = extractor?.extract(aligned)
            faceBox.embedding = emb
            emb
        } catch (e: Throwable) {
            Log.e(TAG, "extractEmbedding error", e)
            null
        }
    }

    /**
     * Cosine similarity between two L2-normalized embeddings.
     * Range 0..1 (we shift from [-1,1] to [0,1] for easier thresholding).
     */
    fun cosineSimilarity(a: FloatArray, b: FloatArray): Float {
        return try {
            val raw = extractor?.cosineSimilarity(a, b) ?: 0f
            // Shift [-1,1] → [0,1]
            (raw + 1f) / 2f
        } catch (e: Throwable) {
            0f
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Embedding serialization helpers (for SQLite BLOB storage)
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Serialize a 512-d embedding to a BLOB for SQLite storage.
     * Accepts nullable FloatArray (e.g. result of extractEmbedding) — returns null if input is null.
     */
    fun embeddingToBytes(embedding: FloatArray?): ByteArray? {
        if (embedding == null) return null
        val buf = ByteBuffer.allocate(embedding.size * 4)
        buf.asFloatBuffer().put(embedding)
        return buf.array()
    }

    fun bytesToEmbedding(bytes: ByteArray?): FloatArray? {
        if (bytes == null || bytes.isEmpty() || bytes.size % 4 != 0) return null
        return try {
            val fb = ByteBuffer.wrap(bytes).asFloatBuffer()
            FloatArray(fb.remaining()) { fb.get() }
        } catch (e: Throwable) {
            null
        }
    }

    /**
     * Java-friendly similarity: takes two ByteArray blobs from DB,
     * deserializes them, and returns cosine similarity 0..1.
     * Returns 0f if either blob is null/invalid.
     */
    @JvmStatic
    fun similarityFromBytes(a: ByteArray?, b: ByteArray?): Float {
        val embA = bytesToEmbedding(a) ?: return 0f
        val embB = bytesToEmbedding(b) ?: return 0f
        return cosineSimilarity(embA, embB)
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Camera helpers
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Convert NV21 byte array from CameraX ImageAnalysis to Bitmap.
     * @param nv21   raw NV21 bytes
     * @param width  frame width
     * @param height frame height
     * @param cameraMode FaceSDK mode (0-3 back, 4-7 front mirrored)
     */
    fun yuv2Bitmap(nv21: ByteArray, width: Int, height: Int, cameraMode: Int): Bitmap? {
        return try {
            val yuvImage = YuvImage(nv21, ImageFormat.NV21, width, height, null)
            val out = ByteArrayOutputStream()
            yuvImage.compressToJpeg(Rect(0, 0, width, height), 90, out)
            val jpegBytes = out.toByteArray()
            val bmp = android.graphics.BitmapFactory.decodeByteArray(jpegBytes, 0, jpegBytes.size)
                ?: return null

            val rotation = (cameraMode % 4) * 90f
            val isFront = cameraMode >= 4

            val finalBmp = if (rotation == 0f && !isFront) bmp
            else {
                val matrix = android.graphics.Matrix()
                matrix.postRotate(rotation)
                if (isFront) {
                    matrix.postScale(-1f, 1f, bmp.width / 2f, bmp.height / 2f)
                }
                Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, matrix, true)
            }

            // --- DEBUG ONLY ---
            try {
                if (Math.random() < 0.05) { // Save ~5% of frames
                    val file = java.io.File(android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS), "face_debug_frame.jpg")
                    val fos = java.io.FileOutputStream(file)
                    finalBmp.compress(Bitmap.CompressFormat.JPEG, 90, fos)
                    fos.close()
                }
            } catch (e: Exception) {
                // Ignore
            }
            // ------------------

            return finalBmp
        } catch (e: Throwable) {
            android.util.Log.e(TAG, "yuv2Bitmap error", e)
            null
        }
    }

    fun close() {
        detector?.close()
        liveness?.close()
        extractor?.close()
        isInitialized = false
    }
}
