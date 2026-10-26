package com.faceplugin.facerecognition;

import android.content.Context;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import java.util.concurrent.TimeUnit;

public class SyncScheduler {
    public static void scheduleImmediate(Context ctx) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        // Download immediately so a kiosk can recognize people enrolled on another
        // vendor device as soon as connectivity returns.
        OneTimeWorkRequest faceDownload = new OneTimeWorkRequest.Builder(FaceDownloadWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(ctx)
                .enqueueUniqueWork("face-download", ExistingWorkPolicy.REPLACE, faceDownload);

        // Local faces must reach the server before attendance recorded against a
        // local identity. DBManager then replaces local IDs in the attendance queue
        // with the canonical server person ID.
        OneTimeWorkRequest faceSync = new OneTimeWorkRequest.Builder(FaceSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        OneTimeWorkRequest attendanceSync = new OneTimeWorkRequest.Builder(AttendanceSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
                .build();

        OneTimeWorkRequest deleteSync = new OneTimeWorkRequest.Builder(DeleteSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(ctx)
                .beginUniqueWork("sync-chain", ExistingWorkPolicy.REPLACE, faceSync)
                .then(attendanceSync)
                .then(deleteSync)
                .enqueue();
    }

    public static void schedulePeriodic(Context ctx) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        // Socket events update connected kiosks immediately. This periodic download is the
        // recovery path for a device that was offline or disconnected when an event occurred.
        PeriodicWorkRequest faceDownload = new PeriodicWorkRequest.Builder(FaceDownloadWorker.class, 15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build();

        WorkManager.getInstance(ctx)
                .enqueueUniquePeriodicWork("face-download-periodic", ExistingPeriodicWorkPolicy.KEEP, faceDownload);
    }
}
