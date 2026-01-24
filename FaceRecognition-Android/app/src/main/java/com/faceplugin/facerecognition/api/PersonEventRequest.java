package com.faceplugin.facerecognition.api;

import com.google.gson.annotations.SerializedName;

public class PersonEventRequest {
    @SerializedName("detected")
    private boolean detected;

    @SerializedName("recognized")
    private boolean recognized;

    @SerializedName("person_id")
    private String personId;

    @SerializedName("name")
    private String name;

    @SerializedName("confidence")
    private float confidence;

    @SerializedName("image")
    private String image;

    public PersonEventRequest(boolean detected, boolean recognized, String personId, String name, float confidence, String image) {
        this.detected = detected;
        this.recognized = recognized;
        this.personId = personId;
        this.name = name;
        this.confidence = confidence;
        this.image = image;
    }

    // Getters and Setters
    public boolean isDetected() {
        return detected;
    }

    public void setDetected(boolean detected) {
        this.detected = detected;
    }

    public boolean isRecognized() {
        return recognized;
    }

    public void setRecognized(boolean recognized) {
        this.recognized = recognized;
    }

    public String getPersonId() {
        return personId;
    }

    public void setPersonId(String personId) {
        this.personId = personId;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public float getConfidence() {
        return confidence;
    }

    public void setConfidence(float confidence) {
        this.confidence = confidence;
    }

    public String getImage() { return image; }
    public void setImage(String image) { this.image = image; }
}
