package com.faceplugin.facerecognition.api;

import com.google.gson.annotations.SerializedName;

public class PersonEventRequest {
    private boolean detected;
    private boolean recognized;

    @SerializedName("person_id")
    private String personId;

    private String name;
    private float confidence;

    @SerializedName("image")
    private String imageBase64;

    private boolean is_attendance;

    // Constructor with is_attendance
    public PersonEventRequest(boolean detected, boolean recognized, String personId, String name, float confidence, String imageBase64, boolean is_attendance) {
        this.detected = detected;
        this.recognized = recognized;
        this.personId = personId;
        this.name = name;
        this.confidence = confidence;
        this.imageBase64 = imageBase64;
        this.is_attendance = is_attendance;
    }

    // Constructor without is_attendance (defaults to true for backward compatibility/CameraActivity)
    public PersonEventRequest(boolean detected, boolean recognized, String personId, String name, float confidence, String imageBase64) {
        this(detected, recognized, personId, name, confidence, imageBase64, true);
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

    public String getImageBase64() {
        return imageBase64;
    }

    public void setImageBase64(String imageBase64) {
        this.imageBase64 = imageBase64;
    }

    public boolean isAttendance() {
        return is_attendance;
    }

    public void setAttendance(boolean attendance) {
        is_attendance = attendance;
    }
}
