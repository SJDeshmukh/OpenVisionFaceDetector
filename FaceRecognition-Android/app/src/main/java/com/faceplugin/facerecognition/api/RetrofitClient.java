package com.faceplugin.facerecognition.api;

import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class RetrofitClient {
    // For Android Emulator, use 10.0.2.2.
    // For Physical Device, use your computer's LAN IP (e.g. 192.168.1.x)
    private static String BASE_URL = "http://192.168.1.2:5001/";
    
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
