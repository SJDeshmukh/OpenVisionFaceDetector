package com.faceplugin.facerecognition.api;

import com.google.gson.annotations.SerializedName;

public class UploadFaceResponse {
    @SerializedName("status")
    private String status;

    @SerializedName("message")
    private String message;

    @SerializedName("person_id")
    private Integer personId;

    @SerializedName("display_id")
    private Integer displayId;

    public String getStatus() {
        return status;
    }

    public String getMessage() {
        return message;
    }

    public Integer getPersonId() {
        return personId;
    }

    public Integer getDisplayId() {
        return displayId;
    }
}
