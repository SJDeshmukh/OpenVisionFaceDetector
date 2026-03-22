package com.faceplugin.facerecognition.api

import com.google.gson.annotations.SerializedName

data class LeaveRequest(
    @SerializedName("student_id") val studentId: String,
    @SerializedName("leave_type") val leaveType: String,
    @SerializedName("reason") val reason: String,
    @SerializedName("start_date") val startDate: String,
    @SerializedName("end_date") val endDate: String,
    @SerializedName("start_time") val startTime: String = "10:00",
    @SerializedName("end_time") val endTime: String = "18:00"
)
