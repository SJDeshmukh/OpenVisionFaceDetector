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
    
    @SerializedName("timestamp")
    private String timestamp;

    // Constructor with is_attendance and timestamp
    public PersonEventRequest(boolean detected, boolean recognized, String personId, String name, float confidence, String imageBase64, boolean is_attendance, String timestamp) {
        this.detected = detected;
        this.recognized = recognized;
        this.personId = personId;
        this.name = name;
        this.confidence = confidence;
        this.imageBase64 = imageBase64;
        this.is_attendance = is_attendance;
        this.timestamp = timestamp;
    }

    // Constructor without timestamp (for backward compatibility, though we should avoid using it)
    public PersonEventRequest(boolean detected, boolean recognized, String personId, String name, float confidence, String imageBase64, boolean is_attendance) {
        this(detected, recognized, personId, name, confidence, imageBase64, is_attendance, null);
    }

    // Constructor without is_attendance (defaults to true)
    public PersonEventRequest(boolean detected, boolean recognized, String personId, String name, float confidence, String imageBase64) {
        this(detected, recognized, personId, name, confidence, imageBase64, true, null);
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

    public String getTimestamp() {
        return timestamp;
    }

    public void setTimestamp(String timestamp) {
        this.timestamp = timestamp;
    }
}
