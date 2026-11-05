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
    public void alreadyMarkedFeedbackOccursOncePerAppearance() {
        FaceAppearanceTracker tracker = new FaceAppearanceTracker(2500L);
        assertTrue(tracker.markAndRequestFeedback("7", "CHECK_IN", 1000L));
        assertFalse(tracker.markAndRequestFeedback("7", "CHECK_IN", 1200L));
    }
}
