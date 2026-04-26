package com.faceplugin.facerecognition

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = context.getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val token = prefs.getString("token", null)
        val role  = prefs.getString("role", null)
        // Only restart listener if a parent is logged in
        if (!token.isNullOrBlank() && role == "parent") {
            AttendanceListenerService.start(context)
        }
    }
}
