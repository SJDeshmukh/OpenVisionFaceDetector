package com.faceplugin.facerecognition;

import android.graphics.Rect;

public class FaceResult {
    public int x1;
    public int y1;
    public int x2;
    public int y2;
    public float liveness;
    public float faceQuality;
    public float yaw;
    public float pitch;
    public float roll;
    
    // New fields for ML Kit features
    public float leftEyeOpenProbability;
    public float rightEyeOpenProbability;
    public float smilingProbability;

    public FaceResult(int x1, int y1, int x2, int y2, float liveness) {
        this.x1 = x1;
        this.y1 = y1;
        this.x2 = x2;
        this.y2 = y2;
        this.liveness = liveness;
    }

    public FaceResult(Rect rect, float liveness) {
        this.x1 = rect.left;
        this.y1 = rect.top;
        this.x2 = rect.right;
        this.y2 = rect.bottom;
        this.liveness = liveness;
    }
}
