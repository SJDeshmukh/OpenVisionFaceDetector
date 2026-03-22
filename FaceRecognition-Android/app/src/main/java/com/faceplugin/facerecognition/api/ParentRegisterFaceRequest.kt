package com.faceplugin.facerecognition.api

import com.google.gson.annotations.SerializedName

data class ParentRegisterFaceRequest(
    @SerializedName("student_number") val studentNumber: String,
    @SerializedName("face_image") val faceImage: String,
    @SerializedName("face_template") val faceTemplate: String
)

data class DefaultResponse(
    @SerializedName("status") val status: String,
    @SerializedName("error") val error: String? = null
)
