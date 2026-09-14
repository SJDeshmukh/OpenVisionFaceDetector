package com.faceplugin.facerecognition.update

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.content.pm.PackageInstaller
import android.os.Build
import com.faceplugin.facerecognition.SplashActivity

/**
 * BroadcastReceiver triggered automatically by Android OS when this application
 * package has been updated (ACTION_MY_PACKAGE_REPLACED), or when a PackageInstaller
 * session reports progress/status.
 *
 * Relaunches SplashActivity immediately so the kiosk returns to the face recognition
 * attendance screen without requiring anyone to physically touch the device.
 */
class AppUpdateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        Log.i("AppUpdateReceiver", "Received intent action: $action")

        // 1. Handled when app package has been successfully updated on the OS
        if (Intent.ACTION_MY_PACKAGE_REPLACED == action) {
            Log.i("AppUpdateReceiver", "App package replaced! Automatically relaunching kiosk...")
            try {
                AppUpdateManager.clearDownloadedApks(context)
                val launchIntent = Intent(context, SplashActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                }
                context.startActivity(launchIntent)
            } catch (e: Exception) {
                Log.e("AppUpdateReceiver", "Failed to relaunch app after update", e)
            }
            return
        }

        // 2. Handled from PackageInstaller session status callback
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -999)
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                Log.i("AppUpdateReceiver", "PackageInstaller requires user action; displaying system dialog")
                val confirmIntent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(Intent.EXTRA_INTENT)
                }
                confirmIntent?.let {
                    it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(it)
                }
            }
            PackageInstaller.STATUS_SUCCESS -> {
                Log.i("AppUpdateReceiver", "PackageInstaller session finished with STATUS_SUCCESS")
            }
            else -> {
                if (status != -999) {
                    val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
                    Log.w("AppUpdateReceiver", "PackageInstaller status=$status, msg=$msg")
                }
            }
        }
    }
}
