package com.faceplugin.facerecognition

import android.app.DatePickerDialog
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.fragment.app.Fragment
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.*

class ParentHistoryFragment : Fragment() {

    private lateinit var root: View
    private val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.US)

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        root = inflater.inflate(R.layout.fragment_parent_history, container, false)
        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val swipe = root.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh_history)
        swipe.setColorSchemeColors(Color.parseColor("#4F46E5"), Color.parseColor("#06B6D4"))

        if (BuildConfig.IS_ATTENDX) {
            setupAttendXHistory(swipe)
        } else {
            setupTapInXHistory(swipe)
        }
    }

    // ── AttendX: date range → lecture attendance (faculty-conducted only) ────

    private fun setupAttendXHistory(swipe: SwipeRefreshLayout) {
        root.findViewById<TextView>(R.id.tv_history_subtitle).text =
            "Lecture attendance by date range"
        root.findViewById<LinearLayout>(R.id.row_hist_single_date).visibility = View.GONE
        root.findViewById<LinearLayout>(R.id.row_hist_date_range).visibility = View.VISIBLE
        root.findViewById<TextView>(R.id.tv_hist_summary).visibility = View.VISIBLE

        val etStart = root.findViewById<EditText>(R.id.et_hist_range_start)
        val etEnd = root.findViewById<EditText>(R.id.et_hist_range_end)

        // Default: last 30 days → today
        val today = sdf.format(Calendar.getInstance().time)
        val cal30 = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -30) }
        val monthAgo = sdf.format(cal30.time)
        etStart.setText(monthAgo)
        etEnd.setText(today)

        etStart.setOnClickListener { showDatePicker(etStart) }
        etEnd.setOnClickListener { showDatePicker(etEnd) }
        root.findViewById<Button>(R.id.btn_hist_range_load).setOnClickListener {
            fetchLectureRange(etStart.text.toString().trim(), etEnd.text.toString().trim())
        }
        swipe.setOnRefreshListener {
            fetchLectureRange(etStart.text.toString().trim(), etEnd.text.toString().trim())
            swipe.isRefreshing = false
        }
        fetchLectureRange(monthAgo, today)
    }

    // Only shows days where faculty actually ran a session — no phantom absent days generated
    private fun fetchLectureRange(startDate: String, endDate: String) {
        if (!isAdded) return
        RetrofitClient.getService()
            .getParentLectureAttendance(startDate.ifBlank { null }, endDate.ifBlank { null })
            .enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                    if (!isAdded) return
                    if (response.code() in listOf(401, 403)) {
                        (activity as? ParentActivity)?.performLogout(); return
                    }
                    val body = response.body() ?: return
                    val list = try { body.getAsJsonArray("attendance") } catch (_: Exception) { null }
                    val container = root.findViewById<LinearLayout>(R.id.history_list_container)
                    container.removeAllViews()

                    if (list == null || list.size() == 0) {
                        val tv = TextView(requireContext())
                        tv.text = "No lectures found for this period."
                        tv.textSize = 14f
                        tv.setTextColor(Color.parseColor("#66FFFFFF"))
                        tv.setPadding(0, 24, 0, 0)
                        container.addView(tv)
                        root.findViewById<TextView>(R.id.tv_hist_summary).text = ""
                        return
                    }

                    var present = 0
                    val total = list.size()
                    for (i in 0 until total) {
                        val obj = try { list[i].asJsonObject } catch (_: Exception) { continue }
                        val status = try { obj.get("status")?.asString ?: "absent" } catch (_: Exception) { "absent" }
                        if (status == "present") present++
                        val card = createLectureCard(obj)
                        card.alpha = 0f
                        container.addView(card)
                        card.animate().alpha(1f).setStartDelay((i * 30).toLong()).setDuration(250).start()
                    }
                    root.findViewById<TextView>(R.id.tv_hist_summary).text =
                        "Present: $present / $total lectures"
                }
                override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                    if (isAdded) Toast.makeText(context, "Network error", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun createLectureCard(obj: JsonObject): LinearLayout {
        val status = try { obj.get("status")?.asString ?: "absent" } catch (_: Exception) { "absent" }
        val subject = try { obj.get("subject")?.asString ?: "Lecture" } catch (_: Exception) { "Lecture" }
        val date = try { obj.get("lecture_date")?.asString ?: "" } catch (_: Exception) { "" }
        val time = try { obj.get("start_time")?.asString ?: "" } catch (_: Exception) { "" }
        val teacher = try { obj.get("teacher")?.asString ?: "" } catch (_: Exception) { "" }
        val isPresent = status == "present"
        val dp = resources.displayMetrics.density

        val card = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundResource(R.drawable.bg_history_item)
            val pad = (14 * dp).toInt()
            setPadding(pad, pad, pad, pad)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).also { it.bottomMargin = (10 * dp).toInt() }
        }

        // Color strip
        val strip = View(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams((4 * dp).toInt(), ViewGroup.LayoutParams.MATCH_PARENT)
                .also { it.marginEnd = (14 * dp).toInt() }
            setBackgroundColor(
                if (isPresent) Color.parseColor("#10B981") else Color.parseColor("#EF4444")
            )
        }

        val col = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }

        val tvSubject = TextView(requireContext()).apply {
            text = subject; textSize = 15f
            setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        }
        val tvStatus = TextView(requireContext()).apply {
            text = if (isPresent) "Present" else "Absent"
            textSize = 12f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (isPresent) Color.parseColor("#10B981") else Color.parseColor("#EF4444"))
        }
        val meta = listOf(date, time, teacher).filter { it.isNotBlank() }.joinToString(" · ")
        val tvMeta = TextView(requireContext()).apply {
            text = meta; textSize = 11f; setTextColor(Color.parseColor("#66FFFFFF"))
        }

        col.addView(tvSubject)
        col.addView(tvStatus)
        if (meta.isNotBlank()) col.addView(tvMeta)
        card.addView(strip)
        card.addView(col)
        return card
    }

    // ── TapInX: single date → check-in/out records ──────────────────────────

    private fun setupTapInXHistory(swipe: SwipeRefreshLayout) {
        val etDate = root.findViewById<EditText>(R.id.et_hist_date)
        etDate.setText(sdf.format(Calendar.getInstance().time))
        etDate.setOnClickListener { showDatePicker(etDate) }
        root.findViewById<Button>(R.id.btn_hist_load).setOnClickListener { fetchCheckInOutHistory() }
        swipe.setOnRefreshListener { fetchCheckInOutHistory(); swipe.isRefreshing = false }
        fetchCheckInOutHistory()
    }

    private fun fetchCheckInOutHistory() {
        if (!isAdded) return
        val date = root.findViewById<EditText>(R.id.et_hist_date).text.toString().trim().ifBlank { null }
        RetrofitClient.getService().getParentStudentDay(date).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                if (response.code() in listOf(401, 403)) {
                    (activity as? ParentActivity)?.performLogout(); return
                }
                val body = response.body() ?: return
                val list = try { body.getAsJsonArray("attendance") } catch (_: Exception) { null }
                val container = root.findViewById<LinearLayout>(R.id.history_list_container)
                container.removeAllViews()

                if (list == null || list.size() == 0) {
                    val tv = TextView(requireContext())
                    tv.text = "No records found for this date."
                    tv.textSize = 14f; tv.setTextColor(Color.parseColor("#66FFFFFF"))
                    tv.setPadding(0, 24, 0, 0)
                    container.addView(tv); return
                }
                for (i in 0 until list.size()) {
                    val obj = try { list[i].asJsonObject } catch (_: Exception) { continue }
                    val status = try { obj.get("status")?.asString ?: "" } catch (_: Exception) { "" }
                    if (status != "CHECK_IN" && status != "CHECK_OUT") continue
                    val ts = try { obj.get("timestamp")?.asString ?: "" } catch (_: Exception) { "" }
                    val act = try { obj.get("activity")?.asString ?: "" } catch (_: Exception) { "" }
                    val place = try {
                        obj.get("device_name")?.asString?.takeIf { it.isNotBlank() }
                            ?: obj.get("place")?.asString ?: ""
                    } catch (_: Exception) { "" }
                    val card = createCheckInCard(status, ts, act, place)
                    card.alpha = 0f
                    container.addView(card)
                    card.animate().alpha(1f).setStartDelay((i * 50).toLong()).setDuration(300).start()
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (isAdded) Toast.makeText(context, "Network error", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun createCheckInCard(status: String, ts: String, activity: String, place: String): LinearLayout {
        val isIn = status == "CHECK_IN"
        val dp = resources.displayMetrics.density

        val card = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundResource(R.drawable.bg_history_item)
            val pad = (16 * dp).toInt()
            setPadding(pad, pad, pad, pad)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).also { it.bottomMargin = (10 * dp).toInt() }
        }
        val strip = View(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams((4 * dp).toInt(), ViewGroup.LayoutParams.MATCH_PARENT)
                .also { it.marginEnd = (14 * dp).toInt() }
            setBackgroundColor(
                if (isIn) Color.parseColor("#10B981") else Color.parseColor("#3B82F6")
            )
        }
        val col = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val tvTime = TextView(requireContext()).apply {
            text = formatTime(ts).let { if (it == "-") "--:--" else it }
            textSize = 22f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        }
        val tvLabel = TextView(requireContext()).apply {
            text = if (isIn) "Checked In" else "Checked Out"
            textSize = 13f; setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (isIn) Color.parseColor("#10B981") else Color.parseColor("#3B82F6"))
        }
        val meta = listOf(ts.take(10), activity, place).filter { it.isNotBlank() }.joinToString(" · ")
        val tvMeta = TextView(requireContext()).apply {
            text = meta; textSize = 12f; setTextColor(Color.parseColor("#66FFFFFF"))
        }
        col.addView(tvTime); col.addView(tvLabel)
        if (meta.isNotBlank()) col.addView(tvMeta)
        card.addView(strip); card.addView(col)
        return card
    }

    private fun showDatePicker(et: EditText) {
        val cal = Calendar.getInstance()
        try {
            val p = et.text.toString().trim().split("-")
            if (p.size == 3) cal.set(p[0].toInt(), p[1].toInt() - 1, p[2].toInt())
        } catch (_: Exception) {}
        DatePickerDialog(requireContext(), { _, y, m, d ->
            et.setText("$y-${(m + 1).toString().padStart(2, '0')}-${d.toString().padStart(2, '0')}")
        }, cal.get(Calendar.YEAR), cal.get(Calendar.MONTH), cal.get(Calendar.DAY_OF_MONTH)).show()
    }

    private fun formatTime(ts: String?): String {
        if (ts.isNullOrBlank()) return "-"
        return try {
            if (ts.contains("T")) ts.split("T").getOrNull(1)?.take(5) ?: ts
            else if (ts.contains(" ")) ts.split(" ").getOrNull(1)?.take(5) ?: ts
            else ts
        } catch (_: Exception) { ts }
    }
}
