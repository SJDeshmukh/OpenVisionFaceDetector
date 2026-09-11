package com.faceplugin.facerecognition;

import java.util.Locale;

/** Fail-closed authorization for recognition side effects. */
public final class RecognitionModePolicy {
    private RecognitionModePolicy() {}

    /** The dedicated kiosk/user login is the only role allowed to mark attendance. */
    public static boolean canMarkAttendance(String role) {
        return role != null && "user".equals(role.trim().toLowerCase(Locale.US));
    }
}
