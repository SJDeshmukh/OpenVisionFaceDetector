package com.faceplugin.facerecognition.api;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class SyncResponse {
    @SerializedName("faces")
    private List<SyncRequest> faces;

    @SerializedName("deleted_ids")
    private List<String> deletedIds;

    @SerializedName("cursor")
    private Long cursor;

    @SerializedName("full_sync")
    private Boolean fullSync;

    public List<SyncRequest> getFaces() {
        return faces;
    }

    public List<String> getDeletedIds() { return deletedIds; }
    public Long getCursor() { return cursor; }
    public boolean isFullSync() { return fullSync == null || fullSync; }
}
