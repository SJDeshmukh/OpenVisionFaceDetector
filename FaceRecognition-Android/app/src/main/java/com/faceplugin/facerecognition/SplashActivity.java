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
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;

public class SplashActivity extends AppCompatActivity {

    private TextView tvStatus;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private static final String LOCAL_URL = "https://postdural-patty-pallial.ngrok-free.dev/";
    private static final String RENDER_URL = "https://face-detection-backend-69o7.onrender.com/";
    private static final String LEGACY_LOCAL_URL = "http://192.0.0.2:5001/";

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
            if (LEGACY_LOCAL_URL.equals(targetUrl)) {
                targetUrl = RetrofitClient.getBaseUrl();
                prefs.edit().putString("server_url", targetUrl).apply();
            }
            try {
                if (targetUrl != null && targetUrl.contains("ngrok-free.dev")) {
                    targetUrl = RetrofitClient.getBaseUrl();
                    prefs.edit().putString("server_url", targetUrl).apply();
                }
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
                runOnUiThread(() -> tvStatus.setText("Server Unreachable"));
                mainHandler.postDelayed(this::proceedToNextScreen, 1200);
            }
        }).start();
    }

    private boolean pingServer(String baseUrl, int timeout) {
        try {
            // Use api/config as it's a valid endpoint (api/ping does not exist)
            URL url = new URL(baseUrl + "api/config");
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(timeout);
            connection.setReadTimeout(timeout);
            connection.setRequestMethod("GET");
            connection.setRequestProperty("ngrok-skip-browser-warning", "1");
            connection.setRequestProperty("User-Agent", "openvisionx-android");
            int code = connection.getResponseCode();
            connection.disconnect();
            return code == 200;
        } catch (IOException e) {
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
                intent = new Intent(SplashActivity.this, ParentActivity.class);
            } else {
                intent = new Intent(SplashActivity.this, MainActivity.class);
            }
        } else {
            intent = new Intent(SplashActivity.this, LoginActivity.class);
        }
        startActivity(intent);
        finish();
    }
}
