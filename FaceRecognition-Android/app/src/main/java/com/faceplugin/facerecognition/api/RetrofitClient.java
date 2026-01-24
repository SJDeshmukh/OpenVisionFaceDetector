package com.faceplugin.facerecognition.api;

import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class RetrofitClient {
    // Default to Render Cloud URL
    private static String BASE_URL = "https://face-detection-backend-69o7.onrender.com/";
    
    private static Retrofit retrofit = null;

    public static void setBaseUrl(String url) {
        if (url != null && !url.isEmpty()) {
            if (!url.endsWith("/")) {
                url += "/";
            }
            BASE_URL = url;
            retrofit = null; // Reset retrofit to force rebuild with new URL
        }
    }

    public static String getBaseUrl() {
        return BASE_URL;
    }

    public static GreetingService getService() {
        if (retrofit == null) {
            retrofit = new Retrofit.Builder()
                    .baseUrl(BASE_URL)
                    .addConverterFactory(GsonConverterFactory.create())
                    .build();
        }
        return retrofit.create(GreetingService.class);
    }
}
