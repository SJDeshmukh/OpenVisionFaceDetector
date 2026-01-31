package com.faceplugin.facerecognition.api;

public class GreetingResponse {
    private boolean speak;
    private String text;
    private String status; // CHECK_IN, CHECK_OUT
    private String display_status; // "Check In: 9:00 AM"

    public boolean isSpeak() {
        return speak;
    }

    public void setSpeak(boolean speak) {
        this.speak = speak;
    }

    public String getText() {
        return text;
    }

    public void setText(String text) {
        this.text = text;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getDisplayStatus() {
        return display_status;
    }

    public void setDisplayStatus(String displayStatus) {
        this.display_status = displayStatus;
    }
}
