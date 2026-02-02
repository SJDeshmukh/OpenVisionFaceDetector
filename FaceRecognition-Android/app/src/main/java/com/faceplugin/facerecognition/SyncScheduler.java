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

        OneTimeWorkRequest faceSync = new OneTimeWorkRequest.Builder(FaceSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        OneTimeWorkRequest attendanceSync = new OneTimeWorkRequest.Builder(AttendanceSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        OneTimeWorkRequest deleteSync = new OneTimeWorkRequest.Builder(DeleteSyncWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        OneTimeWorkRequest faceDownload = new OneTimeWorkRequest.Builder(FaceDownloadWorker.class)
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .build();

        WorkManager.getInstance(ctx)
                .beginUniqueWork("sync-chain", ExistingWorkPolicy.KEEP, faceSync)
                .then(attendanceSync)
                .then(deleteSync)
                .then(faceDownload)
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
