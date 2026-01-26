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
    Call<Void> uploadFace(@Body SyncRequest request);

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
}
