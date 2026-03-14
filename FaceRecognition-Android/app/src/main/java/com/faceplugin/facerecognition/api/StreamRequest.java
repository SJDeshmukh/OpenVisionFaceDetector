package com.faceplugin.facerecognition.api;

public class StreamRequest {
    private String image; // Base64 encoded image
    private Integer vendor_id;
    private String device_id;
    private String device_name;
    private Float battery_level;

    public StreamRequest(String image) {
        this.image = image;
    }
    
    public StreamRequest(String image, Integer vendor_id) {
        this.image = image;
        this.vendor_id = vendor_id;
    }

    public StreamRequest(String image, Integer vendor_id, String device_id, String device_name) {
        this.image = image;
        this.vendor_id = vendor_id;
        this.device_id = device_id;
        this.device_name = device_name;
    }

    public StreamRequest(String image, Integer vendor_id, String device_id, String device_name, Float battery_level) {
        this.image = image;
        this.vendor_id = vendor_id;
        this.device_id = device_id;
        this.device_name = device_name;
        this.battery_level = battery_level;
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

    public Float getBatteryLevel() {
        return battery_level;
    }

    public void setBatteryLevel(Float battery_level) {
        this.battery_level = battery_level;
    }

    public String getDeviceId() {
        return device_id;
    }

    public void setDeviceId(String device_id) {
        this.device_id = device_id;
    }

    public String getDeviceName() {
        return device_name;
    }

    public void setDeviceName(String device_name) {
        this.device_name = device_name;
    }
}
