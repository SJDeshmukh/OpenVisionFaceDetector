package com.faceplugin.facerecognition.api;

import com.google.gson.annotations.SerializedName;

public class LoginResponse {
    @SerializedName("status")
    private String status;

    @SerializedName("role")
    private String role; // "admin" or "user"

    @SerializedName("username")
    private String username;
    
    @SerializedName("error")
    private String error;

    public String getStatus() { return status; }
    public String getRole() { return role; }
    public String getUsername() { return username; }
    public String getError() { return error; }
}
