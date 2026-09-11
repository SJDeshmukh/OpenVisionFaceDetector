package com.faceplugin.faceengine

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.graphics.RectF
import com.example.faceid.ml.AntiSpoofDetector
import com.example.faceid.ml.FaceDetector
import com.example.faceid.ml.FaceRecognizer
import com.example.faceid.ml.ImageUtils
import com.example.faceid.ml.LivenessGate
import java.util.WeakHashMap
import kotlin.math.atan2

/** Runs the FaceIDApp ONNX pipeline behind the app's existing byte-template contract. */
object LocalFaceEngine {
    const val SUCCESS = 0
    const val INIT_FAILED = -1

    private data class Components(
        val detector: FaceDetector,
        val antiSpoof: AntiSpoofDetector,
        val livenessGate: LivenessGate,
        val recognizer: FaceRecognizer
    )

    @Volatile
    private var components: Components? = null

    /** Weak keys avoid retaining probe templates or people removed from the gallery. */
    private val decodedTemplateCache = WeakHashMap<ByteArray, FloatArray>()

    @Volatile
    var lastInitializationError: String? = null
        private set

    @Synchronized
    fun initialize(context: Context): Int {
        if (components != null) return SUCCESS
        var detector: FaceDetector? = null
        var antiSpoof: AntiSpoofDetector? = null
        var recognizer: FaceRecognizer? = null
        return try {
            val loadedDetector = FaceDetector(context.applicationContext)
            detector = loadedDetector
            val loadedAntiSpoof = AntiSpoofDetector(context.applicationContext, liveIndex = 1)
            antiSpoof = loadedAntiSpoof
            val loadedRecognizer = FaceRecognizer(context.applicationContext)
            recognizer = loadedRecognizer
            components = Components(
                loadedDetector,
                loadedAntiSpoof,
                LivenessGate(loadedAntiSpoof),
                loadedRecognizer
            )
            lastInitializationError = null
            SUCCESS
        } catch (error: Throwable) {
            runCatching { detector?.close() }
            runCatching { antiSpoof?.close() }
            runCatching { recognizer?.close() }
            lastInitializationError = buildString {
                append(error.javaClass.simpleName)
                error.message?.takeIf { it.isNotBlank() }?.let { append(": ").append(it) }
            }
            INIT_FAILED
        }
    }

    fun isInitialized(): Boolean = components != null

    @Synchronized
    fun detect(bitmap: Bitmap, param: FaceDetectionParam?): List<FaceBox> {
        val engine = components ?: return emptyList()
        if (bitmap.isRecycled || bitmap.width <= 0 || bitmap.height <= 0) return emptyList()
        return engine.detector.detect(bitmap).mapNotNull { detected ->
            if (!detected.score.isFinite()
                || !detected.box.left.isFinite() || !detected.box.top.isFinite()
                || !detected.box.right.isFinite() || !detected.box.bottom.isFinite()
                || detected.landmarks.size < 10 || detected.landmarks.any { !it.isFinite() }) {
                return@mapNotNull null
            }
            val left = detected.box.left.toInt().coerceIn(0, bitmap.width)
            val top = detected.box.top.toInt().coerceIn(0, bitmap.height)
            val right = detected.box.right.toInt().coerceIn(0, bitmap.width)
            val bottom = detected.box.bottom.toInt().coerceIn(0, bitmap.height)
            if (right <= left || bottom <= top) return@mapNotNull null

            FaceBox().apply {
                x1 = left
                y1 = top
                x2 = right
                y2 = bottom
                face_quality = detected.score.coerceIn(0f, 1f)
                qualityLabel = when {
                    face_quality >= 0.75f -> "high"
                    face_quality >= 0.5f -> "medium"
                    else -> "low"
                }
                face_luminance = luminance(bitmap, left, top, right, bottom)
                landmarks_68 = detected.landmarks.copyOf()
                landmarkCount = detected.landmarks.size / 2
                if (landmarkCount >= 2) {
                    val dx = detected.landmarks[2] - detected.landmarks[0]
                    val dy = detected.landmarks[3] - detected.landmarks[1]
                    roll = Math.toDegrees(atan2(dy, dx).toDouble()).toFloat()
                }
                if (landmarkCount >= 3) {
                    val eyeDistance = kotlin.math.abs(detected.landmarks[2] - detected.landmarks[0]).coerceAtLeast(1f)
                    val eyeMidX = (detected.landmarks[0] + detected.landmarks[2]) / 2f
                    yaw = ((detected.landmarks[4] - eyeMidX) / eyeDistance * 45f).coerceIn(-90f, 90f)
                }
                pitch = 0f

                if (param?.check_liveness == true) {
                    val box = RectF(left.toFloat(), top.toFloat(), right.toFloat(), bottom.toFloat())
                    val crop4x = safeCrop(bitmap, expand(box, 4f))
                    val crop2_7x = safeCrop(bitmap, expand(box, 2.7f))
                    try {
                        val verdict = engine.livenessGate.evaluate(crop4x, crop2_7x)
                        liveness = verdict.cnnResult.liveScore.coerceIn(0f, 1f)
                        livenessLabel = when {
                            verdict.isLive -> "live"
                            verdict.rejectReason?.name == "MOIRE_PATTERN" -> "replay_attack"
                            else -> "spoof_attack"
                        }
                    } finally {
                        crop4x.recycleSafely(bitmap)
                        crop2_7x.recycleSafely(bitmap, crop4x)
                    }
                } else {
                    liveness = 1f
                    livenessLabel = "not_checked"
                }
            }
        }
    }

    @Synchronized
    fun extractTemplate(bitmap: Bitmap, face: FaceBox): ByteArray? {
        val engine = components ?: return null
        if (face.landmarkCount < 5 || face.landmarks_68.size < 10) return null
        val aligned = ImageUtils.alignFace(bitmap, face.landmarks_68.copyOf(10))
        return try {
            FaceTemplateCodec.encode(engine.recognizer.getEmbedding(aligned))
        } finally {
            aligned.recycleSafely(bitmap)
        }
    }

    @Synchronized
    fun similarity(first: ByteArray, second: ByteArray): Float {
        val a = decodedTemplate(first) ?: return 0f
        val b = decodedTemplate(second) ?: return 0f
        return FaceRecognizer.cosineSimilarity(a, b).coerceIn(-1f, 1f)
    }

    fun aggregateTemplates(templates: List<ByteArray>): ByteArray? {
        val embeddings = templates.mapNotNull(FaceTemplateCodec::decode)
        if (embeddings.size != templates.size || embeddings.isEmpty()) return null
        return FaceTemplateCodec.encode(FaceRecognizer.aggregate(embeddings))
    }

    private fun decodedTemplate(template: ByteArray): FloatArray? {
        decodedTemplateCache[template]?.let { return it }
        return FaceTemplateCodec.decode(template)?.also { decodedTemplateCache[template] = it }
    }

    fun nv21ToBitmap(nv21: ByteArray, width: Int, height: Int, mode: Int): Bitmap? {
        if (width <= 0 || height <= 0 || nv21.size < width.toLong() * height * 3 / 2) return null
        val argb = IntArray(width * height)
        var yp = 0
        for (y in 0 until height) {
            var uvp = width * height + (y shr 1) * width
            var u = 0
            var v = 0
            for (x in 0 until width) {
                var yy = (nv21[yp].toInt() and 0xff) - 16
                if (yy < 0) yy = 0
                if (x and 1 == 0) {
                    v = (nv21[uvp++].toInt() and 0xff) - 128
                    u = (nv21[uvp++].toInt() and 0xff) - 128
                }
                val y1192 = 1192 * yy
                var r = y1192 + 1634 * v
                var g = y1192 - 833 * v - 400 * u
                var b = y1192 + 2066 * u
                r = r.coerceIn(0, 262143)
                g = g.coerceIn(0, 262143)
                b = b.coerceIn(0, 262143)
                argb[yp++] = -0x1000000 or ((r shl 6) and 0xff0000) or
                    ((g shr 2) and 0xff00) or ((b shr 10) and 0xff)
            }
        }
        val source = Bitmap.createBitmap(argb, width, height, Bitmap.Config.ARGB_8888)
        val rotation = when (mode and 3) { 1 -> 90f; 2 -> 180f; 3 -> 270f; else -> 0f }
        val matrix = Matrix().apply {
            postRotate(rotation)
            if (mode >= 4) postScale(-1f, 1f)
        }
        if (rotation == 0f && mode < 4) return source
        return try {
            Bitmap.createBitmap(source, 0, 0, width, height, matrix, true)
        } finally {
            source.recycle()
        }
    }

    private fun expand(box: RectF, scale: Float): RectF {
        val dx = box.width() * (scale - 1f) / 2f
        val dy = box.height() * (scale - 1f) / 2f
        return RectF(box.left - dx, box.top - dy, box.right + dx, box.bottom + dy)
    }

    private fun safeCrop(bitmap: Bitmap, rect: RectF): Bitmap {
        val left = rect.left.toInt().coerceIn(0, bitmap.width - 1)
        val top = rect.top.toInt().coerceIn(0, bitmap.height - 1)
        val right = rect.right.toInt().coerceIn(left + 1, bitmap.width)
        val bottom = rect.bottom.toInt().coerceIn(top + 1, bitmap.height)
        return Bitmap.createBitmap(bitmap, left, top, right - left, bottom - top)
    }

    private fun luminance(bitmap: Bitmap, left: Int, top: Int, right: Int, bottom: Int): Float {
        val stepX = ((right - left) / 16).coerceAtLeast(1)
        val stepY = ((bottom - top) / 16).coerceAtLeast(1)
        var total = 0L
        var count = 0
        var y = top
        while (y < bottom) {
            var x = left
            while (x < right) {
                val pixel = bitmap.getPixel(x, y)
                val r = pixel shr 16 and 0xff
                val g = pixel shr 8 and 0xff
                val b = pixel and 0xff
                total += (299L * r + 587L * g + 114L * b) / 1000L
                count++
                x += stepX
            }
            y += stepY
        }
        return if (count == 0) 0f else total.toFloat() / count / 255f
    }

    private fun Bitmap.recycleSafely(vararg retained: Bitmap) {
        if (retained.none { it === this } && !isRecycled) recycle()
    }
}
