package com.faceplugin.facerecognition.api;

import com.faceplugin.facerecognition.BuildConfig;
import com.google.gson.annotations.SerializedName;

public class LoginRequest {
    @SerializedName("username")
    private String username;

    @SerializedName("password")
    private String password;

    @SerializedName("device_id")
    private String deviceId;

    @SerializedName("platform")
    private String platform;

    @SerializedName("app_type")
    private String appType;

    public LoginRequest(String username, String password, String deviceId) {
        this.username = username;
        this.password = password;
        this.deviceId = deviceId;
        this.platform = "mobile";
        this.appType  = BuildConfig.IS_ATTENDX ? "attendx" : "tapinx";
    }
}
