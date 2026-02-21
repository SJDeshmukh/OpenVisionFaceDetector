package com.faceplugin.facerecognition.api;

public class ParentLoginRequest {
    private String student_id;
    private String mobile_number;
    private String device_id;
    private int vendor_id;
    private String fcm_token;

    public ParentLoginRequest(String student_id, String mobile_number, String device_id, int vendor_id, String fcm_token) {
        this.student_id = student_id;
        this.mobile_number = mobile_number;
        this.device_id = device_id;
        this.vendor_id = vendor_id;
        this.fcm_token = fcm_token;
    }
}
