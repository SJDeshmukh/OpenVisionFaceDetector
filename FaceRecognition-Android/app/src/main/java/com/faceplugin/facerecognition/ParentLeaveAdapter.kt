package com.faceplugin.facerecognition

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.google.gson.JsonObject

class ParentLeaveAdapter(
    private val leaves: List<JsonObject>,
    private val onClick: (JsonObject) -> Unit
) : RecyclerView.Adapter<ParentLeaveAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvLeaveReason: TextView = view.findViewById(R.id.tvLeaveReason)
        val tvLeaveStatus: TextView = view.findViewById(R.id.tvLeaveStatus)
        val tvLeaveDate: TextView = view.findViewById(R.id.tvLeaveDate)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_parent_leave, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val leave = leaves[position]
        
        holder.tvLeaveReason.text = leave.get("reason")?.asString ?: "No Reason Provided"
        
        val startDate = leave.get("start_date")?.asString ?: ""
        val endDate = leave.get("end_date")?.asString ?: ""
        
        if (startDate == endDate || endDate.isEmpty()) {
            holder.tvLeaveDate.text = "Date: $startDate"
        } else {
            holder.tvLeaveDate.text = "Date: $startDate to $endDate"
        }

        val status = leave.get("parent_status")?.asString ?: "Pending"
        holder.tvLeaveStatus.text = status.capitalize()

        holder.itemView.setOnClickListener {
            onClick(leave)
        }
    }

    override fun getItemCount() = leaves.size
}
