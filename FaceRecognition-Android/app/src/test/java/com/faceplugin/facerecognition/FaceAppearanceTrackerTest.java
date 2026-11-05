package com.faceplugin.facerecognition;

import org.junit.Test;

import static org.junit.Assert.*;

public class FaceAppearanceTrackerTest {
    @Test
    public void continuousAppearanceStaysMarkedPastCooldown() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);
        tracker.observe("7", 1000L);
        tracker.mark("7", "CHECK_IN", 1100L);
        for (long now = 2000L; now <= 62000L; now += 1000L) {
            tracker.observe("7", now);
        }
        assertTrue(tracker.isMarked("7"));
        assertEquals("CHECK_IN", tracker.getStatus("7"));
    }

    @Test
    public void shortDetectionLossDoesNotResetAppearance() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);
        tracker.mark("7", "CHECK_IN", 1000L);
        tracker.expireStale(3000L);
        tracker.observe("7", 3000L);
        assertTrue(tracker.isMarked("7"));
    }

    @Test
    public void leavingPastGraceCreatesNewAppearance() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);
        tracker.mark("7", "CHECK_IN", 1000L);
        tracker.expireStale(3600L);
        tracker.observe("7", 3600L);
        assertFalse(tracker.isMarked("7"));
    }

    @Test
    public void confirmedAttendanceChangesFromGreenToRedAfterSuccessWindow() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);
        tracker.mark("7", "CHECK_IN", 1000L);

        assertEquals(FaceAppearanceTracker.VISUAL_SUCCESS,
                tracker.getVisualState("7", 2999L, 2000L));
        assertEquals(FaceAppearanceTracker.VISUAL_COOLDOWN,
                tracker.getVisualState("7", 3000L, 2000L));
    }

    @Test
    public void cooldownFeedbackRepeatsEveryTwoSeconds() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);
        tracker.mark("7", "CHECK_IN", 1000L);

        assertFalse(tracker.requestCooldownFeedbackIfDue("7", 2999L, 2000L, 2000L));
        assertTrue(tracker.requestCooldownFeedbackIfDue("7", 3000L, 2000L, 2000L));
        assertFalse(tracker.requestCooldownFeedbackIfDue("7", 4999L, 2000L, 2000L));
        assertTrue(tracker.requestCooldownFeedbackIfDue("7", 5000L, 2000L, 2000L));
    }

    @Test
    public void serverCooldownIsRedAndFeedbackIsThrottled() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);

        assertTrue(tracker.markCooldownAndRequestFeedback("7", "CHECK_OUT", 1000L, 2000L));
        assertEquals(FaceAppearanceTracker.VISUAL_COOLDOWN,
                tracker.getVisualState("7", 1000L, 2000L));
        assertFalse(tracker.requestCooldownFeedbackIfDue("7", 2999L, 2000L, 2000L));
        assertTrue(tracker.requestCooldownFeedbackIfDue("7", 3000L, 2000L, 2000L));
    }

    @Test
    public void pendingOnlineRequestBlocksDuplicatesAndShowsPendingState() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);
        tracker.markPending("7", "CHECK_IN", 1000L);

        assertTrue(tracker.isMarked("7"));
        assertEquals(FaceAppearanceTracker.VISUAL_PENDING,
                tracker.getVisualState("7", 1000L, 2000L));

        tracker.mark("7", "CHECK_IN", 1500L);
        assertEquals(FaceAppearanceTracker.VISUAL_SUCCESS,
                tracker.getVisualState("7", 1500L, 2000L));
    }
}
