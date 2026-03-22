package com.faceplugin.facerecognition

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ParentLeaveFragment : Fragment() {

    private lateinit var rvLeaves: RecyclerView
    private lateinit var swipeRefreshLayout: SwipeRefreshLayout
    private lateinit var tvEmptyState: TextView
    private lateinit var progressBar: ProgressBar
    private val leaveList = mutableListOf<JsonObject>()
    private lateinit var adapter: ParentLeaveAdapter

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View? {
        val root = inflater.inflate(R.layout.fragment_parent_leave, container, false)
        rvLeaves = root.findViewById<RecyclerView>(R.id.rvLeaves)
        swipeRefreshLayout = root.findViewById<SwipeRefreshLayout>(R.id.swipeRefreshLayout)
        tvEmptyState = root.findViewById<TextView>(R.id.tvEmptyState)
        progressBar = root.findViewById<ProgressBar>(R.id.progressBar)

        adapter = ParentLeaveAdapter(leaveList) { leaveReq ->
            val intent = Intent(requireContext(), ParentLeaveDetailActivity::class.java)
            intent.putExtra("leave_data", leaveReq.toString())
            startActivity(intent)
        }

        rvLeaves.layoutManager = LinearLayoutManager(requireContext())
        rvLeaves.adapter = adapter

        swipeRefreshLayout.setOnRefreshListener {
            fetchPendingLeaves()
        }

        return root
    }

    override fun onResume() {
        super.onResume()
        fetchPendingLeaves()
    }

    private fun fetchPendingLeaves() {
        if (!isAdded) return
        val prefs = requireActivity().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val studentNumber = prefs.getString("parent_student_number", "") ?: ""

        if (studentNumber.isEmpty()) {
            swipeRefreshLayout.isRefreshing = false
            return
        }

        if (!swipeRefreshLayout.isRefreshing && leaveList.isEmpty()) {
            progressBar.visibility = View.VISIBLE
        }

        RetrofitClient.getService().getParentPendingLeaves(studentNumber).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                progressBar.visibility = View.GONE
                swipeRefreshLayout.isRefreshing = false

                if (response.isSuccessful && response.body() != null) {
                    val requests = response.body()!!.getAsJsonArray("requests") ?: JsonArray()
                    leaveList.clear()
                    for (i in 0 until requests.size()) {
                        leaveList.add(requests.get(i).asJsonObject)
                    }
                    adapter.notifyDataSetChanged()
                    tvEmptyState.visibility = if (leaveList.isEmpty()) View.VISIBLE else View.GONE
                } else {
                    Toast.makeText(context, "Failed to fetch leave requests", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (!isAdded) return
                progressBar.visibility = View.GONE
                swipeRefreshLayout.isRefreshing = false
                Toast.makeText(context, "Network error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }
}
