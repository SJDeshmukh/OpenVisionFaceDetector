package com.faceplugin.facerecognition;

/** Requires the same identity on several fresh frames before acting on a match. */
public final class ConsecutiveMatchGate {
    private final int requiredMatches;
    private final long maxGapMillis;
    private String candidateKey;
    private int count;
    private long lastSeenAt;

    public ConsecutiveMatchGate(int requiredMatches, long maxGapMillis) {
        if (requiredMatches < 1) throw new IllegalArgumentException("requiredMatches must be positive");
        if (maxGapMillis < 1) throw new IllegalArgumentException("maxGapMillis must be positive");
        this.requiredMatches = requiredMatches;
        this.maxGapMillis = maxGapMillis;
    }

    public synchronized boolean accept(String key, long nowMillis) {
        if (key == null || key.isEmpty()) {
            reset();
            return false;
        }
        boolean sameCandidate = key.equals(candidateKey);
        boolean inTime = nowMillis >= lastSeenAt && nowMillis - lastSeenAt <= maxGapMillis;
        if (!sameCandidate || !inTime) {
            candidateKey = key;
            count = 1;
        } else if (count < requiredMatches) {
            count++;
        }
        lastSeenAt = nowMillis;
        return count >= requiredMatches;
    }

    public synchronized void reset() {
        candidateKey = null;
        count = 0;
        lastSeenAt = 0L;
    }

    synchronized int getCountForTest() {
        return count;
    }
}
