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
        // 1. Direct immediate background sync if currently online
        AttendanceSyncWorker.syncNow(ctx);

        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        // 2. AttendanceSyncWorker runs independently with REPLACE policy
        OneTimeWorkRequest attendanceSync = new OneTimeWorkRequest.Builder(AttendanceSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(ctx)
                .enqueueUniqueWork("attendance-sync", ExistingWorkPolicy.REPLACE, attendanceSync);

        // 3. Face download runs independently with REPLACE policy so latest gallery is fetched immediately
        OneTimeWorkRequest faceDownload = new OneTimeWorkRequest.Builder(FaceDownloadWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(ctx)
                .enqueueUniqueWork("face-download", ExistingWorkPolicy.REPLACE, faceDownload);

        // 4. Heavy face upload runs in background chain
        OneTimeWorkRequest faceSync = new OneTimeWorkRequest.Builder(FaceSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        OneTimeWorkRequest deleteSync = new OneTimeWorkRequest.Builder(DeleteSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(ctx)
                .beginUniqueWork("sync-chain", ExistingWorkPolicy.REPLACE, faceSync)
                .then(deleteSync)
                .enqueue();
    }

    public static void schedulePeriodic(Context ctx) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();

        PeriodicWorkRequest faceDownload = new PeriodicWorkRequest.Builder(FaceDownloadWorker.class, 6, TimeUnit.HOURS)
                .setConstraints(constraints)
                .build();

        WorkManager.getInstance(ctx)
                .enqueueUniquePeriodicWork("face-download-periodic", ExistingPeriodicWorkPolicy.KEEP, faceDownload);
    }
}
