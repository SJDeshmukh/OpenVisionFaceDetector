package com.faceplugin.facerecognition.update

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.faceplugin.facerecognition.SplashActivity

/**
 * BroadcastReceiver triggered automatically by Android OS when this application
 * package has been updated (ACTION_MY_PACKAGE_REPLACED).
 *
 * Relaunches SplashActivity immediately so the kiosk returns to the face recognition
 * attendance screen without requiring anyone to physically touch the device.
 */
class AppUpdateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Intent.ACTION_MY_PACKAGE_REPLACED == intent.action) {
            Log.i("AppUpdateReceiver", "App package replaced! Automatically relaunching kiosk...")
            try {
                // Clear any leftover update APK cache
                AppUpdateManager.clearDownloadedApks(context)

                // Launch main splash activity
                val launchIntent = Intent(context, SplashActivity::class.java).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                }
                context.startActivity(launchIntent)
            } catch (e: Exception) {
                Log.e("AppUpdateReceiver", "Failed to relaunch app after update", e)
            }
        }
    }
}
