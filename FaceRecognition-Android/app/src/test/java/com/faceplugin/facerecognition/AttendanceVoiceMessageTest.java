package com.faceplugin.facerecognition;

import static org.junit.Assert.assertEquals;

import java.util.Arrays;
import java.util.Collections;

import org.junit.Test;

public class AttendanceVoiceMessageTest {
    @Test public void announcesConfirmedCheckInWithName() {
        assertEquals("Anant Batre, checked in",
                AttendanceVoiceMessage.success("Anant Batre", "CHECK_IN"));
    }

    @Test public void announcesConfirmedCheckOutWithName() {
        assertEquals("Anant Batre, checked out",
                AttendanceVoiceMessage.success("Anant Batre", "CHECK_OUT"));
    }

    @Test public void keepsCooldownAnnouncementShort() {
        assertEquals("Anant Batre, check in already marked",
                AttendanceVoiceMessage.alreadyMarked("Anant Batre", "CHECK_IN"));
        assertEquals("Anant Batre, check out already marked",
                AttendanceVoiceMessage.alreadyMarked("Anant Batre", "CHECK_OUT"));
    }

    @Test public void offlineAnnouncementIncludesEachConfirmedAction() {
        assertEquals(
                "Anant Batre, checked in. Vijay Vable, checked out. Attendance saved offline",
                AttendanceVoiceMessage.savedOffline(
                        Arrays.asList("Anant Batre", "Vijay Vable"),
                        Arrays.asList("CHECK_IN", "CHECK_OUT")));
        assertEquals(
                "Employee, checked in. Attendance saved offline",
                AttendanceVoiceMessage.savedOffline(
                        Collections.singletonList(" "),
                        Collections.singletonList("CHECK_IN")));
    }
}
