package com.faceplugin.facerecognition

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class OwnerInsightsFragment : Fragment() {

    private lateinit var root: View
    private lateinit var tvEmployees: TextView
    private lateinit var tvPendingAdvances: TextView
    private lateinit var tvMonthTotal: TextView
    private lateinit var tvActiveShifts: TextView
    private lateinit var activityContainer: LinearLayout

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        root = inflater.inflate(R.layout.fragment_owner_insights, container, false)
        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        
        tvEmployees = view.findViewById(R.id.tv_insight_employees)
        tvPendingAdvances = view.findViewById(R.id.tv_insight_pending_advances)
        tvMonthTotal = view.findViewById(R.id.tv_insight_month_total)
        tvActiveShifts = view.findViewById(R.id.tv_insight_active_shifts)
        activityContainer = view.findViewById(R.id.insights_activity_container)

        fetchInsights()
    }

    private fun fetchInsights() {
        if (!isAdded) return
        
        RetrofitClient.getService().getOwnerInsights().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                
                if (response.isSuccessful && response.body()?.get("status")?.asString == "success") {
                    val data = response.body()
                    val stats = data?.getAsJsonObject("stats")
                    
                    if (stats != null) {
                        tvEmployees.text = stats.get("total_employees")?.asString ?: "0"
                        tvPendingAdvances.text = stats.get("pending_advances_count")?.asString ?: "0"
                        tvMonthTotal.text = String.format("₹%.2f", stats.get("total_advances_month")?.asDouble ?: 0.0)
                        tvActiveShifts.text = stats.get("active_shifts_count")?.asString ?: "0"
                    }
                    
                    val activities = data?.getAsJsonArray("recent_activity")
                    activityContainer.removeAllViews()
                    
                    if (activities != null && activities.size() > 0) {
                        for (i in 0 until activities.size()) {
                            val activity = activities.get(i).asJsonObject
                            activityContainer.addView(createActivityView(activity))
                        }
                    } else {
                        val tv = TextView(context)
                        tv.text = "No recent activity"
                        tv.setTextColor(resources.getColor(R.color.vision_text_secondary, null))
                        tv.setPadding(0, 32, 0, 32)
                        tv.gravity = android.view.Gravity.CENTER
                        activityContainer.addView(tv)
                    }
                } else {
                    Toast.makeText(context, "Failed to load insights", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                Toast.makeText(context, "Network error", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun createActivityView(activity: JsonObject): View {
        val view = LinearLayout(context)
        view.orientation = LinearLayout.VERTICAL
        view.setPadding(0, 12, 0, 12)
        
        val tvAction = TextView(context)
        tvAction.text = activity.get("action")?.asString ?: ""
        tvAction.setTextColor(resources.getColor(R.color.vision_text_primary, null))
        tvAction.textSize = 14f
        tvAction.textStyle = android.graphics.Typeface.BOLD
        
        val tvMeta = TextView(context)
        val timestamp = activity.get("timestamp")?.asString ?: ""
        val details = activity.get("details")?.asString ?: ""
        tvMeta.text = "$timestamp • $details"
        tvMeta.setTextColor(resources.getColor(R.color.vision_text_secondary, null))
        tvMeta.textSize = 12f
        
        view.addView(tvAction)
        view.addView(tvMeta)
        
        // Add divider line
        val divider = View(context)
        val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 1)
        lp.topMargin = 12
        divider.layoutParams = lp
        divider.setBackgroundColor(resources.getColor(R.color.vision_navy_800, null))
        view.addView(divider)
        
        return view
    }
}
