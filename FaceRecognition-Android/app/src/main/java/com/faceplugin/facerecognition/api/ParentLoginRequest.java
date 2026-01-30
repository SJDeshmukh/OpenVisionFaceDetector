package com.faceplugin.facerecognition.api;

public class ParentLoginRequest {
    private String username;
    private String password;
    public ParentLoginRequest(String username, String password) {
        this.username = username;
        this.password = password;
    }
}
