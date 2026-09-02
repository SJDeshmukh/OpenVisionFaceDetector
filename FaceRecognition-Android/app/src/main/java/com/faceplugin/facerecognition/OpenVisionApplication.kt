package com.faceplugin.facerecognition

import android.app.Application
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import kotlin.system.exitProcess

class OpenVisionApplication : Application() {

    companion object {
        var instance: OpenVisionApplication? = null
            private set
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        MyGlobal.context = applicationContext

        // FaceSDK is initialized lazily:
        // - MainActivity (kiosk/user role) → IdentifyFragment calls ensureInitialized on first frame
        // - FacultyActivity (faculty role)  → ensureInitialized called in onStart
        // - ParentActivity                  → models never loaded (saves ~50 MB RAM)
        Log.i("OpenVision", "Application started — FaceSDK will init on demand")

        // Register Global Crash Handler
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            handleGlobalCrash(thread, throwable, defaultHandler)
        }
    }

    override fun onLowMemory() {
        super.onLowMemory()
        // The recognition gallery is live application state, not a disposable cache.
        // Android will terminate the process if more memory is required; clearing this
        // list in a live process makes every enrolled person appear as "Unknown".
        Log.w("OpenVision", "Low memory warning received; preserving recognition gallery")
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        Log.i("OpenVision", "onTrimMemory level: $level")
        // Do not recursively remove app cache files or clear DBManager.personList here.
        // Camera/SDK resources are released by their lifecycle owners.
    }

    private fun clearAppCache() {
        try {
            val cacheDir = cacheDir
            if (cacheDir != null && cacheDir.isDirectory) {
                deleteDir(cacheDir)
            }
        } catch (e: Exception) {
            Log.e("OpenVision", "Failed to clear cache", e)
        }
    }

    private fun deleteDir(dir: java.io.File?): Boolean {
        if (dir != null && dir.isDirectory) {
            val children = dir.list()
            if (children != null) {
                for (i in children.indices) {
                    val success = deleteDir(java.io.File(dir, children[i]))
                    if (!success) {
                        return false
                    }
                }
            }
            return dir.delete()
        } else if (dir != null && dir.isFile) {
            return dir.delete()
        }
        return false
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
