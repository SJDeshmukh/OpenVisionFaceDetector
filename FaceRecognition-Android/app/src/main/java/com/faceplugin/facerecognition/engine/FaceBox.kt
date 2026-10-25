package com.faceplugin.facerecognition.engine

/**
 * Represents a detected face bounding box with landmarks.
 * Replaces com.ocp.facesdk.FaceBox and com.faceplugin.facerecognitionsdk.FaceBox.
 *
 * All fields are @JvmField so Java code can access them directly (box.x1, box.liveness, etc.)
 */
data class FaceBox(
    @JvmField val x1: Int,
    @JvmField val y1: Int,
    @JvmField val x2: Int,
    @JvmField val y2: Int,
    /** 5-point landmarks: [lx0,ly0, lx1,ly1, lx2,ly2, lx3,ly3, lx4,ly4] */
    @JvmField val landmarks: FloatArray = FloatArray(10),
    /** Detection confidence score 0..1 */
    @JvmField val score: Float = 1f,
    /** Liveness score 0..1 (set after liveness check). >= 0.5 means likely real. */
    @JvmField var liveness: Float = 0f,
    /** 512-d embedding (set after extraction) */
    @JvmField var embedding: FloatArray? = null,
    /** Matched person name (set after identification) */
    @JvmField var userName: String = "",
    /** Matched person id (set after identification) */
    @JvmField var personId: String = "",
    /** Similarity score to best match */
    @JvmField var similarity: Float = 0f,

    // --- Legacy stub fields to keep old Java code compiling ---
    @JvmField val landmarks_68: FloatArray = FloatArray(136),
    @JvmField var yaw: Float = 0f,
    @JvmField var pitch: Float = 0f,
    @JvmField var roll: Float = 0f,
    @JvmField var face_quality: Float = 1f,
    @JvmField var face_luminance: Float = 100f,
    @JvmField var face_occlusion: Float = 0f,
    @JvmField var left_eye_closed: Float = 0f,
    @JvmField var right_eye_closed: Float = 0f,
    @JvmField var mouth_opened: Float = 0f
) {
    val width: Int get() = x2 - x1
    val height: Int get() = y2 - y1

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is FaceBox) return false
        return x1 == other.x1 && y1 == other.y1 && x2 == other.x2 && y2 == other.y2
    }

    override fun hashCode(): Int = 31 * x1 + y1 + x2 + y2
}
