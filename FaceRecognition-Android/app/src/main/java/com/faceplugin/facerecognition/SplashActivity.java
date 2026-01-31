package com.faceplugin.facerecognition;

import androidx.appcompat.app.AppCompatActivity;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.Intent;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.Handler;
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

    private static final String LOCAL_URL = "http://192.168.1.102:5001/";
    private static final String RENDER_URL = "https://face-detection-backend-69o7.onrender.com/";

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
            String targetUrl = LOCAL_URL;

            RetrofitClient.setBaseUrl(targetUrl);
            prefs.edit().putString("server_url", targetUrl).apply();

            boolean online = false;
            try {
                online = NetworkUtils.INSTANCE.isOnline(getApplicationContext());
            } catch (Exception ignored) {}

            if (!online) {
                runOnUiThread(() -> tvStatus.setText("Offline Mode"));
                new Handler().postDelayed(this::proceedToNextScreen, 800);
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
                new Handler().postDelayed(this::proceedToNextScreen, 1200);
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
            int code = connection.getResponseCode();
            connection.disconnect();
            return code == 200;
        } catch (IOException e) {
            return false;
        }
    }

    private void proceedToNextScreen() {
        SharedPreferences prefs = getSharedPreferences("app_prefs", MODE_PRIVATE);
        String role = prefs.getString("role", null);
        String token = prefs.getString("token", null);

        if (token != null) {
            RetrofitClient.setAuthToken(token);
        }

        Intent intent;
        if (role != null) {
            intent = new Intent(SplashActivity.this, MainActivity.class);
        } else {
            intent = new Intent(SplashActivity.this, LoginActivity.class);
        }
        startActivity(intent);
        finish();
    }
}
