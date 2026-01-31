package com.faceplugin.facesdk;

import android.graphics.Bitmap;

import java.util.ArrayList;
import java.util.List;

public class FaceSDK {
    public static List<FaceBox> faceDetection(Bitmap bitmap, Object options) {
        return new ArrayList<>();
    }

    public static byte[] templateExtraction(Bitmap bitmap, FaceBox box) {
        return new byte[0];
    }

    public static float similarityCalculation(byte[] emb1, byte[] emb2) {
        if (emb1 == null || emb2 == null) return 0f;
        int len = Math.min(emb1.length, emb2.length);
        if (len == 0) return 0f;
        int equal = 0;
        for (int i = 0; i < len; i++) {
            if (emb1[i] == emb2[i]) {
                equal++;
            }
        }
        return (float) equal / (float) len;
    }
}
