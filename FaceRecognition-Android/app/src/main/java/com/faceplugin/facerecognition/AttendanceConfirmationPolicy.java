package com.faceplugin.facerecognition;

/** Controls whether a server response needs a second kiosk announcement. */
final class AttendanceConfirmationPolicy {
    private AttendanceConfirmationPolicy() {}

    static boolean shouldAnnounceServerResult(
            String locallyAnnouncedStatus,
            String serverStatus,
            boolean localFeedbackShown) {
        if (!localFeedbackShown) return true;
        if (locallyAnnouncedStatus == null || serverStatus == null) return true;
        return !locallyAnnouncedStatus.trim().equalsIgnoreCase(serverStatus.trim());
    }
}
