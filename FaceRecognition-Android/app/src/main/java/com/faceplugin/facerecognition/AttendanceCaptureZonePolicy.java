package com.faceplugin.facerecognition;

/** Separates visible/tracked faces from faces close enough to mark attendance. */
final class AttendanceCaptureZonePolicy {
    static final float MIN_FACE_AREA_RATIO = 0.035f;
    static final float MIN_RELATIVE_AREA = 0.55f;

    private AttendanceCaptureZonePolicy() {}

    static boolean isEligible(float x1, float y1, float x2, float y2,
                              int frameWidth, int frameHeight, float largestAreaRatio) {
        if (frameWidth <= 0 || frameHeight <= 0 || x2 <= x1 || y2 <= y1) return false;
        float areaRatio = ((x2 - x1) * (y2 - y1)) / ((float) frameWidth * frameHeight);
        float centerX = ((x1 + x2) * 0.5f) / frameWidth;
        float centerY = ((y1 + y2) * 0.5f) / frameHeight;
        boolean inCaptureZone = centerX >= 0.12f && centerX <= 0.88f
                && centerY >= 0.10f && centerY <= 0.90f;
        boolean foregroundSize = areaRatio >= MIN_FACE_AREA_RATIO
                && (largestAreaRatio <= 0f || areaRatio >= largestAreaRatio * MIN_RELATIVE_AREA);
        return inCaptureZone && foregroundSize;
    }
}
