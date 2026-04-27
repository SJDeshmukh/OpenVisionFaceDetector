package com.faceplugin.facerecognition

import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.github.mikephil.charting.animation.Easing
import com.github.mikephil.charting.charts.BarChart
import com.github.mikephil.charting.charts.PieChart
import com.github.mikephil.charting.components.XAxis
import com.github.mikephil.charting.data.*
import com.github.mikephil.charting.formatter.IndexAxisValueFormatter
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.*

class ParentAnalyticsFragment : Fragment() {

    private lateinit var root: View
    private var currentFilter = "week"
    private val colorPresent = Color.parseColor("#10B981")
    private val colorAbsent = Color.parseColor("#EF4444")
    private val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.US)

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        root = inflater.inflate(R.layout.fragment_parent_analytics, container, false)
        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupPieChart()
        setupBarChart()
        setupFilterChips()
        loadData()
    }

    private fun setupFilterChips() {
        val chips = mapOf(
            root.findViewById<TextView>(R.id.chip_week) to "week",
            root.findViewById<TextView>(R.id.chip_month) to "month",
            root.findViewById<TextView>(R.id.chip_year) to "year"
        )
        chips.forEach { (chip, filter) ->
            chip.setOnClickListener {
                chips.keys.forEach { it.isSelected = false }
                chip.isSelected = true
                currentFilter = filter
                root.findViewById<TextView>(R.id.tv_bar_chart_title).text = when (filter) {
                    "month" -> "Monthly Trend"
                    "year" -> "Yearly Overview"
                    else -> "Weekly Trend"
                }
                loadData()
            }
        }
        root.findViewById<TextView>(R.id.chip_week).isSelected = true
    }

    private fun setupPieChart() {
        root.findViewById<PieChart>(R.id.pie_chart).apply {
            description.isEnabled = false
            isDrawHoleEnabled = true
            holeRadius = 55f
            setHoleColor(Color.TRANSPARENT)
            transparentCircleRadius = 60f
            setTransparentCircleColor(Color.TRANSPARENT)
            setDrawCenterText(true)
            setCenterTextColor(Color.WHITE)
            setCenterTextSize(14f)
            legend.textColor = Color.WHITE
            legend.textSize = 12f
            setDrawEntryLabels(false)
            setNoDataText("Loading...")
            setNoDataTextColor(Color.WHITE)
        }
    }

    private fun setupBarChart() {
        root.findViewById<BarChart>(R.id.bar_chart).apply {
            description.isEnabled = false
            setDrawGridBackground(false)
            setDrawBarShadow(false)
            setFitBars(true)
            legend.isEnabled = false
            setNoDataText("Loading...")
            setNoDataTextColor(Color.WHITE)
            axisLeft.textColor = Color.parseColor("#99FFFFFF")
            axisLeft.gridColor = Color.parseColor("#22FFFFFF")
            axisLeft.axisLineColor = Color.TRANSPARENT
            axisRight.isEnabled = false
            xAxis.textColor = Color.parseColor("#99FFFFFF")
            xAxis.gridColor = Color.TRANSPARENT
            xAxis.position = XAxis.XAxisPosition.BOTTOM
            xAxis.setDrawAxisLine(false)
        }
    }

    private fun filterDates(): Pair<String, String> {
        val end = Calendar.getInstance()
        val start = Calendar.getInstance()
        when (currentFilter) {
            "month" -> start.add(Calendar.DAY_OF_YEAR, -30)
            "year" -> start.add(Calendar.DAY_OF_YEAR, -365)
            else -> start.add(Calendar.DAY_OF_YEAR, -7)
        }
        return sdf.format(start.time) to sdf.format(end.time)
    }

    private fun loadData() {
        if (!isAdded) return
        if (BuildConfig.IS_ATTENDX) {
            loadAttendXData()
        } else {
            loadTapInXData()
        }
    }

    // AttendX: count only from faculty-conducted lectures — no phantom days
    private fun loadAttendXData() {
        val (startDate, endDate) = filterDates()
        RetrofitClient.getService()
            .getParentLectureAttendance(startDate, endDate)
            .enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                    if (!isAdded) return
                    if (response.code() in listOf(401, 403)) {
                        (activity as? ParentActivity)?.performLogout(); return
                    }
                    if (!response.isSuccessful || response.body() == null) {
                        showAnalyticsError("No data found. Please contact your administrator.")
                        return
                    }
                    val body = response.body()!!
                    val list = try { body.getAsJsonArray("attendance") } catch (_: Exception) { return }

                    var present = 0
                    var absent = 0
                    // Group by date for bar chart
                    val byDate = linkedMapOf<String, Pair<Int, Int>>() // date → (present, absent)

                    for (i in 0 until list.size()) {
                        val obj = try { list[i].asJsonObject } catch (_: Exception) { continue }
                        val status = try { obj.get("status")?.asString ?: "absent" } catch (_: Exception) { "absent" }
                        val rawDate = try { obj.get("lecture_date")?.asString ?: "" } catch (_: Exception) { "" }
                        // Normalize date: take first 10 chars if it's a full datetime
                        val dateKey = rawDate.take(10).let {
                            if (it.matches(Regex("\\d{4}-\\d{2}-\\d{2}"))) it
                            else rawDate.take(11).replace(" ", "").take(10)
                        }

                        val (p, a) = byDate.getOrDefault(dateKey, 0 to 0)
                        if (status == "present") {
                            present++
                            byDate[dateKey] = p + 1 to a
                        } else {
                            absent++
                            byDate[dateKey] = p to a + 1
                        }
                    }

                    val total = present + absent
                    val rate = if (total > 0) present * 100 / total else 0
                    root.findViewById<TextView>(R.id.tv_analytics_present).text = "$present"
                    root.findViewById<TextView>(R.id.tv_analytics_absent).text = "$absent"
                    root.findViewById<TextView>(R.id.tv_analytics_rate).text = "$rate%"

                    updatePieChart(present, absent)
                    updateBarChartFromMap(byDate)
                    updateInsight(present, absent, rate)
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                    if (isAdded) showAnalyticsError("Connection error. Check your internet and try again.")
                }
            })
    }

    // TapInX: count from check-in events (day = present if has CHECK_IN)
    private fun loadTapInXData() {
        RetrofitClient.getService().getParentAttendance().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                if (response.code() in listOf(401, 403)) {
                    (activity as? ParentActivity)?.performLogout(); return
                }
                if (!response.isSuccessful || response.body() == null) {
                    showAnalyticsError("No data found. Please contact your administrator.")
                    return
                }
                val body = response.body()!!
                val list = try { body.getAsJsonArray("attendance") } catch (_: Exception) { return }

                val (startStr, _) = filterDates()
                val cutoff = try { sdf.parse(startStr) } catch (_: Exception) { null } ?: return

                val dayPresent = mutableMapOf<String, Boolean>()
                for (i in 0 until list.size()) {
                    val obj = try { list[i].asJsonObject } catch (_: Exception) { continue }
                    val ts = try { obj.get("timestamp")?.asString ?: "" } catch (_: Exception) { "" }
                    val status = try { obj.get("status")?.asString ?: "" } catch (_: Exception) { "" }
                    val dateStr = ts.take(10)
                    if (!dateStr.matches(Regex("\\d{4}-\\d{2}-\\d{2}"))) continue
                    val date = try { sdf.parse(dateStr) } catch (_: Exception) { null } ?: continue
                    if (date.before(cutoff)) continue
                    if (status == "CHECK_IN") dayPresent[dateStr] = true
                    else if (!dayPresent.containsKey(dateStr)) dayPresent[dateStr] = false
                }

                val present = dayPresent.values.count { it }
                val total = dayPresent.size
                val absent = total - present
                val rate = if (total > 0) present * 100 / total else 0

                root.findViewById<TextView>(R.id.tv_analytics_present).text = "$present"
                root.findViewById<TextView>(R.id.tv_analytics_absent).text = "$absent"
                root.findViewById<TextView>(R.id.tv_analytics_rate).text = "$rate%"

                updatePieChart(present, absent)
                // Bar chart: only days that have a record (no phantom days)
                val byDate = dayPresent.entries
                    .sortedBy { it.key }
                    .associate { it.key.takeLast(5) to (if (it.value) 1 to 0 else 0 to 1) }
                updateBarChartFromMap(LinkedHashMap(byDate))
                updateInsight(present, absent, rate)
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (isAdded) showAnalyticsError("Connection error. Check your internet and try again.")
            }
        })
    }

    private fun updatePieChart(present: Int, absent: Int) {
        val chart = root.findViewById<PieChart>(R.id.pie_chart)
        val total = present + absent
        if (total == 0) { chart.clear(); return }
        val entries = listOf(PieEntry(present.toFloat(), "Present"), PieEntry(absent.toFloat(), "Absent"))
        val ds = PieDataSet(entries, "").apply {
            colors = listOf(colorPresent, colorAbsent)
            sliceSpace = 3f; selectionShift = 5f
            valueTextColor = Color.WHITE; valueTextSize = 12f
        }
        chart.data = PieData(ds)
        chart.centerText = "${present * 100 / total}%\nPresent"
        chart.animateY(800, Easing.EaseInOutCubic)
        chart.invalidate()
    }

    private fun updateBarChartFromMap(byDate: Map<String, Pair<Int, Int>>) {
        val chart = root.findViewById<BarChart>(R.id.bar_chart)
        if (byDate.isEmpty()) { chart.clear(); return }

        val labels = byDate.keys.toList()
        val entries = labels.mapIndexed { i, key ->
            val (p, _) = byDate[key]!!
            BarEntry(i.toFloat(), p.toFloat())
        }
        val colors = labels.map { key ->
            val (p, _) = byDate[key]!!
            if (p > 0) colorPresent else colorAbsent
        }
        val ds = BarDataSet(entries, "").apply {
            this.colors = colors
            setDrawValues(false)
        }
        chart.xAxis.valueFormatter = IndexAxisValueFormatter(labels)
        chart.xAxis.labelCount = minOf(labels.size, 7)
        chart.xAxis.labelRotationAngle = -30f
        chart.data = BarData(ds).apply { barWidth = 0.6f }
        chart.axisLeft.axisMinimum = 0f
        chart.axisLeft.resetAxisMaximum()
        chart.animateY(600, Easing.EaseInOutCubic)
        chart.invalidate()
    }

    private fun updateInsight(present: Int, absent: Int, rate: Int) {
        val label = if (BuildConfig.IS_ATTENDX) "lectures" else "days"
        root.findViewById<TextView>(R.id.tv_analytics_insight).text = when {
            rate >= 90 -> "Excellent! $present/${ present + absent} $label attended ($rate%). Outstanding performance."
            rate >= 75 -> "Good job at $rate% ($present $label). Push for 90%+ to maximize performance."
            rate >= 50 -> "Fair at $rate% — $absent $label missed. There's room to improve."
            else -> "Attendance needs improvement: $rate% ($absent $label missed). Take action now."
        }
    }

    private fun showAnalyticsError(msg: String) {
        if (!isAdded) return
        try {
            root.findViewById<TextView>(R.id.tv_analytics_present).text = "—"
            root.findViewById<TextView>(R.id.tv_analytics_absent).text = "—"
            root.findViewById<TextView>(R.id.tv_analytics_rate).text = "—"
            root.findViewById<TextView>(R.id.tv_analytics_insight).text = msg
            root.findViewById<com.github.mikephil.charting.charts.PieChart>(R.id.pie_chart).setNoDataText(msg)
            root.findViewById<com.github.mikephil.charting.charts.BarChart>(R.id.bar_chart).setNoDataText(msg)
            root.findViewById<com.github.mikephil.charting.charts.PieChart>(R.id.pie_chart).invalidate()
            root.findViewById<com.github.mikephil.charting.charts.BarChart>(R.id.bar_chart).invalidate()
        } catch (_: Exception) {}
    }
}
