package com.faceplugin.facerecognition

import java.text.SimpleDateFormat
import java.util.Locale

object LeaveDateTimeFormatter {
    private val sourceDatePatterns = listOf(
        "yyyy-MM-dd",
        "yyyy-MM-dd'T'HH:mm:ss",
        "EEE, dd MMM yyyy HH:mm:ss z",
        "EEE MMM dd HH:mm:ss z yyyy"
    )

    fun date(raw: String?): String {
        val value = raw?.trim().orEmpty()
        if (value.isBlank()) return "Date not provided"
        sourceDatePatterns.forEach { pattern ->
            try {
                val parsed = SimpleDateFormat(pattern, Locale.US).parse(value)
                if (parsed != null) {
                    return SimpleDateFormat("dd MMM yyyy", Locale.ENGLISH).format(parsed)
                }
            } catch (_: Exception) {
                // Try the next supported server representation.
            }
        }
        return value.take(32)
    }

    fun time(raw: String?): String {
        val value = raw?.trim().orEmpty()
        val match = Regex("(?:^|\\D)([01]\\d|2[0-3]):([0-5]\\d)").find(value)
            ?: return "Time not provided"
        return try {
            val parsed = SimpleDateFormat("HH:mm", Locale.US)
                .parse("${match.groupValues[1]}:${match.groupValues[2]}")
            SimpleDateFormat("hh:mm a", Locale.ENGLISH).format(parsed!!)
        } catch (_: Exception) {
            "${match.groupValues[1]}:${match.groupValues[2]}"
        }
    }

    fun point(dateValue: String?, timeValue: String?): String = "${date(dateValue)}\n${time(timeValue)}"

    fun range(startDate: String?, startTime: String?, endDate: String?, endTime: String?): String {
        val startDateLabel = date(startDate)
        val endDateLabel = date(endDate)
        val startTimeLabel = time(startTime)
        val endTimeLabel = time(endTime)
        return if (startDateLabel == endDateLabel) {
            "$startDateLabel · $startTimeLabel – $endTimeLabel"
        } else {
            "$startDateLabel, $startTimeLabel → $endDateLabel, $endTimeLabel"
        }
    }
}
