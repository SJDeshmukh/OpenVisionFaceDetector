package com.faceplugin.faceengine;

/** Compatibility DTO used by the existing camera overlays and enrollment UI. */
public final class FaceBox {
    public int x1;
    public int y1;
    public int x2;
    public int y2;
    public float yaw;
    public float roll;
    public float pitch;
    public float liveness;
    public float face_quality;
    public float face_luminance;
    public float left_eye_closed;
    public float right_eye_closed;
    public float face_occlusion;
    public float mouth_opened;
    public float[] landmarks_68 = new float[10];
    public int landmarkCount;
    public String livenessLabel = "";
    public String maskLabel = "";
    public String qualityLabel = "";
    public String eyesLeftLabel = "";
    public String eyesRightLabel = "";

    public int width() {
        return Math.max(0, x2 - x1);
    }

    public int height() {
        return Math.max(0, y2 - y1);
    }
}
