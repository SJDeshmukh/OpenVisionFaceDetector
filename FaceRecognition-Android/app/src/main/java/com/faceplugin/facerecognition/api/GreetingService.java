package com.faceplugin.facerecognition.api;

import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.DELETE;
import retrofit2.http.GET;
import retrofit2.http.POST;
import retrofit2.http.Path;
import retrofit2.http.Query;

public interface GreetingService {
    @POST("api/auth/login")
    Call<LoginResponse> login(@Body LoginRequest request);

    @POST("api/auth/register")
    Call<LoginResponse> register(@Body RegisterRequest request);

    @POST("api/person-event")
    Call<GreetingResponse> sendPersonEvent(@Body PersonEventRequest request);

    @POST("api/sync/upload")
    Call<UploadFaceResponse> uploadFace(@Body com.google.gson.JsonObject request);

    @GET("api/admin/vendors/{vendor_id}/registration-config")
    Call<com.google.gson.JsonObject> getRegistrationConfig(@Path("vendor_id") int vendorId);

    @GET("api/settings")
    Call<com.google.gson.JsonObject> getSettings();

    @GET("api/sync/download")
    Call<SyncResponse> downloadFaces();

    @GET("api/public/vendors")
    Call<com.google.gson.JsonObject> getPublicVendors();

    @GET("api/public/business-types")
    Call<com.google.gson.JsonObject> getPublicBusinessTypes();

    @GET("api/config")
    Call<com.google.gson.JsonObject> getConfig();

    @POST("api/stream/upload")
    Call<Void> uploadStreamFrame(@Body StreamRequest request);

    @DELETE("api/sync/delete/{name}")
    Call<Void> deleteFace(@Path("name") String name);

    @DELETE("api/sync/delete/id/{id}")
    Call<Void> deleteFaceById(@Path("id") String id);

    @GET("api/companies/{id}")
    Call<com.google.gson.JsonObject> getCompany(@Path("id") int id);

    @GET("api/companies")
    Call<com.google.gson.JsonObject> getCompanies();

    @POST("api/parents/login")
    Call<LoginResponse> parentLogin(@Body ParentLoginRequest request);

    @GET("api/parents/attendance")
    Call<com.google.gson.JsonObject> getParentAttendance();

    @GET("api/parents/attendance")
    Call<com.google.gson.JsonObject> getParentAttendanceByDate(@Query("date") String date);

    @GET("api/parents/attendance")
    Call<com.google.gson.JsonObject> getParentAttendanceByDateLimit(@Query("date") String date, @Query("limit") int limit);

    @GET("api/parents/student-day")
    Call<com.google.gson.JsonObject> getParentStudentDay(@Query("date") String date);

    @GET("api/parents/lecture-attendance")
    Call<com.google.gson.JsonObject> getParentLectureAttendance(
        @Query("start_date") String startDate,
        @Query("end_date") String endDate
    );

    @POST("api/parents/select-student")
    Call<com.google.gson.JsonObject> selectStudent(@Body ParentSelectRequest request);

    @POST("api/parents/logout")
    Call<com.google.gson.JsonObject> parentLogout();

    @POST("api/parents/update-fcm-token")
    Call<com.google.gson.JsonObject> updateFcmToken(@Body com.google.gson.JsonObject body);

    @POST("api/leave/parent/register-face")
    Call<com.google.gson.JsonObject> parentRegisterFace(@Body ParentRegisterFaceRequest request);

    @GET("api/leave/parent/pending")
    Call<com.google.gson.JsonObject> getParentPendingLeaves(@Query("student_number") String studentNumber);

    @POST("api/leave/parent/approve")
    Call<com.google.gson.JsonObject> parentApproveLeave(@Body com.google.gson.JsonObject request);

    @POST("api/leave/request")
    Call<com.google.gson.JsonObject> createLeaveRequest(@Body LeaveRequest request);

    @POST("api/leave/parent/reject")
    Call<com.google.gson.JsonObject> parentRejectLeave(@Body com.google.gson.JsonObject request);

    @GET("api/public/attendance-by-student")
    Call<com.google.gson.JsonObject> attendanceByStudent(@Query("student_number") String studentNumber);
    @GET("api/public/attendance-by-student")
    Call<com.google.gson.JsonObject> attendanceByStudentWithDate(@Query("student_number") String studentNumber,
                                                                 @Query("date") String date);

    // Mobile device slot management
    @GET("api/mobile/device-slots")
    Call<com.google.gson.JsonObject> getMobileDeviceSlots(@Query("include_deleted") boolean includeDeleted);
    @POST("api/mobile/assign-slot")
    Call<com.google.gson.JsonObject> assignMobileDeviceSlot(@Body com.google.gson.JsonObject body);

    @GET("api/mobile/device-info")
    Call<com.google.gson.JsonObject> getMobileDeviceInfo();

    @POST("api/mobile/heartbeat")
    Call<com.google.gson.JsonObject> sendHeartbeat(@Body com.google.gson.JsonObject body);

    @POST("api/parents/face-reset-request")
    Call<com.google.gson.JsonObject> requestFaceReset(@Body com.google.gson.JsonObject body);

    // Faculty mobile endpoints
    @GET("api/bulk-attendance/lectures")
    Call<com.google.gson.JsonObject> getFacultyLectures(
        @Query("class_year") String classYear,
        @Query("division") String division,
        @Query("date") String date
    );

    @POST("api/bulk-attendance/lectures")
    Call<com.google.gson.JsonObject> createFacultyLecture(@Body com.google.gson.JsonObject body);

    @POST("api/bulk-attendance/lectures/{lecture_id}/mark")
    Call<com.google.gson.JsonObject> markFacultyLectureAttendance(
        @Path("lecture_id") int lectureId,
        @Body com.google.gson.JsonObject body
    );

    @POST("api/bulk-attendance/faculty/sync")
    Call<com.google.gson.JsonObject> syncFacultyAttendance(@Body com.google.gson.JsonObject body);

    @POST("api/bulk-attendance/faculty/scan")
    Call<com.google.gson.JsonObject> scanFacultyImage(@Body com.google.gson.JsonObject body);

    @GET("api/bulk-attendance/faculty/classes")
    Call<com.google.gson.JsonObject> getFacultyClasses();


    // Owner API
    @GET("api/owner/advances")
    Call<com.google.gson.JsonObject> getOwnerAdvances();

    @POST("api/owner/advances/approve")
    Call<com.google.gson.JsonObject> approveOwnerAdvance(@Body com.google.gson.JsonObject body);

    @POST("api/owner/advances/reject")
    Call<com.google.gson.JsonObject> rejectOwnerAdvance(@Body com.google.gson.JsonObject body);

    @GET("api/owner/insights")
    Call<com.google.gson.JsonObject> getOwnerInsights();
}
