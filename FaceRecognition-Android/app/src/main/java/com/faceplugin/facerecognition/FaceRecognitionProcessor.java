package com.faceplugin.facerecognition;

import android.content.Context;
import android.graphics.Bitmap;
import android.util.Log;

import com.ocp.facesdk.FaceBox;

import java.util.ArrayList;
import java.util.List;

public class FaceRecognitionProcessor {

    public FaceRecognitionProcessor(Context context) {
        // FaceSDK is initialized in MainActivity
    }

    public List<FaceResult> detectFaces(Bitmap bitmap) {
        if (bitmap == null) return new ArrayList<>();

        List<FaceResult> results = new ArrayList<>();
        try {
            // FaceSDK detection
            List<FaceBox> faceBoxes = FaceSDKWrapper.INSTANCE.faceDetection(bitmap, null);
            
            if (faceBoxes != null) {
                for (FaceBox box : faceBoxes) {
                    // Map FaceBox to FaceResult
                    // Assuming FaceBox has x1, y1, x2, y2, liveness
                    FaceResult res = new FaceResult(box.x1, box.y1, box.x2, box.y2, box.liveness);
                    res.yaw = box.yaw;
                    res.pitch = box.pitch;
                    res.roll = box.roll;
                    
                    // FaceSDK FaceBox usually doesn't have smile/eye prob directly unless enabled
                    // We'll leave them as default (-1 or 0)
                    
                    // FaceQuality might be available
                    // res.faceQuality = box.faceQuality; 
                    
                    results.add(res);
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        return results;
    }

    public byte[] getFaceEmbedding(Bitmap bitmap, FaceResult faceResult) {
        if (bitmap == null || faceResult == null) return null;

        try {
            // Reconstruct FaceBox from FaceResult
            List<FaceBox> boxes = FaceSDKWrapper.INSTANCE.faceDetection(bitmap, null);
            if (boxes.isEmpty()) return null;
            return FaceSDKWrapper.INSTANCE.templateExtraction(bitmap, boxes.get(0));
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    public float compare(byte[] emb1, byte[] emb2) {
        if (emb1 == null || emb2 == null) return 0f;
        try {
            return FaceSDKWrapper.INSTANCE.similarityCalculation(emb1, emb2);
        } catch (Exception e) {
            e.printStackTrace();
            return 0f;
        }
    }
    
    // Helper for direct embedding if needed (FaceSDK might not support this easily without box)
    // We can skip getFaceEmbeddingDirect or implement it by detecting face first
    public byte[] getFaceEmbeddingDirect(Bitmap faceBitmap) {
        List<FaceResult> faces = detectFaces(faceBitmap);
        if (!faces.isEmpty()) {
            return getFaceEmbedding(faceBitmap, faces.get(0));
        }
        return null;
    }

    // Utility for conversion if needed (but we are switching to byte[])
    public static float[] byteArrayToFloatArray(byte[] bytes) {
        // Not used with FaceSDK usually, but kept for compatibility if needed
        return new float[0];
    }
}
