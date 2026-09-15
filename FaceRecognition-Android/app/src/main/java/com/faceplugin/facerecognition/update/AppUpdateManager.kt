package com.faceplugin.facerecognition.update

import android.app.admin.DevicePolicyManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.FileProvider
import com.faceplugin.facerecognition.BuildConfig
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.security.MessageDigest

/**
 * Manages Over-The-Air (OTA) APK updates for the kiosk application.
 *
 * Designed to execute completely in the background without hampering active
 * camera frame processing, ONNX face detection, or attendance logging.
 */
object AppUpdateManager {

    private const val TAG = "AppUpdateManager"
    private val backgroundExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "ota-apk-downloader").apply {
            priority = Thread.MIN_PRIORITY // Run with minimum thread priority so camera/ONNX inference is unaffected
            isDaemon = true
        }
    }
    private val mainHandler = Handler(Looper.getMainLooper())

    private val isDownloading = AtomicBoolean(false)
    private var lastCheckedTs: Long = 0
    private const val CHECK_INTERVAL_MS = 60 * 60 * 1000L // 1 hour between automatic checks

    data class ReleaseInfo(
        val releaseId: Int,
        val versionCode: Int,
        val versionName: String,
        val packageName: String,
        val downloadUrl: String,
        val fileSize: Long,
        val checksumSha256: String,
        val releaseNotes: String,
        val forceUpdate: Boolean
    )

    interface UpdateCallback {
        fun onUpdateAvailable(release: ReleaseInfo) {}
        fun onDownloadProgress(percent: Int) {}
        fun onStatus(release: ReleaseInfo, status: String, progress: Int? = null, error: String? = null) {}
        fun onUpdateReadyToInstall(release: ReleaseInfo, apkFile: File)
        fun onError(error: String) {}
    }

    /**
     * Checks the backend for a newer APK release.
     * If an update is found with versionCode > local versionCode, triggers background download.
     */
    fun checkAndUpdateInBackground(context: Context, quiet: Boolean = true, callback: UpdateCallback? = null) {
        val now = System.currentTimeMillis()
        if (quiet && (now - lastCheckedTs < CHECK_INTERVAL_MS)) {
            Log.d(TAG, "Skipping update check; checked recently")
            return
        }
        lastCheckedTs = now

        backgroundExecutor.execute {
            try {
                val baseUrl = BuildConfig.BASE_URL.trimEnd('/')
                val url = URL("$baseUrl/api/public/app/latest-version")
                val connection = (url.openConnection() as HttpURLConnection).apply {
                    connectTimeout = 10000
                    readTimeout = 15000
                    requestMethod = "GET"
                    setRequestProperty("Accept", "application/json")
                }

                if (connection.responseCode != 200) {
                    Log.w(TAG, "Update check returned HTTP ${connection.responseCode}")
                    if (!quiet) mainHandler.post { callback?.onError("Server returned status ${connection.responseCode}") }
                    return@execute
                }

                val responseStr = connection.inputStream.bufferedReader().use { it.readText() }
                val json = JSONObject(responseStr)

                val hasUpdate = json.optBoolean("has_update", false)
                if (!hasUpdate) {
                    Log.d(TAG, "No update available on server")
                    return@execute
                }

                val serverVersionCode = json.optInt("version_code", 0)
                val currentVersionCode = BuildConfig.VERSION_CODE

                Log.i(TAG, "Server version code: $serverVersionCode, Current app version code: $currentVersionCode")

                if (serverVersionCode > currentVersionCode) {
                    val release = ReleaseInfo(
                        releaseId = json.optInt("release_id", 0),
                        versionCode = serverVersionCode,
                        versionName = json.optString("version_name", ""),
                        packageName = json.optString("package_name", context.packageName),
                        downloadUrl = json.optString("download_url", ""),
                        fileSize = json.optLong("file_size", 0),
                        checksumSha256 = json.optString("checksum_sha256", ""),
                        releaseNotes = json.optString("release_notes", ""),
                        forceUpdate = json.optBoolean("force_update", false)
                    )

                    mainHandler.post { callback?.onUpdateAvailable(release) }
                    mainHandler.post { callback?.onStatus(release, "AVAILABLE") }
                    downloadAndVerifyApk(context.applicationContext, release, callback)
                } else {
                    Log.d(TAG, "App is already up to date (v${BuildConfig.VERSION_NAME})")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error checking for app update", e)
                if (!quiet) mainHandler.post { callback?.onError(e.message ?: "Update check failed") }
            }
        }
    }

    /**
     * Downloads the APK in the background and verifies its integrity.
     */
    private fun downloadAndVerifyApk(context: Context, release: ReleaseInfo, callback: UpdateCallback?) {
        if (!isDownloading.compareAndSet(false, true)) {
            Log.w(TAG, "Download already in progress; skipping duplicate request")
            return
        }

        backgroundExecutor.execute {
            var inputStream: InputStream? = null
            var outputStream: FileOutputStream? = null
            var tempFile: File? = null

            try {
                val updatesDir = File(context.cacheDir, "updates").apply { mkdirs() }
                val apkFile = File(updatesDir, "tapinx_v${release.versionCode}.apk")

                // If already downloaded and valid, don't download again
                if (apkFile.exists() && isApkValid(context, apkFile, release)) {
                    Log.i(TAG, "Valid APK already present in cache: ${apkFile.absolutePath}")
                    isDownloading.set(false)
                    mainHandler.post { callback?.onUpdateReadyToInstall(release, apkFile) }
                    return@execute
                }

                Log.i(TAG, "Starting background download from: ${release.downloadUrl}")
                mainHandler.post { callback?.onStatus(release, "DOWNLOADING", 0) }
                tempFile = File(updatesDir, "download_temp_${System.currentTimeMillis()}.apk")

                val url = URL(release.downloadUrl)
                val conn = (url.openConnection() as HttpURLConnection).apply {
                    connectTimeout = 15000
                    readTimeout = 30000
                    requestMethod = "GET"
                }

                val headerLen = conn.contentLength.toLong()
                val totalBytes: Long = if (headerLen > 0L) headerLen else release.fileSize
                inputStream = conn.inputStream
                outputStream = FileOutputStream(tempFile)

                val buffer = ByteArray(8192)
                var bytesRead: Int
                var totalRead = 0L
                var lastProgressReport = 0

                while (inputStream.read(buffer).also { bytesRead = it } != -1) {
                    outputStream.write(buffer, 0, bytesRead)
                    totalRead += bytesRead

                    if (totalBytes > 0L) {
                        val progress = ((totalRead * 100L) / totalBytes).toInt()
                        if (progress - lastProgressReport >= 5) {
                            lastProgressReport = progress
                            mainHandler.post { callback?.onDownloadProgress(progress) }
                            mainHandler.post { callback?.onStatus(release, "DOWNLOADING", progress) }
                        }
                    }

                    // Yield CPU briefly to ensure the camera thread always takes priority
                    Thread.sleep(1)
                }

                outputStream.flush()
                outputStream.close()
                outputStream = null

                // Verify file integrity before renaming
                if (!isApkValid(context, tempFile, release)) {
                    throw IllegalStateException("Downloaded APK verification failed or package corrupted")
                }

                // Rename temp file to destination APK
                if (apkFile.exists()) apkFile.delete()
                if (!tempFile.renameTo(apkFile)) {
                    throw IllegalStateException("Failed to move downloaded file to target APK path")
                }

                Log.i(TAG, "APK successfully downloaded and verified: ${apkFile.absolutePath} (${apkFile.length()} bytes)")
                mainHandler.post {
                    callback?.onDownloadProgress(100)
                    callback?.onStatus(release, "DOWNLOADED", 100)
                    callback?.onUpdateReadyToInstall(release, apkFile)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to download APK update", e)
                tempFile?.delete()
                mainHandler.post { callback?.onStatus(release, "FAILED", error = e.message) }
                mainHandler.post { callback?.onError(e.message ?: "APK download failed") }
            } finally {
                try { inputStream?.close() } catch (_: Exception) {}
                try { outputStream?.close() } catch (_: Exception) {}
                isDownloading.set(false)
            }
        }
    }

    /**
     * Validates that the file is an intact Android package with a valid signature and expected versionCode.
     */
    private fun isApkValid(context: Context, file: File, release: ReleaseInfo): Boolean {
        if (!file.exists() || file.length() < 1024) return false
        return try {
            if (release.checksumSha256.isBlank()) {
                Log.e(TAG, "Release is missing the required SHA-256 checksum")
                return false
            }
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(8192)
                var count: Int
                while (input.read(buffer).also { count = it } != -1) {
                    digest.update(buffer, 0, count)
                }
            }
            val actualChecksum = digest.digest().joinToString("") { "%02x".format(it) }
            if (!actualChecksum.equals(release.checksumSha256, ignoreCase = true)) {
                Log.e(TAG, "APK checksum mismatch")
                return false
            }
            val pm = context.packageManager
            val info = pm.getPackageArchiveInfo(file.absolutePath, PackageManager.GET_ACTIVITIES)
            if (info == null) {
                Log.e(TAG, "PackageManager could not parse package archive")
                return false
            }

            val archiveVersion = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                info.longVersionCode.toInt()
            } else {
                @Suppress("DEPRECATION")
                info.versionCode
            }

            val expectedPackage = release.packageName.ifBlank { context.packageName }
            val valid = info.packageName == context.packageName &&
                info.packageName == expectedPackage &&
                archiveVersion == release.versionCode &&
                archiveVersion > com.faceplugin.facerecognition.BuildConfig.VERSION_CODE
            Log.d(TAG, "Parsed archive pkg: ${info.packageName}, version: $archiveVersion, valid=$valid")
            valid
        } catch (e: Exception) {
            Log.e(TAG, "Error validating APK archive", e)
            false
        }
    }

    /**
     * Launches the installation of the downloaded APK.
     *
     * If the app is a Device Owner (Kiosk Lockdown mode), it uses Android's PackageInstaller
     * session API for a silent installation.
     *
     * Otherwise, it uses Android's FileProvider to trigger the standard system package installer.
     */
    fun installApk(context: Context, apkFile: File) {
        if (!apkFile.exists()) {
            Log.e(TAG, "Cannot install; APK file does not exist: ${apkFile.absolutePath}")
            return
        }

        try {
            if (context is android.app.Activity) {
                try {
                    context.stopLockTask()
                } catch (_: Exception) {}
            }
            val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as? DevicePolicyManager
            val isDeviceOwner = dpm?.isDeviceOwnerApp(context.packageName) == true

            // On Android 12+ (API 31+) or if Device Owner, we can use PackageInstaller with USER_ACTION_NOT_REQUIRED
            // for completely silent background self-updates!
            if (isDeviceOwner || Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                try {
                    Log.i(TAG, "Installing via PackageInstaller session (isDeviceOwner=$isDeviceOwner, sdk=${Build.VERSION.SDK_INT})...")
                    installViaPackageInstaller(context, apkFile)
                    return
                } catch (e: Exception) {
                    Log.w(TAG, "PackageInstaller session failed; falling back to system intent", e)
                }
            }

            Log.i(TAG, "Launching system package installer via FileProvider...")
            launchSystemInstallIntent(context, apkFile)
        } catch (e: Exception) {
            Log.e(TAG, "Error initiating APK installation; falling back to intent", e)
            launchSystemInstallIntent(context, apkFile)
        }
    }

    private fun launchSystemInstallIntent(context: Context, apkFile: File) {
        if (context is android.app.Activity) {
            try {
                context.stopLockTask()
            } catch (_: Exception) {}
        }
        val authority = "${context.packageName}.provider"
        val contentUri: Uri = FileProvider.getUriForFile(context, authority, apkFile)

        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(contentUri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun installViaPackageInstaller(context: Context, apkFile: File) {
        val packageInstaller = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(context.packageName)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            }
        }
        val sessionId = packageInstaller.createSession(params)
        val session = packageInstaller.openSession(sessionId)

        apkFile.inputStream().use { input ->
            session.openWrite("package_update", 0, apkFile.length()).use { output ->
                input.copyTo(output)
                session.fsync(output)
            }
        }

        // Commit installation session with broadcast to AppUpdateReceiver
        val intent = Intent(context, AppUpdateReceiver::class.java).apply {
            action = "com.faceplugin.facerecognition.action.PACKAGE_INSTALL_STATUS"
        }
        val pendingIntent = android.app.PendingIntent.getBroadcast(
            context,
            sessionId,
            intent,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                android.app.PendingIntent.FLAG_MUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT
            } else {
                android.app.PendingIntent.FLAG_UPDATE_CURRENT
            }
        )

        session.commit(pendingIntent.intentSender)
        session.close()
        Log.i(TAG, "PackageInstaller session $sessionId committed successfully")
    }

    /**
     * Clears cached APK files after successful update or cleanup.
     */
    fun clearDownloadedApks(context: Context) {
        try {
            val updatesDir = File(context.cacheDir, "updates")
            if (updatesDir.exists() && updatesDir.isDirectory) {
                updatesDir.listFiles()?.forEach { it.delete() }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to clear update cache", e)
        }
    }
}
