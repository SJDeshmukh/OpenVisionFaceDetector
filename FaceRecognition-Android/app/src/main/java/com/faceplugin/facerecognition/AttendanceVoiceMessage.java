package com.faceplugin.facerecognition;

import java.util.List;

/** Builds short, consistent attendance announcements for the kiosk. */
final class AttendanceVoiceMessage {
    private AttendanceVoiceMessage() {}

    static String success(String name, String status) {
        return safeName(name) + ", " + completedAction(status);
    }

    static String alreadyMarked(String name, String status) {
        return safeName(name) + ", " + action(status) + " already marked";
    }

    static String savedOffline(List<String> names, List<String> statuses) {
        StringBuilder message = new StringBuilder();
        int count = Math.min(names == null ? 0 : names.size(), statuses == null ? 0 : statuses.size());
        for (int i = 0; i < count; i++) {
            if (message.length() > 0) message.append(". ");
            message.append(success(names.get(i), statuses.get(i)));
        }
        if (message.length() == 0) message.append("Attendance marked");
        message.append(". Attendance saved offline");
        return message.toString();
    }

    private static String safeName(String name) {
        if (name == null || name.trim().isEmpty()) return "Employee";
        return name.trim();
    }

    private static String action(String status) {
        return "CHECK_OUT".equalsIgnoreCase(status) ? "check out" : "check in";
    }

    private static String completedAction(String status) {
        return "CHECK_OUT".equalsIgnoreCase(status) ? "checked out" : "checked in";
    }
}
