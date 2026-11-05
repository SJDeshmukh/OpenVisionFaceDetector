package com.faceplugin.facerecognition;

/** Local guard for explicit kiosk actions while the device is offline. */
final class ManualAttendanceActionPolicy {
    static final class Decision {
        final boolean allowed;
        final String reason;
        final String message;

        Decision(boolean allowed, String reason, String message) {
            this.allowed = allowed;
            this.reason = reason;
            this.message = message;
        }
    }

    private ManualAttendanceActionPolicy() {}

    static boolean isCurrentSelection(String dispatchedAction, long dispatchedRevision,
                                      String currentAction, long currentRevision) {
        if (dispatchedRevision != currentRevision) return false;
        if (dispatchedAction == null || currentAction == null) return false;
        return dispatchedAction.trim().equalsIgnoreCase(currentAction.trim());
    }

    static Decision decide(String action, String lastStatus, String lastOperationalDate,
                           String currentOperationalDate, String name) {
        String normalizedAction = action == null ? "" : action.trim().toUpperCase();
        String normalizedStatus = lastStatus == null ? "" : lastStatus.trim().toUpperCase();
        boolean sameShiftDay = currentOperationalDate != null
                && currentOperationalDate.equals(lastOperationalDate);
        String safeName = name == null ? "Employee" : name;

        if ("CHECK_IN".equals(normalizedAction)) {
            if (sameShiftDay && "CHECK_IN".equals(normalizedStatus)) {
                return new Decision(false, "already_checked_in",
                        safeName + ", check in is already active");
            }
            return new Decision(true, null, null);
        }
        if ("CHECK_OUT".equals(normalizedAction)) {
            if (sameShiftDay && "CHECK_OUT".equals(normalizedStatus)) {
                return new Decision(false, "already_checked_out",
                        safeName + ", check out is already marked");
            }
            if (!sameShiftDay || !"CHECK_IN".equals(normalizedStatus)) {
                return new Decision(false, "not_checked_in",
                        safeName + ", check in must be marked first");
            }
            return new Decision(true, null, null);
        }
        return new Decision(false, "manual_action_required",
                "Select Check In or Check Out before scanning");
    }
}
