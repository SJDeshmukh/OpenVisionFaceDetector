package com.faceplugin.facerecognition;

import android.content.Context;
import android.graphics.Bitmap;
import android.util.Log;

import com.faceplugin.faceengine.FaceBox;

import java.util.ArrayList;
import java.util.List;

public class FaceRecognitionProcessor {
    private final Context context;

    public FaceRecognitionProcessor(Context context) {
        this.context = context.getApplicationContext();
    }

    public List<FaceResult> detectFaces(Bitmap bitmap) {
        if (bitmap == null) return new ArrayList<>();

        List<FaceResult> results = new ArrayList<>();
        try {
            // Local SCRFD detection and liveness analysis.
            List<FaceBox> faceBoxes = LocalFaceEngineFacade.INSTANCE.faceDetection(
                    bitmap, FacePipeline.secureDetectionParams(context));
            
            if (faceBoxes != null) {
                for (FaceBox box : faceBoxes) {
                    // Map FaceBox to FaceResult
                    // Assuming FaceBox has x1, y1, x2, y2, liveness
                    FaceResult res = new FaceResult(box.x1, box.y1, box.x2, box.y2, box.liveness);
                    res.yaw = box.yaw;
                    res.pitch = box.pitch;
                    res.roll = box.roll;
                    res.faceQuality = box.face_quality;
                    
                    // The local FaceIDApp models do not expose smile/eye probabilities.
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
            List<FaceBox> boxes = LocalFaceEngineFacade.INSTANCE.faceDetection(
                    bitmap, FacePipeline.secureDetectionParams(context));
            if (boxes.isEmpty()) return null;
            FaceBox best = null;
            float bestIou = -1f;
            for (FaceBox box : boxes) {
                float iou = intersectionOverUnion(box, faceResult);
                if (iou > bestIou) {
                    bestIou = iou;
                    best = box;
                }
            }
            if (best == null || !FacePipeline.recognitionReady(
                    context, best, bitmap.getWidth(), bitmap.getHeight())) return null;
            return LocalFaceEngineFacade.INSTANCE.templateExtraction(bitmap, best);
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    public float compare(byte[] emb1, byte[] emb2) {
        if (emb1 == null || emb2 == null) return 0f;
        try {
            return LocalFaceEngineFacade.INSTANCE.similarityCalculation(emb1, emb2);
        } catch (Exception e) {
            e.printStackTrace();
            return 0f;
        }
    }
    
    // Helper for direct embedding when a caller already has a frame.
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
        // Retained for compatibility with older callers.
        return new float[0];
    }

    private static float intersectionOverUnion(FaceBox box, FaceResult result) {
        int left = Math.max(box.x1, result.x1);
        int top = Math.max(box.y1, result.y1);
        int right = Math.min(box.x2, result.x2);
        int bottom = Math.min(box.y2, result.y2);
        long intersection = (long) Math.max(0, right - left) * Math.max(0, bottom - top);
        long boxArea = (long) box.width() * box.height();
        long resultArea = (long) Math.max(0, result.x2 - result.x1)
                * Math.max(0, result.y2 - result.y1);
        long union = boxArea + resultArea - intersection;
        return union <= 0 ? 0f : (float) intersection / union;
    }
}
