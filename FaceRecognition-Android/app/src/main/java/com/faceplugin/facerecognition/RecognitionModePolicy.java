package com.faceplugin.facerecognition;

import java.util.Locale;

/** Authorization for recognition side effects. */
public final class RecognitionModePolicy {
    private RecognitionModePolicy() {}

    /** Dedicated kiosk/user login, as well as offline cached kiosk sessions, are authorized to mark attendance. */
    public static boolean canMarkAttendance(String role) {
        if (role == null || role.trim().isEmpty()) {
            // Default to user/kiosk mode when role is unspecified (offline kiosk session)
            return true;
        }
        String normalized = role.trim().toLowerCase(Locale.US);
        return "user".equals(normalized) || "kiosk".equals(normalized);
    }
}
