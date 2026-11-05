package com.faceplugin.facerecognition;

import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/** Keeps attendance state tied to one continuous appearance in the camera. */
final class FaceAppearanceTracker {
    static final long DEFAULT_EXIT_GRACE_MS = 2500L;
    static final int VISUAL_NONE = 0;
    static final int VISUAL_SUCCESS = 1;
    static final int VISUAL_COOLDOWN = 2;

    private static final class State {
        long lastSeenAtMs;
        boolean marked;
        boolean confirmed;
        boolean cooldownVisual;
        String status;
        long markedAtMs;
        long lastCooldownFeedbackAtMs;
    }

    private final long exitGraceMs;
    private final Map<String, State> states = new HashMap<>();

    FaceAppearanceTracker() {
        this(DEFAULT_EXIT_GRACE_MS);
    }

    FaceAppearanceTracker(long exitGraceMs) {
        if (exitGraceMs < 1) throw new IllegalArgumentException("exitGraceMs must be positive");
        this.exitGraceMs = exitGraceMs;
    }

    synchronized void expireStale(long nowMs) {
        Iterator<Map.Entry<String, State>> iterator = states.entrySet().iterator();
        while (iterator.hasNext()) {
            State state = iterator.next().getValue();
            if (nowMs >= state.lastSeenAtMs && nowMs - state.lastSeenAtMs > exitGraceMs) {
                iterator.remove();
            }
        }
    }

    synchronized void observe(String key, long nowMs) {
        if (key == null || key.isEmpty()) return;
        State state = states.get(key);
        if (state != null && nowMs >= state.lastSeenAtMs && nowMs - state.lastSeenAtMs > exitGraceMs) {
            states.remove(key);
            state = null;
        }
        if (state == null) {
            state = new State();
            states.put(key, state);
        }
        state.lastSeenAtMs = nowMs;
    }

    synchronized boolean isMarked(String key) {
        State state = states.get(key);
        return state != null && state.marked;
    }

    synchronized String getStatus(String key) {
        State state = states.get(key);
        return state == null ? null : state.status;
    }

    synchronized void mark(String key, String status, long nowMs) {
        observe(key, nowMs);
        State state = states.get(key);
        state.marked = true;
        state.confirmed = true;
        state.cooldownVisual = false;
        state.status = status;
        state.markedAtMs = nowMs;
        state.lastCooldownFeedbackAtMs = 0L;
    }

    /** Blocks duplicate scans while an online attendance request is awaiting confirmation. */
    synchronized void markPending(String key, String status, long nowMs) {
        observe(key, nowMs);
        State state = states.get(key);
        state.marked = true;
        state.confirmed = false;
        state.cooldownVisual = false;
        state.status = status;
        state.markedAtMs = nowMs;
        state.lastCooldownFeedbackAtMs = 0L;
    }

    /**
     * Marks a recognition as a cooldown hit and requests immediate feedback for
     * the first observation, followed by one request per repeat interval.
     */
    synchronized boolean markCooldownAndRequestFeedback(
            String key, String status, long nowMs, long repeatIntervalMs) {
        observe(key, nowMs);
        State state = states.get(key);
        state.marked = true;
        state.confirmed = true;
        state.cooldownVisual = true;
        state.status = status;
        if (state.markedAtMs == 0L) state.markedAtMs = nowMs;
        return requestCooldownFeedback(state, nowMs, repeatIntervalMs);
    }

    /**
     * Converts a successful green state to the red cooldown state after the
     * success window, and throttles repeated voice/UI feedback per person.
     */
    synchronized boolean requestCooldownFeedbackIfDue(
            String key, long nowMs, long successWindowMs, long repeatIntervalMs) {
        State state = states.get(key);
        if (state == null || !state.marked || !state.confirmed) return false;
        if (!state.cooldownVisual) {
            if (nowMs < state.markedAtMs || nowMs - state.markedAtMs < successWindowMs) {
                return false;
            }
            state.cooldownVisual = true;
        }
        return requestCooldownFeedback(state, nowMs, repeatIntervalMs);
    }

    synchronized int getVisualState(String key, long nowMs, long successWindowMs) {
        State state = states.get(key);
        if (state == null || !state.marked || !state.confirmed) return VISUAL_NONE;
        if (state.cooldownVisual) return VISUAL_COOLDOWN;
        if (nowMs >= state.markedAtMs && nowMs - state.markedAtMs >= successWindowMs) {
            return VISUAL_COOLDOWN;
        }
        return VISUAL_SUCCESS;
    }

    private boolean requestCooldownFeedback(State state, long nowMs, long repeatIntervalMs) {
        long interval = Math.max(1L, repeatIntervalMs);
        if (state.lastCooldownFeedbackAtMs > 0L
                && nowMs >= state.lastCooldownFeedbackAtMs
                && nowMs - state.lastCooldownFeedbackAtMs < interval) {
            return false;
        }
        state.lastCooldownFeedbackAtMs = nowMs;
        return true;
    }

    synchronized void clearMark(String key) {
        State state = states.get(key);
        if (state == null) return;
        state.marked = false;
        state.confirmed = false;
        state.cooldownVisual = false;
        state.status = null;
        state.markedAtMs = 0L;
        state.lastCooldownFeedbackAtMs = 0L;
    }

    synchronized void clearAll() {
        states.clear();
    }
}
