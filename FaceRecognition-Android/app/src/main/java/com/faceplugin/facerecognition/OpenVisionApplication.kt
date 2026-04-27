package com.faceplugin.facerecognition

import android.app.Application
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.ocp.facesdk.FaceSDK
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

        // Initialize FaceSDK at application startup — this guarantees it is ready
        // regardless of which Activity the OS launches into (e.g. after login).
        try {
            val ret = FaceSDKWrapper.ensureInitialized(applicationContext)
            if (ret != FaceSDK.SDK_SUCCESS) {
                val errName = when (ret) {
                    FaceSDK.SDK_LICENSE_KEY_ERROR  -> "SDK_LICENSE_KEY_ERROR (-1)"
                    FaceSDK.SDK_LICENSE_APPID_ERROR -> "SDK_LICENSE_APPID_ERROR (-2) — license was issued for a different applicationId; reinstall the correct APK"
                    FaceSDK.SDK_LICENSE_EXPIRED    -> "SDK_LICENSE_EXPIRED (-3)"
                    FaceSDK.SDK_NO_ACTIVATED       -> "SDK_NO_ACTIVATED (-4)"
                    FaceSDK.SDK_INIT_ERROR         -> "SDK_INIT_ERROR (-5)"
                    else -> "UNKNOWN ($ret)"
                }
                Log.e("OpenVision", "FaceSDK init FAILED: $errName")
            } else {
                Log.i("OpenVision", "FaceSDK initialized successfully in Application.onCreate")
            }
        } catch (e: Exception) {
            Log.e("OpenVision", "FaceSDK init exception", e)
        }

        // Register Global Crash Handler
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            handleGlobalCrash(thread, throwable, defaultHandler)
        }
    }

    override fun onLowMemory() {
        super.onLowMemory()
        Log.w("OpenVision", "Low Memory Warning! Clearing cache and person list...")
        clearAppCache()
        
        // Clear static memory-intensive list to prevent OOM
        try {
            synchronized(DBManager.personList) {
                DBManager.personList.clear()
            }
            System.gc() // Suggest GC
        } catch (e: Exception) {}
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        Log.i("OpenVision", "onTrimMemory level: $level")
        if (level >= TRIM_MEMORY_MODERATE) {
            clearAppCache()
            
            // Clear static list to free up significant RAM
            try {
                synchronized(DBManager.personList) {
                    DBManager.personList.clear()
                }
                System.gc()
            } catch (e: Exception) {}
        }
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
