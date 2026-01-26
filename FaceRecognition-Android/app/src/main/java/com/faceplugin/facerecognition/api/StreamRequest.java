package com.faceplugin.facerecognition.api;

public class StreamRequest {
    private String image; // Base64 encoded image
    private Integer vendor_id;

    public StreamRequest(String image) {
        this.image = image;
    }
    
    public StreamRequest(String image, Integer vendor_id) {
        this.image = image;
        this.vendor_id = vendor_id;
    }

    public String getImage() {
        return image;
    }

    public void setImage(String image) {
        this.image = image;
    }
    
    public Integer getVendorId() {
        return vendor_id;
    }

    public void setVendorId(Integer vendor_id) {
        this.vendor_id = vendor_id;
    }
}
