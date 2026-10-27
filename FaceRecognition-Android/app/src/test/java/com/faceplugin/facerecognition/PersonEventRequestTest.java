package com.faceplugin.facerecognition;

import com.faceplugin.facerecognition.api.PersonEventRequest;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;

public class PersonEventRequestTest {
    @Test
    public void sourceEventIdIsStableForDirectRequestAndRetry() {
        String first = PersonEventRequest.buildSourceEventId(
                "device-a", "42", "local-ignored", "2026-10-27T09:00:00.123");
        String retry = PersonEventRequest.buildSourceEventId(
                "device-a", "42", "local-ignored", "2026-10-27T09:00:00.123");

        assertEquals(first, retry);
        assertEquals("device-a:42:2026-10-27T09:00:00.123", first);
    }

    @Test
    public void sourceEventIdSeparatesDevicesAndUsesLocalIdentity() {
        String deviceA = PersonEventRequest.buildSourceEventId(
                "device-a", null, "local-7", "2026-10-27T09:00:00.123");
        String deviceB = PersonEventRequest.buildSourceEventId(
                "device-b", null, "local-7", "2026-10-27T09:00:00.123");

        assertEquals("device-a:local:local-7:2026-10-27T09:00:00.123", deviceA);
        assertNotEquals(deviceA, deviceB);
    }
}
