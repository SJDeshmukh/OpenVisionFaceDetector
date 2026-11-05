package com.faceplugin.facerecognition;

/** Tenant-configured upper bound shared by detection and recognition. */
final class FaceProcessingLimitPolicy {
    static final int DEFAULT_LIMIT = 5;
    static final int MAX_LIMIT = 10;

    private FaceProcessingLimitPolicy() {}

    static int clamp(int configured) {
        return Math.max(1, Math.min(MAX_LIMIT, configured));
    }

    static int processedCount(int detectedCount, int configured) {
        return Math.min(Math.max(0, detectedCount), clamp(configured));
    }
}
