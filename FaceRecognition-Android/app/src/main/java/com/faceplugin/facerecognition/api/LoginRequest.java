package com.faceplugin.facerecognition.api;

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

    public LoginRequest(String username, String password, String deviceId) {
        this.username = username;
        this.password = password;
        this.deviceId = deviceId;
        this.platform = "mobile";
    }
}
