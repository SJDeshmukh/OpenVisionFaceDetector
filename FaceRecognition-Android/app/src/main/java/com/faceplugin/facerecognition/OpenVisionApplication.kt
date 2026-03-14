package com.faceplugin.facerecognition

import android.app.Application
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import kotlin.system.exitProcess

class OpenVisionApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        
        // Register Global Crash Handler
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            handleGlobalCrash(thread, throwable, defaultHandler)
        }
    }

    private fun handleGlobalCrash(thread: Thread, throwable: Throwable, defaultHandler: Thread.UncaughtExceptionHandler?) {
        try {
            Log.e("OpenVisionCrash", "FATAL EXCEPTION in thread ${thread.name}", throwable)
            
            // Log to local file if needed for later retrieval
            // For now, focus on graceful recovery
            
            Handler(Looper.getMainLooper()).post {
                // If we are on the main thread and catch a crash, we try to restart
                try {
                    val intent = Intent(applicationContext, SplashActivity::class.java)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                    intent.putExtra("crash_recovery", true)
                    applicationContext.startActivity(intent)
                } catch (e: Exception) {
                    Log.e("OpenVisionCrash", "Restart failed", e)
                }
            }

            // Sleep a bit to allow the intent to start (Android handles this better)
            Thread.sleep(1500)
            
            // Finally, let the default handler take over or exit
            // We exit process to ensure a clean state upon restart
            exitProcess(2)
            
        } catch (e: Exception) {
            // If our crash handler crashes, let the system take over
            defaultHandler?.uncaughtException(thread, throwable)
        }
    }
}
