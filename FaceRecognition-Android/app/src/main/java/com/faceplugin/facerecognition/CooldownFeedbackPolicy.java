package com.faceplugin.facerecognition;

/** Decides when a cooldown recognition should be surfaced to the person at the camera. */
final class CooldownFeedbackPolicy {
    static final long FACE_REENTRY_GAP_MS = 2000L;
    static final long MIN_LOCAL_FEEDBACK_DELAY_MS = 2000L;
    static final float FRONT_FACE_AREA_RATIO = 0.025f;

    private CooldownFeedbackPolicy() {}

    static boolean shouldNotify(
            Long lastFeedbackAtMs,
            Long lastEventSentAtMs,
            Float markedFaceAreaRatio,
            float currentFaceAreaRatio,
            Long previousSeenAtMs,
            long nowMs,
            int cooldownSeconds) {
        long feedbackThrottleMs = Math.max(5000L, Math.max(0, cooldownSeconds) * 1000L);
        if (lastFeedbackAtMs != null && nowMs - lastFeedbackAtMs < feedbackThrottleMs) {
            return false;
        }
        if (lastEventSentAtMs != null && nowMs - lastEventSentAtMs < MIN_LOCAL_FEEDBACK_DELAY_MS) {
            return false;
        }

        boolean movedToFront = markedFaceAreaRatio != null
                && currentFaceAreaRatio >= FRONT_FACE_AREA_RATIO
                && currentFaceAreaRatio >= markedFaceAreaRatio * 1.25f;
        boolean reenteredAtFront = previousSeenAtMs != null
                && nowMs - previousSeenAtMs >= FACE_REENTRY_GAP_MS
                && currentFaceAreaRatio >= FRONT_FACE_AREA_RATIO;
        boolean firstLocalObservationAtFront = markedFaceAreaRatio == null
                && currentFaceAreaRatio >= FRONT_FACE_AREA_RATIO;
        boolean locallyMarkedAndNowAtFront = lastEventSentAtMs != null
                && nowMs - lastEventSentAtMs >= MIN_LOCAL_FEEDBACK_DELAY_MS
                && currentFaceAreaRatio >= FRONT_FACE_AREA_RATIO;
        return movedToFront || reenteredAtFront || firstLocalObservationAtFront || locallyMarkedAndNowAtFront;
    }
}
