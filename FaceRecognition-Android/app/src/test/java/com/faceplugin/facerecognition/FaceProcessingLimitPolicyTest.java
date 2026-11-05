package com.faceplugin.facerecognition;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class FaceProcessingLimitPolicyTest {
    @Test
    public void tenantLimitThreeProcessesThreeFaces() {
        assertEquals(3, FaceProcessingLimitPolicy.processedCount(8, 3));
    }

    @Test
    public void tenantLimitFiveProcessesFiveFaces() {
        assertEquals(5, FaceProcessingLimitPolicy.processedCount(8, 5));
    }

    @Test
    public void detectedCountBelowLimitIsPreserved() {
        assertEquals(2, FaceProcessingLimitPolicy.processedCount(2, 5));
    }
}
