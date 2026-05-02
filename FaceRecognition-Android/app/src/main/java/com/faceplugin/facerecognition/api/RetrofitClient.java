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
    private static String BASE_URL = BuildConfig.BASE_URL;
    
    private static Retrofit retrofit = null;
    private static String authToken = null;

    public static void setBaseUrl(String url) {
        if (url != null && !url.isEmpty()) {
            if (!url.endsWith("/")) {
                url += "/";
            }
            BASE_URL = url;
            retrofit = null; // Reset retrofit to force rebuild with new URL
        }
    }

    public static void setAuthToken(String token) {
        authToken = token;
        retrofit = null; // Reset to rebuild with new token
    }

    public static String getBaseUrl() {
        if (BASE_URL == null || BASE_URL.isEmpty()) {
            BASE_URL = BuildConfig.BASE_URL;
        }
        return BASE_URL;
    }

    public static GreetingService getService() {
        if (retrofit == null) {
            // Try to recover token from SharedPreferences if null (e.g. process death)
            if (authToken == null && MyGlobal.context != null) {
                try {
                    android.content.SharedPreferences prefs = MyGlobal.context.getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE);
                    authToken = prefs.getString("token", null);
                } catch (Exception ignored) {}
            }

            OkHttpClient.Builder httpClient = new OkHttpClient.Builder()
                    .connectTimeout(30, TimeUnit.SECONDS)
                    .readTimeout(120, TimeUnit.SECONDS)   // face detection can take 15-30s
                    .writeTimeout(60, TimeUnit.SECONDS);  // large base64 image uploads

            // Global Headers
            httpClient.addInterceptor(chain -> {
                Request original = chain.request();
                Request.Builder builder = original.newBuilder()
                        .header("User-Agent", "openvisionx-android")
                        .header("X-App-Brand", BuildConfig.IS_ATTENDX ? "AttendX" : "TapInX");
                
                // Always add Authorization if token is available
                if (authToken != null && !authToken.isEmpty()) {
                    builder.header("Authorization", "Bearer " + authToken);
                }
                
                okhttp3.Response response = chain.proceed(builder.build());
                
                // Track Auth Failures (401=Unauthorized, 403=Forbidden/Limit Reached/Suspended)
                if (response.code() == 401 || response.code() == 403) {
                     if (MyGlobal.context != null) {
                         String errorMessage = null;
                         try {
                             // Peaking into the response body without consuming it
                             okhttp3.ResponseBody body = response.peekBody(2048); 
                             String bodyStr = body.string();
                             JSONObject json = new JSONObject(bodyStr);
                             if (json.has("error")) {
                                 errorMessage = json.getString("error");
                             }
                         } catch (Exception ignored) {}

                         Intent intent = new Intent(MyGlobal.ACTION_AUTH_FAILURE);
                         intent.setPackage(MyGlobal.context.getPackageName());
                         if (errorMessage != null && !errorMessage.isEmpty()) {
                             intent.putExtra("message", errorMessage);
                         }
                         MyGlobal.context.sendBroadcast(intent);
                     }
                }
                return response;
            });

            retrofit = new Retrofit.Builder()
                    .baseUrl(BASE_URL)
                    .addConverterFactory(GsonConverterFactory.create())
                    .client(httpClient.build())
                    .build();
        }
        return retrofit.create(GreetingService.class);
    }
}
