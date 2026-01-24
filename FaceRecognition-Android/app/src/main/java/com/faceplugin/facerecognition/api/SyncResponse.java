package com.faceplugin.facerecognition.api;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class SyncResponse {
    @SerializedName("faces")
    private List<SyncRequest> faces;

    public List<SyncRequest> getFaces() {
        return faces;
    }
}
