package com.faceplugin.facerecognition.api;

import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.DELETE;
import retrofit2.http.GET;
import retrofit2.http.POST;
import retrofit2.http.Path;

public interface GreetingService {
    @POST("api/auth/login")
    Call<LoginResponse> login(@Body LoginRequest request);

    @POST("api/auth/register")
    Call<LoginResponse> register(@Body RegisterRequest request);

    @POST("api/person-event")
    Call<GreetingResponse> sendPersonEvent(@Body PersonEventRequest request);

    @POST("api/sync/upload")
    Call<Void> uploadFace(@Body com.google.gson.JsonObject request);

    @GET("api/admin/vendors/{vendor_id}/registration-config")
    Call<com.google.gson.JsonObject> getRegistrationConfig(@Path("vendor_id") int vendorId);

    @GET("api/sync/download")
    Call<SyncResponse> downloadFaces();

    @POST("api/stream/upload")
    Call<Void> uploadStreamFrame(@Body StreamRequest request);

    @DELETE("api/sync/delete/{name}")
    Call<Void> deleteFace(@Path("name") String name);

    @GET("api/companies/{id}")
    Call<com.google.gson.JsonObject> getCompany(@Path("id") int id);

    @GET("api/companies")
    Call<com.google.gson.JsonObject> getCompanies();

    @POST("api/parents/login")
    Call<LoginResponse> parentLogin(@Body ParentLoginRequest request);

    @GET("api/parents/attendance")
    Call<com.google.gson.JsonObject> getParentAttendance();

    @POST("api/parents/select-student")
    Call<com.google.gson.JsonObject> selectStudent(@Body ParentSelectRequest request);

    @GET("api/public/attendance-by-student")
    Call<com.google.gson.JsonObject> attendanceByStudent(@retrofit2.http.Query("student_number") String studentNumber);
    @GET("api/public/attendance-by-student")
    Call<com.google.gson.JsonObject> attendanceByStudentWithDate(@retrofit2.http.Query("student_number") String studentNumber,
                                                                 @retrofit2.http.Query("date") String date);
}
