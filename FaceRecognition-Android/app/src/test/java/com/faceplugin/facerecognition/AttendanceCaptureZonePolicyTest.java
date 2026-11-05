package com.faceplugin.facerecognition;

import org.junit.Test;

import static org.junit.Assert.*;

public class AttendanceCaptureZonePolicyTest {
    @Test
    public void foregroundFaceInZoneIsEligible() {
        assertTrue(AttendanceCaptureZonePolicy.isEligible(300, 200, 700, 700, 1000, 1000, 0.20f));
    }

    @Test
    public void smallBackgroundFaceIsTrackedButNotEligible() {
        assertFalse(AttendanceCaptureZonePolicy.isEligible(450, 300, 550, 400, 1000, 1000, 0.20f));
    }

    @Test
    public void edgeFaceIsNotEligible() {
        assertFalse(AttendanceCaptureZonePolicy.isEligible(0, 200, 200, 700, 1000, 1000, 0.10f));
    }
}
