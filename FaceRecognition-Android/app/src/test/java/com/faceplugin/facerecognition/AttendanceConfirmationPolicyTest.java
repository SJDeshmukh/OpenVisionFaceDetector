package com.faceplugin.facerecognition;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class AttendanceConfirmationPolicyTest {
    @Test
    public void matchingServerStatusDoesNotRepeatLocalAnnouncement() {
        assertFalse(AttendanceConfirmationPolicy.shouldAnnounceServerResult(
                "CHECK_IN", "check_in", true));
    }

    @Test
    public void reconciledServerStatusIsAnnounced() {
        assertTrue(AttendanceConfirmationPolicy.shouldAnnounceServerResult(
                "CHECK_IN", "CHECK_OUT", true));
    }

    @Test
    public void serverResultIsAnnouncedWhenLocalFeedbackWasNotShown() {
        assertTrue(AttendanceConfirmationPolicy.shouldAnnounceServerResult(
                "CHECK_IN", "CHECK_IN", false));
    }
}
