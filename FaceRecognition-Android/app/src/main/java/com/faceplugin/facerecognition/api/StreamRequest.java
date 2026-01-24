package com.faceplugin.facerecognition.api;

public class StreamRequest {
    private String image; // Base64 encoded image

    public StreamRequest(String image) {
        this.image = image;
    }

    public String getImage() {
        return image;
    }

    public void setImage(String image) {
        this.image = image;
    }
}
