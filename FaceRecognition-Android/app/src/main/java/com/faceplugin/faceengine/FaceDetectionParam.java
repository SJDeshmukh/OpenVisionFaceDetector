package com.faceplugin.faceengine;

/** Options retained so existing screens can request only the work they need. */
public final class FaceDetectionParam {
    public boolean check_liveness;
    public int check_liveness_level;
    public boolean check_eye_closeness;
    public boolean check_face_occlusion;
    public boolean estimate_age_gender;
    public boolean check_pose = true;
    public boolean check_landmarks = true;
    public boolean check_quality;
    public boolean check_emotion;
    public boolean check_mask;
    public boolean check_glasses;
}
