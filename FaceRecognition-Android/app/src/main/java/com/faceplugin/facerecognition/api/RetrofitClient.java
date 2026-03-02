package com.faceplugin.facerecognition.api;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

import android.content.Intent;
import com.faceplugin.facerecognition.MyGlobal;

public class RetrofitClient {
    private static String BASE_URL = "https://postdural-patty-pallial.ngrok-free.dev/";
    
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
        return BASE_URL;
    }

    public static GreetingService getService() {
        if (retrofit == null) {
            OkHttpClient.Builder httpClient = new OkHttpClient.Builder();
            httpClient.addInterceptor(chain -> {
                Request original = chain.request();
                Request.Builder builder = original.newBuilder()
                        .header("ngrok-skip-browser-warning", "1")
                        .header("User-Agent", "openvisionx-android");
                return chain.proceed(builder.build());
            });

            if (authToken != null && !authToken.isEmpty()) {
                httpClient.addInterceptor(chain -> {
                    Request original = chain.request();
                    Request.Builder requestBuilder = original.newBuilder()
                            .header("Authorization", "Bearer " + authToken);
                    Request request = requestBuilder.build();
                    okhttp3.Response response = chain.proceed(request);
                    
                    if (response.code() == 401 || response.code() == 403) {
                         if (MyGlobal.context != null) {
                             Intent intent = new Intent(MyGlobal.ACTION_AUTH_FAILURE);
                             intent.setPackage(MyGlobal.context.getPackageName());
                             MyGlobal.context.sendBroadcast(intent);
                         }
                    }
                    return response;
                });
            } else {
                 // Even without auth token, we might get 401/403 (e.g. login failed, but that's handled by Callback usually)
                 // But for consistency, let's add the response check interceptor always?
                 // No, usually unauth requests expect 401. Only add if we THINK we are auth'd.
                 httpClient.addInterceptor(chain -> {
                    okhttp3.Response response = chain.proceed(chain.request());
                     if (response.code() == 403) { // 403 implies forbidden (subscription end), even if public endpoint?
                         if (MyGlobal.context != null) {
                             Intent intent = new Intent(MyGlobal.ACTION_AUTH_FAILURE);
                             intent.setPackage(MyGlobal.context.getPackageName());
                             MyGlobal.context.sendBroadcast(intent);
                         }
                     }
                    return response;
                 });
            }

            retrofit = new Retrofit.Builder()
                    .baseUrl(BASE_URL)
                    .addConverterFactory(GsonConverterFactory.create())
                    .client(httpClient.build())
                    .build();
        }
        return retrofit.create(GreetingService.class);
    }
}
