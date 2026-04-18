package com.faceplugin.facerecognition

import android.content.Context
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

class OwnerAdvanceFragment : Fragment() {

    private lateinit var root: View
    private lateinit var advancesContainer: LinearLayout
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var tvNoAdvances: TextView

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        root = inflater.inflate(R.layout.fragment_owner_advances, container, false)
        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        advancesContainer = view.findViewById(R.id.advances_container)
        swipeRefresh = view.findViewById(R.id.swipe_refresh_advances)
        tvNoAdvances = view.findViewById(R.id.tv_no_advances)

        swipeRefresh.setOnRefreshListener {
            fetchAdvances()
        }

        fetchAdvances()
    }

    private fun fetchAdvances() {
        if (!isAdded) return
        swipeRefresh.isRefreshing = true
        
        RetrofitClient.getService().getOwnerAdvances().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                swipeRefresh.isRefreshing = false
                
                if (response.isSuccessful && response.body()?.get("status")?.asString == "success") {
                    val advances = response.body()?.getAsJsonArray("advances")
                    advancesContainer.removeAllViews()
                    
                    if (advances == null || advances.size() == 0) {
                        tvNoAdvances.visibility = View.VISIBLE
                        return
                    }
                    
                    tvNoAdvances.visibility = View.GONE
                    for (i in 0 until advances.size()) {
                        val advance = advances.get(i).asJsonObject
                        val status = advance.get("status")?.asString ?: "pending"
                        if (status == "pending") {
                            advancesContainer.addView(createAdvanceCard(advance))
                        }
                    }
                    
                    if (advancesContainer.childCount == 0) {
                        tvNoAdvances.visibility = View.VISIBLE
                    }
                } else {
                    Toast.makeText(context, "Failed to load advances", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                swipeRefresh.isRefreshing = false
                Toast.makeText(context, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun createAdvanceCard(advance: JsonObject): View {
        val view = LayoutInflater.from(requireContext()).inflate(R.layout.item_owner_advance, advancesContainer, false)
        
        val tvName = view.findViewById<TextView>(R.id.tv_advance_employee_name)
        val tvDate = view.findViewById<TextView>(R.id.tv_advance_date)
        val tvAmount = view.findViewById<TextView>(R.id.tv_advance_amount)
        val tvType = view.findViewById<TextView>(R.id.tv_advance_type)
        val btnApprove = view.findViewById<Button>(R.id.btn_approve_advance)
        val btnReject = view.findViewById<Button>(R.id.btn_reject_advance)
        
        val id = advance.get("id").asInt
        val employeeName = advance.get("name")?.asString ?: "Unknown"
        val date = advance.get("date")?.asString ?: "-"
        val amount = advance.get("amount")?.asDouble ?: 0.0
        val amountCash = advance.get("amount_cash")?.asDouble ?: 0.0
        val amountOnline = advance.get("amount_online")?.asDouble ?: 0.0
        
        tvName.text = employeeName
        tvDate.text = "Requested on: $date"
        tvAmount.text = "₹${String.format("%.2f", amount)}"
        
        val typeStr = StringBuilder()
        if (amountOnline > 0) typeStr.append("Online: ₹${String.format("%.2f", amountOnline)}")
        if (amountCash > 0) {
            if (typeStr.isNotEmpty()) typeStr.append(" | ")
            typeStr.append("Cash: ₹${String.format("%.2f", amountCash)}")
        }
        tvType.text = typeStr.toString()

        btnApprove.setOnClickListener {
            updateAdvance(id, "approve")
        }
        
        btnReject.setOnClickListener {
            showRejectDialog(id)
        }
        
        return view
    }

    private fun updateAdvance(id: Int, action: String, reason: String? = null) {
        val body = JsonObject()
        body.addProperty("advance_id", id)
        if (reason != null) body.addProperty("rejection_reason", reason)
        
        val call = if (action == "approve") {
            RetrofitClient.getService().approveOwnerAdvance(body)
        } else {
            RetrofitClient.getService().rejectOwnerAdvance(body)
        }
        
        call.enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                if (response.isSuccessful && response.body()?.get("status")?.asString == "success") {
                    Toast.makeText(context, "Advance $action" + "d", Toast.LENGTH_SHORT).show()
                    fetchAdvances()
                } else {
                    Toast.makeText(context, "Action failed", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                Toast.makeText(context, "Network error", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun showRejectDialog(id: Int) {
        val builder = androidx.appcompat.app.AlertDialog.Builder(requireContext())
        builder.setTitle("Reject Advance")
        
        val input = EditText(requireContext())
        input.hint = "Reason for rejection"
        builder.setView(input)
        
        builder.setPositiveButton("Reject") { _, _ ->
            val reason = input.text.toString().trim()
            if (reason.isEmpty()) {
                Toast.makeText(context, "Please provide a reason", Toast.LENGTH_SHORT).show()
            } else {
                updateAdvance(id, "reject", reason)
            }
        }
        builder.setNegativeButton("Cancel") { dialog, _ -> dialog.cancel() }
        builder.show()
    }
}
