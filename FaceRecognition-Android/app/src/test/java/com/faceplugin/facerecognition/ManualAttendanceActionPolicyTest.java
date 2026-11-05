package com.faceplugin.facerecognition;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class ManualAttendanceActionPolicyTest {
    @Test public void permitsFirstCheckInForShiftDay() {
        assertTrue(ManualAttendanceActionPolicy.decide(
                "CHECK_IN", "CHECK_OUT", "2026-11-04", "2026-11-05", "Anant").allowed);
    }

    @Test public void permitsAnotherCheckInAfterCheckoutWithinShiftDay() {
        assertTrue(ManualAttendanceActionPolicy.decide(
                "CHECK_IN", "CHECK_OUT", "2026-11-05", "2026-11-05", "Anant").allowed);
    }

    @Test public void blocksConsecutiveCheckInsWhileSessionIsOpen() {
        assertFalse(ManualAttendanceActionPolicy.decide(
                "CHECK_IN", "CHECK_IN", "2026-11-05", "2026-11-05", "Anant").allowed);
    }

    @Test public void checkoutRequiresOpenCheckInOnSameShiftDay() {
        assertTrue(ManualAttendanceActionPolicy.decide(
                "CHECK_OUT", "CHECK_IN", "2026-11-05", "2026-11-05", "Anant").allowed);
        assertFalse(ManualAttendanceActionPolicy.decide(
                "CHECK_OUT", "CHECK_IN", "2026-11-04", "2026-11-05", "Anant").allowed);
        assertFalse(ManualAttendanceActionPolicy.decide(
                "CHECK_OUT", "CHECK_OUT", "2026-11-05", "2026-11-05", "Anant").allowed);
    }

    @Test public void actionChangeInvalidatesAnOlderRecognitionCycle() {
        assertTrue(ManualAttendanceActionPolicy.isCurrentSelection(
                "CHECK_IN", 4L, "CHECK_IN", 4L));
        assertFalse(ManualAttendanceActionPolicy.isCurrentSelection(
                "CHECK_IN", 4L, "CHECK_OUT", 5L));
        assertFalse(ManualAttendanceActionPolicy.isCurrentSelection(
                "CHECK_IN", 4L, "CHECK_IN", 6L));
    }
}
