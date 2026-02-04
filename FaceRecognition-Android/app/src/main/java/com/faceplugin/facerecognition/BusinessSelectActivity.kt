package com.faceplugin.facerecognition

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.android.material.card.MaterialCardView
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class BusinessSelectActivity : AppCompatActivity() {
    private var allBusinesses: List<BusinessTypeItem> = emptyList()
    private lateinit var businessAdapter: BusinessTypeCardAdapter
    private val legacyLocalUrl = "http://192.0.0.2:5001/"
    private val currentLocalUrl = "https://bolometric-lower-joaquina.ngrok-free.dev/"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_business_select)

        val recycler = findViewById<RecyclerView>(R.id.recycler_businesses)
        val progress = findViewById<ProgressBar>(R.id.progress_businesses)
        val tvError = findViewById<TextView>(R.id.tv_business_error)
        val btnContinue = findViewById<Button>(R.id.btn_business_continue)
        val tvServerUrl = findViewById<TextView>(R.id.tv_business_server_url)

        recycler.layoutManager = LinearLayoutManager(this, LinearLayoutManager.VERTICAL, false)

        val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
        var initialUrl = prefs.getString("server_url", null)
        if (initialUrl == legacyLocalUrl) {
            initialUrl = currentLocalUrl
            prefs.edit().putString("server_url", initialUrl).apply()
        }
        if (!initialUrl.isNullOrBlank()) {
            RetrofitClient.setBaseUrl(initialUrl)
        }
        tvServerUrl.text = "Server: " + RetrofitClient.getBaseUrl()
        tvServerUrl.setOnClickListener {
            showServerUrlDialog(tvServerUrl, progress, tvError, prefs)
        }

        val cached = readCachedBusinessTypes(prefs)
        if (cached.isNotEmpty()) {
            allBusinesses = cached
        }

        var selectedItem: BusinessTypeItem? = null
        businessAdapter = BusinessTypeCardAdapter(
            items = allBusinesses,
            selectedValue = null
        ) { item ->
            selectedItem = item
            btnContinue.isEnabled = true
        }
        recycler.adapter = businessAdapter

        btnContinue.setOnClickListener {
            val chosenValue = selectedItem?.value
            val chosenLabel = selectedItem?.label
            val chosenAllowParentLogin = selectedItem?.allowParentLogin

            val prefs = getSharedPreferences("app_prefs", MODE_PRIVATE)
            val editor = prefs.edit()
            if (!chosenValue.isNullOrBlank()) {
                editor.putString("selected_business_type_code", chosenValue)
                editor.putString("selected_business_type_label", chosenLabel ?: chosenValue)
                editor.putString("selected_business_type", chosenValue)
                editor.putString("selected_vendor_vertical", chosenValue)
                val allow = chosenAllowParentLogin ?: chosenValue.equals("school", true)
                editor.putBoolean("selected_allow_parent_login", allow)
            } else {
                Toast.makeText(this, "Please select a business", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            editor.putString("selected_vendor_set_at", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date()))
            editor.apply()

            val existingVendorId = prefs.getInt("vendor_id", -1)
            val existingSelectedVendorId = prefs.getInt("selected_vendor_id", -1)
            if (existingVendorId != -1 || existingSelectedVendorId != -1) {
                startActivity(Intent(this, LoginActivity::class.java))
                finish()
                return@setOnClickListener
            }

            progress.visibility = View.VISIBLE
            tvError.visibility = View.GONE
            RetrofitClient.getService().getPublicVendors().enqueue(object : Callback<JsonObject> {
                override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                    try {
                        if (response.isSuccessful && response.body() != null) {
                            val root = response.body()!!
                            if (root.has("vendors") && root.get("vendors").isJsonArray) {
                                val vendors = root.getAsJsonArray("vendors")
                                var selectedVendorId: Int? = null
                                for (el in vendors) {
                                    if (!el.isJsonObject) continue
                                    val v = el.asJsonObject
                                    val vertical = if (v.has("vertical") && !v.get("vertical").isJsonNull) v.get("vertical").asString else null
                                    val id = if (v.has("id") && !v.get("id").isJsonNull) v.get("id").asInt else null
                                    if (id != null && !vertical.isNullOrBlank() && vertical.equals(chosenValue, true)) {
                                        selectedVendorId = id
                                        break
                                    }
                                }
                                if (selectedVendorId != null) {
                                    prefs.edit().putInt("selected_vendor_id", selectedVendorId).apply()
                                }
                            }
                        }
                    } catch (_: Exception) {
                    } finally {
                        progress.visibility = View.GONE
                        startActivity(Intent(this@BusinessSelectActivity, LoginActivity::class.java))
                        finish()
                    }
                }

                override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                    progress.visibility = View.GONE
                    startActivity(Intent(this@BusinessSelectActivity, LoginActivity::class.java))
                    finish()
                }
            })
        }

        btnContinue.isEnabled = false

        fetchBusinessTypes(progress, tvError, prefs)
    }

    private fun showServerUrlDialog(
        tvServerUrl: TextView,
        progress: ProgressBar,
        tvError: TextView,
        prefs: android.content.SharedPreferences
    ) {
        val builder = androidx.appcompat.app.AlertDialog.Builder(this)
        builder.setTitle("Set Server URL")

        val input = EditText(this)
        input.setText(prefs.getString("server_url", RetrofitClient.getBaseUrl()) ?: RetrofitClient.getBaseUrl())
        builder.setView(input)

        builder.setPositiveButton("Save") { _, _ ->
            var url = input.text.toString().trim()
            if (url.isNotEmpty()) {
                if (url == legacyLocalUrl) url = currentLocalUrl
                val lower = url.lowercase()
                if (lower.contains(":5173")) {
                    Toast.makeText(this, "Enter backend URL like http://<LAN_IP>:5001", Toast.LENGTH_LONG).show()
                    return@setPositiveButton
                }
                if (!url.endsWith("/")) url += "/"
                prefs.edit().putString("server_url", url).apply()
                RetrofitClient.setBaseUrl(url)
                tvServerUrl.text = "Server: $url"
                fetchBusinessTypes(progress, tvError, prefs)
            }
        }
        builder.setNegativeButton("Cancel") { dialog, _ -> dialog.cancel() }

        builder.show()
    }

    private fun fetchBusinessTypes(
        progress: ProgressBar,
        tvError: TextView,
        prefs: android.content.SharedPreferences
    ) {
        progress.visibility = View.VISIBLE
        tvError.visibility = View.VISIBLE
        tvError.text = if (allBusinesses.isNotEmpty()) "Loading business types..." else "Loading business types..."

        val online = try { NetworkUtils.isOnline(applicationContext) } catch (_: Exception) { false }
        if (!online) {
            progress.visibility = View.GONE
            tvError.visibility = View.VISIBLE
            tvError.text = if (allBusinesses.isNotEmpty()) "Offline: using cached list. Tap Server to change." else "Offline: no cached business types."
            return
        }

        RetrofitClient.getService().getPublicBusinessTypes().enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                progress.visibility = View.GONE
                if (!response.isSuccessful || response.body() == null) {
                    tvError.visibility = View.VISIBLE
                    val base = RetrofitClient.getBaseUrl()
                    tvError.text = if (allBusinesses.isNotEmpty()) "Server unreachable ($base). Using cached list. Tap Server to change." else "Server unreachable ($base)."
                    return
                }
                val body = response.body()!!
                val typesEl = body.get("business_types")
                val types = if (typesEl != null && typesEl.isJsonArray) typesEl.asJsonArray else JsonArray()
                val parsed = mutableListOf<BusinessTypeItem>()
                for (el in types) {
                    try {
                        if (el.isJsonObject) {
                            val obj = el.asJsonObject
                            val value = try { obj.get("value")?.asString } catch (_: Exception) { null }
                            val label = try { obj.get("label")?.asString } catch (_: Exception) { null }
                            val allowParentLogin = try { obj.get("allow_parent_login")?.asBoolean } catch (_: Exception) { null }
                            if (!value.isNullOrBlank()) {
                                val v = value.trim()
                                parsed.add(BusinessTypeItem(v, (label ?: v).trim(), allowParentLogin ?: v.equals("school", true)))
                            }
                        } else if (el.isJsonPrimitive) {
                            val value = try { el.asString } catch (_: Exception) { null }
                            if (!value.isNullOrBlank()) {
                                val v = value.trim()
                                parsed.add(BusinessTypeItem(v, normalizeLabel(v), v.equals("school", true)))
                            }
                        }
                    } catch (_: Exception) {}
                }
                val list = parsed
                    .filter { it.value.isNotBlank() }
                    .distinctBy { it.value.lowercase(Locale.US) }
                    .sortedBy { it.label.lowercase(Locale.US) }
                if (list.isNotEmpty()) {
                    allBusinesses = list
                    businessAdapter.setItems(allBusinesses)
                    businessAdapter.setSelectedValue(null)
                    writeCachedBusinessTypes(prefs, allBusinesses)
                    tvError.visibility = View.VISIBLE
                    tvError.text = "Select a business type."
                } else {
                    tvError.visibility = View.VISIBLE
                    tvError.text = if (allBusinesses.isNotEmpty()) "No business types found on server. Using cached list." else "No business types found on server."
                }
            }

            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                progress.visibility = View.GONE
                tvError.visibility = View.VISIBLE
                val base = RetrofitClient.getBaseUrl()
                tvError.text = if (allBusinesses.isNotEmpty()) "Server unreachable ($base). Using cached list. Tap Server to change." else "Server unreachable ($base)."
            }
        })
    }

    private fun normalizeLabel(raw: String): String {
        val known = mapOf(
            "school" to "School / College / Tuitions",
            "wages" to "Daily Wages / Workforce",
            "factory" to "Industrial / Manufacturing",
            "enterprise" to "Enterprise (Custom)"
        )
        val key = raw.trim().lowercase(Locale.US)
        val mapped = known[key]
        if (!mapped.isNullOrBlank()) return mapped
        val cleaned = raw.trim().replace('_', ' ')
        if (cleaned.isEmpty()) return cleaned
        return cleaned
            .split(' ')
            .filter { it.isNotBlank() }
            .joinToString(" ") { token ->
                token.lowercase(Locale.US).replaceFirstChar { ch ->
                    if (ch.isLowerCase()) ch.titlecase(Locale.US) else ch.toString()
                }
            }
    }

    private fun readCachedBusinessTypes(prefs: android.content.SharedPreferences): List<BusinessTypeItem> {
        val raw = prefs.getString("cached_business_types_json", null) ?: return emptyList()
        if (raw.isBlank()) return emptyList()
        return try {
            val el = JsonParser().parse(raw)
            if (!el.isJsonArray) return emptyList()
            val arr = el.asJsonArray
            val out = mutableListOf<BusinessTypeItem>()
            for (x in arr) {
                if (!x.isJsonObject) continue
                val obj = x.asJsonObject
                val value = try { obj.get("value")?.asString } catch (_: Exception) { null }
                val label = try { obj.get("label")?.asString } catch (_: Exception) { null }
                val allow = try { obj.get("allow_parent_login")?.asBoolean } catch (_: Exception) { null }
                if (!value.isNullOrBlank()) {
                    val v = value.trim()
                    out.add(BusinessTypeItem(v, (label ?: v).trim(), allow ?: v.equals("school", true)))
                }
            }
            out.distinctBy { it.value.lowercase(Locale.US) }.sortedBy { it.label.lowercase(Locale.US) }
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun writeCachedBusinessTypes(prefs: android.content.SharedPreferences, types: List<BusinessTypeItem>) {
        val arr = com.google.gson.JsonArray()
        for (t in types.distinctBy { it.value.lowercase(Locale.US) }) {
            val o = com.google.gson.JsonObject()
            o.addProperty("value", t.value)
            o.addProperty("label", t.label)
            o.addProperty("allow_parent_login", t.allowParentLogin)
            arr.add(o)
        }
        prefs.edit().putString("cached_business_types_json", arr.toString()).apply()
    }

    private data class BusinessTypeItem(val value: String, val label: String, val allowParentLogin: Boolean)

    private class BusinessTypeCardAdapter(
        items: List<BusinessTypeItem>,
        private var selectedValue: String?,
        private val onClick: (BusinessTypeItem) -> Unit
    ) : RecyclerView.Adapter<BusinessTypeCardAdapter.VH>() {

        private var data: List<BusinessTypeItem> = items

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = android.view.LayoutInflater.from(parent.context)
                .inflate(R.layout.item_business_type_card, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val item = data[position]
            val selected = selectedValue != null && item.value.equals(selectedValue, true)
            holder.bind(item, selected) {
                selectedValue = item.value
                notifyDataSetChanged()
                onClick(item)
            }
        }

        override fun getItemCount(): Int = data.size

        fun setItems(items: List<BusinessTypeItem>) {
            data = items
            notifyDataSetChanged()
        }

        fun setSelectedValue(value: String?) {
            selectedValue = value
            notifyDataSetChanged()
        }

        class VH(itemView: View) : RecyclerView.ViewHolder(itemView) {
            private val card = itemView.findViewById<MaterialCardView>(R.id.card_business_type)
            private val label = itemView.findViewById<TextView>(R.id.tv_business_type_label)

            fun bind(item: BusinessTypeItem, selected: Boolean, click: () -> Unit) {
                label.text = item.label
                if (selected) {
                    card.strokeWidth = dp(itemView, 2)
                    card.setStrokeColor(itemView.context.getColor(R.color.vision_text_primary))
                    card.setCardBackgroundColor(itemView.context.getColor(R.color.vision_navy_700))
                } else {
                    card.strokeWidth = dp(itemView, 1)
                    card.setStrokeColor(itemView.context.getColor(R.color.vision_navy_700))
                    card.setCardBackgroundColor(itemView.context.getColor(R.color.vision_navy_800))
                }
                card.setOnClickListener { click() }
            }

            private fun dp(view: View, v: Int): Int {
                return (v * view.resources.displayMetrics.density).toInt()
            }
        }
    }
}
