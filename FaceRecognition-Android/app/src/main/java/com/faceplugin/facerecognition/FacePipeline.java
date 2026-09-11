package com.faceplugin.facerecognition;

import android.content.Context;
import android.util.Size;

import com.faceplugin.faceengine.FaceBox;
import com.faceplugin.faceengine.FaceDetectionParam;

import java.util.List;
import java.util.Locale;

/**
 * Security policy shared by enrollment and recognition for the local FaceIDApp
 * pipeline: SCRFD detection, MiniFASNet plus Moire liveness, then ArcFace.
 * Embeddings are never extracted until the liveness and quality gates pass.
 */
public final class FacePipeline {
    private FacePipeline() {}

    /** Full, security-sensitive analysis. Use this before enrollment or matching. */
    public static FaceDetectionParam secureDetectionParams(Context context) {
        FaceDetectionParam param = new FaceDetectionParam();
        param.check_liveness = true;
        param.check_liveness_level = SettingsActivity.getLivenessLevel(context);
        param.check_landmarks = true;
        param.check_pose = true;
        param.check_quality = true;
        param.check_face_occlusion = true;
        param.check_eye_closeness = true;
        param.check_mask = true;
        return param;
    }

    public static boolean isLive(Context context, FaceBox face) {
        return face != null && SettingsActivity.livenessPassed(
                context, face.liveness, face.livenessLabel);
    }

    /** Less restrictive than enrollment, but still blocks poor/spoof inputs before extraction. */
    public static boolean recognitionReady(
            Context context, FaceBox face, int frameWidth, int frameHeight) {
        if (!hasValidBounds(face, frameWidth, frameHeight) || !isLive(context, face)) return false;
        int shorterFrameSide = Math.min(frameWidth, frameHeight);
        int shorterFaceSide = Math.min(face.width(), face.height());
        if (shorterFrameSide <= 0 || shorterFaceSide < shorterFrameSide * 0.12f) return false;
        if (Math.abs(face.yaw) > SettingsActivity.getYawThreshold(context)
                || Math.abs(face.roll) > SettingsActivity.getRollThreshold(context)
                || Math.abs(face.pitch) > SettingsActivity.getPitchThreshold(context)) return false;
        if (!Float.isFinite(face.face_quality)
                || face.face_quality < SettingsActivity.getFaceQualityThreshold(context) * 0.7f) return false;
        String mask = normalized(face.maskLabel);
        return !isMaskPresent(mask)
                && (mask.length() > 0 || face.face_occlusion <= SettingsActivity.getOcclusionThreshold(context));
    }

    /**
     * Validate an enrollment face. Expensive attributes must have been requested
     * with {@link #secureDetectionParams(Context)} before calling this method.
     */
    public static FACE_CAPTURE_STATE enrollmentState(
            List<FaceBox> faces, Context context, int width, int height) {
        if (faces == null || faces.isEmpty()) return FACE_CAPTURE_STATE.NO_FACE;
        if (faces.size() != 1) return FACE_CAPTURE_STATE.MULTIPLE_FACES;
        if (width <= 0 || height <= 0) return FACE_CAPTURE_STATE.NO_FACE;

        FaceBox face = faces.get(0);
        if (!hasValidBounds(face, width, height)) return FACE_CAPTURE_STATE.NO_FACE;

        float faceLeft = face.x1;
        float faceRight = face.x2;
        float faceBottom = face.y2;
        int availableLandmarks = face.landmarks_68 == null ? 0 : face.landmarks_68.length / 2;
        int landmarkCount = Math.max(0, Math.min(face.landmarkCount, availableLandmarks));
        if (landmarkCount >= 5) {
            faceLeft = Float.MAX_VALUE;
            faceRight = -Float.MAX_VALUE;
            faceBottom = -Float.MAX_VALUE;
            for (int i = 0; i < landmarkCount; i++) {
                float x = face.landmarks_68[i * 2];
                float y = face.landmarks_68[i * 2 + 1];
                if (!Float.isFinite(x) || !Float.isFinite(y)) continue;
                faceLeft = Math.min(faceLeft, x);
                faceRight = Math.max(faceRight, x);
                faceBottom = Math.max(faceBottom, y);
            }
            if (!Float.isFinite(faceLeft) || !Float.isFinite(faceRight) || !Float.isFinite(faceBottom)) {
                faceLeft = face.x1;
                faceRight = face.x2;
                faceBottom = face.y2;
            }
        }

        android.graphics.RectF roi = CaptureView.getROIRect(new Size(width, height));
        if (roi.width() <= 0f || roi.height() <= 0f) return FACE_CAPTURE_STATE.FIT_IN_CIRCLE;
        float centerY = (face.y2 + face.y1) / 2f;
        float topY = centerY - (face.y2 - face.y1) * 2f / 3f;
        float outsideX = Math.max(0f, roi.left - faceLeft) + Math.max(0f, faceRight - roi.right);
        float outsideY = Math.max(0f, roi.top - topY) + Math.max(0f, faceBottom - roi.bottom);
        if (outsideX / roi.width() > 0.10f || outsideY / roi.height() > 0.10f) {
            return FACE_CAPTURE_STATE.FIT_IN_CIRCLE;
        }

        long faceArea = (long) face.width() * face.height();
        if (faceArea < roi.width() * roi.height() * 0.25f) return FACE_CAPTURE_STATE.MOVE_CLOSER;

        if (Math.abs(face.yaw) > SettingsActivity.getYawThreshold(context)
                || Math.abs(face.roll) > SettingsActivity.getRollThreshold(context)
                || Math.abs(face.pitch) > SettingsActivity.getPitchThreshold(context)) {
            return FACE_CAPTURE_STATE.NO_FRONT;
        }

        String mask = normalized(face.maskLabel);
        if (isMaskPresent(mask) || (mask.isEmpty()
                && face.face_occlusion > SettingsActivity.getOcclusionThreshold(context))) {
            return FACE_CAPTURE_STATE.FACE_OCCLUDED;
        }

        String leftEye = normalized(face.eyesLeftLabel);
        String rightEye = normalized(face.eyesRightLabel);
        if (leftEye.contains("closed") || rightEye.contains("closed")
                || (leftEye.isEmpty() && rightEye.isEmpty()
                && (face.left_eye_closed > SettingsActivity.getEyecloseThreshold(context)
                || face.right_eye_closed > SettingsActivity.getEyecloseThreshold(context)))) {
            return FACE_CAPTURE_STATE.EYE_CLOSED;
        }

        if (face.mouth_opened > SettingsActivity.getMouthopenThreshold(context)) {
            return FACE_CAPTURE_STATE.MOUTH_OPENED;
        }
        if (!Float.isFinite(face.face_quality)
                || face.face_quality < SettingsActivity.getFaceQualityThreshold(context)) {
            return FACE_CAPTURE_STATE.LOW_QUALITY;
        }
        if (!Float.isFinite(face.face_luminance)
                || face.face_luminance < SettingsActivity.getMinLuminance(context)
                || face.face_luminance > SettingsActivity.getMaxLuminance(context)) {
            return FACE_CAPTURE_STATE.BAD_LIGHTING;
        }
        if (!isLive(context, face)) return FACE_CAPTURE_STATE.SPOOFED_FACE;
        return FACE_CAPTURE_STATE.CAPTURE_OK;
    }

    private static boolean hasValidBounds(FaceBox face, int width, int height) {
        return face != null && face.x1 >= 0 && face.y1 >= 0
                && face.x2 > face.x1 && face.y2 > face.y1
                && face.x2 <= width && face.y2 <= height;
    }

    private static String normalized(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US);
    }

    private static boolean isMaskPresent(String label) {
        if (label.isEmpty() || label.contains("no mask") || label.contains("no_mask")
                || label.contains("nomask") || label.contains("without")
                || label.equals("no") || label.equals("false")) return false;
        return label.equals("yes") || label.equals("true") || label.contains("mask");
    }
}
