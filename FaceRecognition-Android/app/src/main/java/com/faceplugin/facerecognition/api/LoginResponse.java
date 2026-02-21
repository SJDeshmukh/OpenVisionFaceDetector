package com.faceplugin.facerecognition.api;

import com.google.gson.JsonElement;
import com.google.gson.annotations.SerializedName;

public class LoginResponse {
    @SerializedName("status")
    private String status;

    @SerializedName("role")
    private String role; // "admin" or "user"

    @SerializedName("username")
    private String username;
    
    @SerializedName("token")
    private String token;

    @SerializedName("vendor_id")
    private Integer vendorId;

    @SerializedName("company_id")
    private Integer companyId;

    @SerializedName("vendor_config")
    private JsonElement vendorConfig;

    @SerializedName("error")
    private String error;

    public String getStatus() { return status; }
    public String getRole() { return role; }
    public String getUsername() { return username; }
    public String getToken() { return token; }
    public Integer getVendorId() { return vendorId; }
    public Integer getCompanyId() { return companyId; }
    public JsonElement getVendorConfig() { return vendorConfig; }
    public String getError() { return error; }
}
