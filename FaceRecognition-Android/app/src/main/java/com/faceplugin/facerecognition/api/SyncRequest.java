package com.faceplugin.facerecognition.api;

import com.google.gson.annotations.SerializedName;

public class SyncRequest {
    @SerializedName("name")
    private String name;

    @SerializedName("templates")
    private String templates;

    @SerializedName("face_image")
    private String faceImage;

    @SerializedName("phone")
    private String phone;

    @SerializedName("department")
    private String department;

    @SerializedName("designation")
    private String designation;

    public SyncRequest(String name, String templates, String faceImage, String phone, String department, String designation) {
        this.name = name;
        this.templates = templates;
        this.faceImage = faceImage;
        this.phone = phone;
        this.department = department;
        this.designation = designation;
    }

    public String getName() { return name; }
    public String getTemplates() { return templates; }
    public String getFaceImage() { return faceImage; }
    public String getPhone() { return phone; }
    public String getDepartment() { return department; }
    public String getDesignation() { return designation; }
}
