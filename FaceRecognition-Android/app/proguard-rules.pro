# ============================================================================
# TapInX / OpenVision ProGuard / R8 Obfuscation & Shrinking Rules
# ============================================================================

# Preserve line numbers and source file names for crash reporting
-keepattributes SourceFile,LineNumberTable
-keepattributes *Annotation*
-keepattributes Signature
-keepattributes InnerClasses,EnclosingMethod

# --- AndroidX & Google Components ---
-keep class androidx.appcompat.** { *; }
-keep class com.google.android.material.** { *; }
-keep class androidx.camera.** { *; }
-dontwarn androidx.camera.**

# --- Retrofit 2 & OkHttp 3 ---
-dontwarn retrofit2.**
-keep class retrofit2.** { *; }
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }

# --- Gson & Serialized API Models ---
# Models must keep field names matching JSON keys
-keepclassmembers class * {
    @com.google.gson.annotations.SerializedName <fields>;
}
-keep class com.faceplugin.facerecognition.api.** { *; }
-keep class com.google.gson.** { *; }
-dontwarn com.google.gson.**

# --- ONNX Runtime & Native ML Libs ---
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**
-keepclasseswithmembernames class * {
    native <methods>;
}

# --- Socket.IO & WebSockets ---
-keep class io.socket.** { *; }
-keep class io.socket.client.** { *; }
-keep class io.socket.engineio.client.** { *; }
-dontwarn io.socket.**

# --- Stream WebRTC ---
-keep class io.getstream.webrtc.** { *; }
-keep class org.webrtc.** { *; }
-dontwarn org.webrtc.**
-dontwarn io.getstream.webrtc.**

# --- MPAndroidChart ---
-keep class com.github.mikephil.charting.** { *; }
-dontwarn com.github.mikephil.charting.**

# --- Kotlin Coroutines ---
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory { *; }
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler { *; }
-dontwarn kotlinx.coroutines.**

# --- Transition Button & SpinKit ---
-keep class com.royrodriguez.transitionbutton.** { *; }
-keep class com.github.ybq.android.spinkit.** { *; }

# --- WorkManager ---
-keep class androidx.work.** { *; }

# --- Firebase Messaging & Play Services ---
-keep class com.google.firebase.** { *; }
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.firebase.**
-dontwarn com.google.android.gms.**
