package com.faceplugin.facerecognition.api;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class RetrofitClient {
    // Default to Render Cloud URL
    private static String BASE_URL = "https://face-detection-backend-69o7.onrender.com/";
    
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

            if (authToken != null && !authToken.isEmpty()) {
                httpClient.addInterceptor(chain -> {
                    Request original = chain.request();
                    Request.Builder requestBuilder = original.newBuilder()
                            .header("Authorization", "Bearer " + authToken);
                    Request request = requestBuilder.build();
                    return chain.proceed(request);
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
