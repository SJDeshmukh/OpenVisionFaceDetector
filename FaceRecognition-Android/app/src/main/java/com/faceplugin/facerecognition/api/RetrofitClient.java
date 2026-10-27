package com.faceplugin.facerecognition.api;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;
import java.util.concurrent.TimeUnit;

import android.content.Intent;
import android.util.Base64;
import com.faceplugin.facerecognition.MyGlobal;
import com.faceplugin.facerecognition.BuildConfig;
import org.json.JSONObject;

public class RetrofitClient {
    private static volatile String BASE_URL = BuildConfig.BASE_URL;
    
    private static volatile Retrofit retrofit = null;
    private static volatile Retrofit attendanceRetrofit = null;
    private static volatile String authToken = null;

    public static synchronized void setBaseUrl(String url) {
        if (url != null && !url.isEmpty()) {
            if (!url.endsWith("/")) {
                url += "/";
            }
            BASE_URL = url;
            retrofit = null; // Reset retrofit to force rebuild with new URL
            attendanceRetrofit = null;
        }
    }

    public static synchronized void setAuthToken(String token) {
        authToken = token;
    }

    public static synchronized String getBaseUrl() {
        if (BASE_URL == null || BASE_URL.isEmpty()) {
            BASE_URL = BuildConfig.BASE_URL;
        }
        return BASE_URL;
    }

    public static synchronized GreetingService getService() {
        if (retrofit == null) {
            // Try to recover token from SharedPreferences if null (e.g. process death)
            if (authToken == null && MyGlobal.context != null) {
                try {
                    android.content.SharedPreferences prefs = MyGlobal.context.getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE);
                    authToken = prefs.getString("token", null);
                } catch (Exception ignored) {}
            }

            OkHttpClient httpClient = buildHttpClient(10, 30, 30);

            retrofit = new Retrofit.Builder()
                    .baseUrl(BASE_URL)
                    .addConverterFactory(GsonConverterFactory.create())
                    .client(httpClient)
                    .build();
        }
        return retrofit.create(GreetingService.class);
    }

    /** Attendance gets a short, isolated timeout so face uploads cannot delay durable fallback. */
    public static synchronized GreetingService getAttendanceService() {
        if (attendanceRetrofit == null) {
            attendanceRetrofit = new Retrofit.Builder()
                    .baseUrl(getBaseUrl())
                    .addConverterFactory(GsonConverterFactory.create())
                    .client(buildHttpClient(10, 20, 20))
                    .build();
        }
        return attendanceRetrofit.create(GreetingService.class);
    }

    /** Short-timeout client for interactive control calls such as attendance and deletion. */
    public static GreetingService getInteractiveService() {
        return getAttendanceService();
    }

    private static OkHttpClient buildHttpClient(long connectSeconds, long readSeconds, long writeSeconds) {
        OkHttpClient.Builder httpClient = new OkHttpClient.Builder()
                .connectTimeout(connectSeconds, TimeUnit.SECONDS)
                .readTimeout(readSeconds, TimeUnit.SECONDS)
                .writeTimeout(writeSeconds, TimeUnit.SECONDS);

        httpClient.addInterceptor(chain -> {
            Request original = chain.request();
            Request.Builder builder = original.newBuilder()
                    .header("User-Agent", "openvisionx-android")
                    .header("X-App-Brand", BuildConfig.IS_ATTENDX ? "AttendX" : "TapInX");
            if (authToken != null && !authToken.isEmpty()) {
                builder.header("Authorization", "Bearer " + authToken);
            }

            okhttp3.Response response = chain.proceed(builder.build());
            if (response.code() == 401 && authToken != null && !authToken.isEmpty()) {
                authToken = null;
                if (MyGlobal.context != null) {
                    String errorMessage = null;
                    try {
                        okhttp3.ResponseBody body = response.peekBody(2048);
                        JSONObject json = new JSONObject(body.string());
                        if (json.has("error")) errorMessage = json.getString("error");
                    } catch (Exception ignored) {}

                    Intent intent = new Intent(MyGlobal.ACTION_AUTH_FAILURE);
                    intent.setPackage(MyGlobal.context.getPackageName());
                    if (errorMessage != null && !errorMessage.isEmpty()) intent.putExtra("message", errorMessage);
                    MyGlobal.context.sendBroadcast(intent);
                }
            }
            return response;
        });
        return httpClient.build();
    }
}
