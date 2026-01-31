package com.faceplugin.facerecognition;

import android.content.Context;

public class SyncScheduler {
    public static void scheduleImmediate(Context ctx) {
        AttendanceSyncWorker.Companion.scheduleImmediate(ctx);
        FaceSyncWorker.Companion.scheduleImmediate(ctx);
        DeleteSyncWorker.Companion.scheduleImmediate(ctx);
    }
}
