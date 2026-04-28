package com.faceplugin.facerecognition;

import androidx.appcompat.app.AppCompatActivity;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.Intent;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.animation.Animation;
import android.view.animation.AnimationUtils;
import android.widget.ImageView;
import android.widget.TextView;
import com.faceplugin.facerecognition.api.RetrofitClient;
import com.ocp.facesdk.FaceSDK;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;

public class SplashActivity extends AppCompatActivity {

    private TextView tvStatus;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private static final String LOCAL_URL = BuildConfig.BASE_URL;
    private static final String RENDER_URL = BuildConfig.BASE_URL;
    private static final String LEGACY_LOCAL_URL = "http://192.0.0.2:5001/";
    private static final String LEGACY_LOCAL_URL_2 = "http://192.168.1.2:5001/";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_splash);

        // Apply pulse animation to logo
        ImageView logo = findViewById(R.id.logo_splash);
        Animation pulse = AnimationUtils.loadAnimation(this, R.anim.pulse);
        logo.startAnimation(pulse);

        MyGlobal.context = getApplicationContext();
        tvStatus = findViewById(R.id.tvStatus);

        // FaceSDK only needed for TapInX kiosk mode; AttendX uses server-side detection
        if (!BuildConfig.IS_ATTENDX) {
            int ret = FaceSDKWrapper.INSTANCE.ensureInitialized(getApplicationContext());
            if (ret != FaceSDK.SDK_SUCCESS) {
                String msg = "SDK Init Failed";
                if (ret == FaceSDK.SDK_LICENSE_KEY_ERROR)    msg = "Invalid license!";
                else if (ret == FaceSDK.SDK_LICENSE_APPID_ERROR) msg = "Invalid error!";
                else if (ret == FaceSDK.SDK_LICENSE_EXPIRED) msg = "License expired!";
                else if (ret == FaceSDK.SDK_NO_ACTIVATED)    msg = "No activated!";
                else if (ret == FaceSDK.SDK_INIT_ERROR)      msg = "Init error!";
                android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_LONG).show();
            }
        }

        // Start Connection Process
        connectToBackend();
    }

    private void connectToBackend() {
        new Thread(() -> {
            runOnUiThread(() -> tvStatus.setText("Connecting..."));

            SharedPreferences prefs = getSharedPreferences("app_prefs", MODE_PRIVATE);
            String targetUrl = prefs.getString("server_url", null);
            if (targetUrl == null || targetUrl.isEmpty()) {
                targetUrl = RetrofitClient.getBaseUrl();
                prefs.edit().putString("server_url", targetUrl).apply();
            }
            if (LEGACY_LOCAL_URL.equals(targetUrl) || LEGACY_LOCAL_URL_2.equals(targetUrl) || BuildConfig.REMOTE_BASE_URL.equals(targetUrl)) {
                targetUrl = BuildConfig.BASE_URL;
                prefs.edit().putString("server_url", targetUrl).apply();
            }
            try {
                // No special-case for ngrok; use the configured base URL directly
            } catch (Exception ignored) {}

            RetrofitClient.setBaseUrl(targetUrl);
            try {
                String token = prefs.getString("token", null);
                RetrofitClient.setAuthToken(token);
            } catch (Exception ignored) {}

            boolean online = false;
            try {
                online = NetworkUtils.INSTANCE.isOnline(getApplicationContext());
            } catch (Exception ignored) {}

            if (!online) {
                runOnUiThread(() -> tvStatus.setText("Offline Mode"));
                mainHandler.postDelayed(this::proceedToNextScreen, 800);
                return;
            }

            runOnUiThread(() -> tvStatus.setText("Connecting to Server..."));
            if (pingServer(targetUrl, 15000)) {
                runOnUiThread(() -> {
                    tvStatus.setText("Connected");
                    proceedToNextScreen();
                });
            } else {
                // Fallback logic
                String remoteUrl = BuildConfig.REMOTE_BASE_URL;
                if (!targetUrl.equals(remoteUrl)) {
                    final String originalUrl = targetUrl;
                    runOnUiThread(() -> tvStatus.setText("Local offline, trying Remote..."));
                    RetrofitClient.setBaseUrl(remoteUrl);
                    if (pingServer(remoteUrl, 15000)) {
                        prefs.edit().putString("server_url", remoteUrl).apply();
                        runOnUiThread(() -> {
                            tvStatus.setText("Connected to Remote");
                            proceedToNextScreen();
                        });
                        return;
                    } else {
                        // Restore original if even remote fails
                        RetrofitClient.setBaseUrl(originalUrl);
                    }
                }
                
                runOnUiThread(() -> tvStatus.setText("Server Unreachable"));
                mainHandler.postDelayed(this::proceedToNextScreen, 1200);
            }
        }).start();
    }

    private boolean pingServer(String baseUrl, int timeout) {
        try {
            com.faceplugin.facerecognition.api.GreetingService svc = com.faceplugin.facerecognition.api.RetrofitClient.getService();
            retrofit2.Response<com.google.gson.JsonObject> resp = svc.getConfig().execute();
            int code = resp.code();
            return code >= 200 && code < 400 && resp.body() != null;
        } catch (Exception e) {
            final String err = e.getMessage();
            runOnUiThread(() -> android.widget.Toast.makeText(SplashActivity.this, "Ping to " + baseUrl + " failed: " + err, android.widget.Toast.LENGTH_LONG).show());
            return false;
        }
    }

    private void proceedToNextScreen() {
        SharedPreferences prefs = getSharedPreferences("app_prefs", MODE_PRIVATE);
        String selectedCode = prefs.getString("selected_business_type_code", null);
        if (selectedCode == null || selectedCode.isEmpty()) {
            selectedCode = prefs.getString("selected_business_type", null);
            if (selectedCode != null && !selectedCode.isEmpty()) {
                prefs.edit().putString("selected_business_type_code", selectedCode).apply();
            }
        }
        if (selectedCode == null || selectedCode.isEmpty()) {
            String legacyVertical = prefs.getString("selected_vendor_vertical", null);
            if (legacyVertical != null && !legacyVertical.isEmpty()) {
                prefs.edit()
                        .putString("selected_business_type_code", legacyVertical)
                        .putString("selected_business_type", legacyVertical)
                        .apply();
                selectedCode = legacyVertical;
            }
        }
        if (selectedCode == null || selectedCode.isEmpty()) {
            Intent intent = new Intent(SplashActivity.this, BusinessSelectActivity.class);
            startActivity(intent);
            finish();
            return;
        }
        String token = prefs.getString("token", null);

        if (token != null) {
            RetrofitClient.setAuthToken(token);
        }

        Intent intent;
        if (token != null) {
            String role = prefs.getString("role", null);
            if ("parent".equals(role)) {
                if (prefs.getBoolean("face_registered", false)) {
                    intent = new Intent(SplashActivity.this, ParentActivity.class);
                } else {
                    intent = new Intent(SplashActivity.this, ParentFaceRegistrationActivity.class);
                }
            } else if ("faculty".equals(role)) {
                intent = new Intent(SplashActivity.this, FacultyActivity.class);
            } else {
                // owner / vendor_admin / user → kiosk screen
                intent = new Intent(SplashActivity.this, MainActivity.class);
            }
        } else {
            intent = new Intent(SplashActivity.this, LoginActivity.class);
        }
        startActivity(intent);
        finish();
    }
}
