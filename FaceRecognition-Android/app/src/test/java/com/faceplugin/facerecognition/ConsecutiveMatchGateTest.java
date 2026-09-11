package com.faceplugin.facerecognition;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class ConsecutiveMatchGateTest {
    @Test
    public void confirmsOnlyAfterRequiredConsecutiveMatches() {
        ConsecutiveMatchGate gate = new ConsecutiveMatchGate(3, 1000);
        assertFalse(gate.accept("alice", 100));
        assertFalse(gate.accept("alice", 200));
        assertTrue(gate.accept("alice", 300));
        assertTrue(gate.accept("alice", 400));
    }

    @Test
    public void identityChangeAndTimeoutRestartConfirmation() {
        ConsecutiveMatchGate gate = new ConsecutiveMatchGate(2, 1000);
        assertFalse(gate.accept("alice", 100));
        assertFalse(gate.accept("bob", 200));
        assertTrue(gate.accept("bob", 300));
        assertFalse(gate.accept("bob", 1401));
        assertTrue(gate.accept("bob", 1500));
    }

    @Test
    public void invalidCandidateClearsPendingMatch() {
        ConsecutiveMatchGate gate = new ConsecutiveMatchGate(2, 1000);
        assertFalse(gate.accept("alice", 100));
        assertFalse(gate.accept(null, 200));
        assertFalse(gate.accept("alice", 300));
        assertTrue(gate.accept("alice", 400));
    }
}
