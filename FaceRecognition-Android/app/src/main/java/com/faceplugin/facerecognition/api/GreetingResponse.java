package com.faceplugin.facerecognition.api;

public class GreetingResponse {
    private boolean speak;
    private String text;
    private String status; // CHECK_IN, CHECK_OUT
    private String display_status; // "Check In: 9:00 AM"
    private Boolean accepted;
    private String reason;
    private boolean duplicate;
    @com.google.gson.annotations.SerializedName("event_id")
    private String eventId;

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

    public Boolean getAccepted() { return accepted; }
    public void setAccepted(Boolean accepted) { this.accepted = accepted; }
    public String getReason() { return reason; }
    public void setReason(String reason) { this.reason = reason; }
    public boolean isDuplicate() { return duplicate; }
    public void setDuplicate(boolean duplicate) { this.duplicate = duplicate; }
    public String getEventId() { return eventId; }
    public void setEventId(String eventId) { this.eventId = eventId; }

    @com.google.gson.annotations.SerializedName("person_id")
    private Object personId;

    public Object getPersonId() {
        return personId;
    }

    public void setPersonId(Object personId) {
        this.personId = personId;
    }
}
