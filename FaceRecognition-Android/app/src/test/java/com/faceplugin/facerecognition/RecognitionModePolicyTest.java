package com.faceplugin.facerecognition;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class RecognitionModePolicyTest {
    @Test
    public void kioskAndOfflineKioskSessionsCanMarkAttendance() {
        assertTrue(RecognitionModePolicy.canMarkAttendance("user"));
        assertTrue(RecognitionModePolicy.canMarkAttendance(" USER "));
        assertTrue(RecognitionModePolicy.canMarkAttendance("kiosk"));
        assertTrue(RecognitionModePolicy.canMarkAttendance(null));
        assertTrue(RecognitionModePolicy.canMarkAttendance(""));

        assertFalse(RecognitionModePolicy.canMarkAttendance("vendor_admin"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("admin"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("owner"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("faculty"));
        assertFalse(RecognitionModePolicy.canMarkAttendance("parent"));
    }
}
