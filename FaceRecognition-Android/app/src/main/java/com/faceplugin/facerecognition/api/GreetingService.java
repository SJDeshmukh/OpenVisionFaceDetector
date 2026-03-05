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

    @POST("api/parents/select-student")
    Call<com.google.gson.JsonObject> selectStudent(@Body ParentSelectRequest request);

    @POST("api/parents/logout")
    Call<com.google.gson.JsonObject> parentLogout();

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
}
