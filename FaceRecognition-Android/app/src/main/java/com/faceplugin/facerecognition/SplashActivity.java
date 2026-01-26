package com.faceplugin.facerecognition;

import androidx.appcompat.app.AppCompatActivity;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.Handler;
import android.text.format.Formatter;
import android.util.Log;
import android.view.animation.Animation;
import android.view.animation.AnimationUtils;
import android.widget.ImageView;
import android.widget.TextView;
import com.faceplugin.facerecognition.api.RetrofitClient;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public class SplashActivity extends AppCompatActivity {

    private TextView tvStatus;
    private AtomicBoolean isServerFound = new AtomicBoolean(false);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_splash);

        // Apply pulse animation to logo
        ImageView logo = findViewById(R.id.logo_splash);
        Animation pulse = AnimationUtils.loadAnimation(this, R.anim.pulse);
        logo.startAnimation(pulse);

        tvStatus = findViewById(R.id.tvStatus);

        // Check for saved server URL first
        SharedPreferences prefs = getSharedPreferences("app_prefs", MODE_PRIVATE);
        String savedUrl = prefs.getString("server_url", null);
        String RENDER_URL = "https://face-detection-backend-69o7.onrender.com/";

        tvStatus.setText("Connecting to Server...");

        new Thread(() -> {
            // Priority 1: Check Saved URL (if exists)
            boolean savedConnected = false;
            if (savedUrl != null && !savedUrl.isEmpty()) {
                runOnUiThread(() -> tvStatus.setText("Connecting to saved server..."));
                if (pingServer(savedUrl, 2000)) {
                    savedConnected = true;
                    runOnUiThread(() -> {
                        tvStatus.setText("Connected to Server");
                        RetrofitClient.setBaseUrl(savedUrl);
                        proceedToNextScreen();
                    });
                }
            }

            if (!savedConnected) {
                // Priority 2: Check Cloud URL
                runOnUiThread(() -> tvStatus.setText("Connecting to cloud server..."));
                if (pingServer(RENDER_URL, 5000)) {
                    runOnUiThread(() -> {
                        tvStatus.setText("Connected to Cloud Server");
                        RetrofitClient.setBaseUrl(RENDER_URL);
                        proceedToNextScreen();
                    });
                } else {
                    // Priority 3: Scan Local Network
                    runOnUiThread(() -> startNetworkScan());
                }
            }
        }).start();
    }

    private void startNetworkScan() {
        runOnUiThread(() -> tvStatus.setText("Searching for local server..."));
        
        new Thread(() -> {
            WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            String ip = Formatter.formatIpAddress(wm.getConnectionInfo().getIpAddress());
            String prefix = ip.substring(0, ip.lastIndexOf(".") + 1);

            ExecutorService executor = Executors.newFixedThreadPool(20);
            
            for (int i = 1; i < 255; i++) {
                if (isServerFound.get()) break;
                final String testIp = prefix + i;
                executor.execute(() -> {
                    if (isServerFound.get()) return;
                    String url = "http://" + testIp + ":5001/";
                    if (pingServer(url, 1000)) {
                        if (!isServerFound.getAndSet(true)) {
                            Log.d("SplashActivity", "Server found: " + url);
                            runOnUiThread(() -> {
                                tvStatus.setText("Server found: " + testIp);
                                RetrofitClient.setBaseUrl(url);
                                
                                // Save to prefs
                                SharedPreferences prefs = getSharedPreferences("app_prefs", MODE_PRIVATE);
                                prefs.edit().putString("server_url", url).apply();
                                
                                proceedToNextScreen();
                            });
                        }
                    }
                });
            }
            
            executor.shutdown();
            try {
                executor.awaitTermination(10, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                e.printStackTrace();
            }

            if (!isServerFound.get()) {
                runOnUiThread(() -> {
                    tvStatus.setText("Server not found. Using default.");
                    // Use default hardcoded in RetrofitClient
                    new Handler().postDelayed(this::proceedToNextScreen, 1000);
                });
            }
        }).start();
    }

    private boolean pingServer(String baseUrl, int timeout) {
        try {
            URL url = new URL(baseUrl + "api/ping");
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