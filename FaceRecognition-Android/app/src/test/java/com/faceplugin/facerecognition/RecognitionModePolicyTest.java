package com.faceplugin.facerecognition;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class RecognitionModePolicyTest {
    @Test
    public void onlyDedicatedUserLoginCanMarkAttendance() {
        assertTrue(RecognitionModePolicy.canMarkAttendance("user"));
        assertTrue(RecognitionModePolicy.canMarkAttendance(" USER "));

        assertFalse(RecognitionModePolicy.canMarkAttendance("vendor_admin"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("admin"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("owner"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("faculty"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("parent"));
        assertFalse(RecognitionModePolicy.canMarkAttendance(null));
        assertFalse(RecognitionModePolicy.canMarkAttendance(""));
    }
}
