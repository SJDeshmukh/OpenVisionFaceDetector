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
            runOnUiThread(() -> tvStatus.setText("Connecting to Cloud Server..."));
            
            // Use saved URL if available, otherwise default to Cloud
            SharedPreferences prefs = getSharedPreferences("app_prefs", MODE_PRIVATE);
            String savedUrl = prefs.getString("server_url", null);
            
            String targetUrl = (savedUrl != null && !savedUrl.isEmpty()) ? savedUrl : RENDER_URL;
            
            RetrofitClient.setBaseUrl(targetUrl);
            if (savedUrl == null) {
                prefs.edit().putString("server_url", RENDER_URL).apply();
            }

            // Ping to ensure server is awake
            // Increased timeout to 30s as requested
            if (pingServer(targetUrl, 30000)) { 
                 runOnUiThread(() -> {
                     tvStatus.setText("Connected to " + (targetUrl.equals(RENDER_URL) ? "Cloud" : "Server"));
                     proceedToNextScreen();
                 });
            } else {
                 runOnUiThread(() -> {
                     tvStatus.setText("Server Unreachable. Check Internet.");
                     // Retry logic or manual retry button could be added here, 
                     // but for now we proceed so the user isn't stuck forever, 
                     // although subsequent calls will likely fail.
                     new Handler().postDelayed(this::proceedToNextScreen, 2000);
                 });
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