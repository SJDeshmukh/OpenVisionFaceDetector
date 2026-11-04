package com.faceplugin.facerecognition;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CooldownFeedbackPolicyTest {
    @Test
    public void markedInQueueNotifiesAfterFaceMovesToFront() {
        assertTrue(CooldownFeedbackPolicy.shouldNotify(
                null, 1_000L, 0.010f, 0.040f, 2_900L, 3_000L, 60));
    }

    @Test
    public void sameFacePositionDoesNotRepeatFeedback() {
        assertFalse(CooldownFeedbackPolicy.shouldNotify(
                null, 1_000L, 0.040f, 0.041f, 1_900L, 2_000L, 60));
    }

    @Test
    public void frontFaceNotifiesWhenItReentersCamera() {
        assertTrue(CooldownFeedbackPolicy.shouldNotify(
                null, 1_000L, 0.040f, 0.040f, 1_000L, 3_000L, 60));
    }

    @Test
    public void locallyMarkedFrontFaceNotifiesAfterTwoSecondDelay() {
        assertTrue(CooldownFeedbackPolicy.shouldNotify(
                null, 1_000L, 0.040f, 0.040f, 2_900L, 3_000L, 60));
    }

    @Test
    public void feedbackIsBlockedImmediatelyAfterAttendanceAndDuringThrottle() {
        assertFalse(CooldownFeedbackPolicy.shouldNotify(
                null, 1_500L, 0.010f, 0.040f, 1_800L, 2_000L, 60));
        assertFalse(CooldownFeedbackPolicy.shouldNotify(
                1_500L, 0L, 0.010f, 0.040f, 1_800L, 2_000L, 60));
    }
}
