package com.faceplugin.facerecognition;

import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/** Keeps attendance state tied to one continuous appearance in the camera. */
final class FaceAppearanceTracker {
    static final long DEFAULT_EXIT_GRACE_MS = 2500L;

    private static final class State {
        long lastSeenAtMs;
        boolean marked;
        String status;
        boolean feedbackShown;
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
        state.status = status;
    }

    synchronized boolean markAndRequestFeedback(String key, String status, long nowMs) {
        mark(key, status, nowMs);
        State state = states.get(key);
        if (state.feedbackShown) return false;
        state.feedbackShown = true;
        return true;
    }

    synchronized void clearMark(String key) {
        State state = states.get(key);
        if (state == null) return;
        state.marked = false;
        state.status = null;
        state.feedbackShown = false;
    }
}
