package com.faceplugin.facerecognition

import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.faceplugin.facerecognition.api.RetrofitClient
import com.google.gson.Gson
import com.google.gson.JsonObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ParentProfileFragment : Fragment() {

    private lateinit var root: View

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        root = inflater.inflate(R.layout.fragment_parent_profile, container, false)
        return root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val prefs = requireActivity().getSharedPreferences("app_prefs", Context.MODE_PRIVATE)
        val studentId = prefs.getString("student_id", "") ?: ""
        val mobile = prefs.getString("parent_mobile_number", "") ?: ""

        root.findViewById<TextView>(R.id.tv_profile_student_id).text =
            "ID: ${studentId.ifBlank { "—" }}"
        root.findViewById<TextView>(R.id.tv_profile_mobile).text =
            "Mobile: ${mobile.ifBlank { "—" }}"

        loadStudentInfo()

        root.findViewById<Button>(R.id.btn_profile_change_face).setOnClickListener {
            showFaceResetConfirmation()
        }
        root.findViewById<Button>(R.id.btn_profile_logout).setOnClickListener {
            (activity as? ParentActivity)?.performLogout()
        }
    }

    private fun loadStudentInfo() {
        if (!isAdded) return
        RetrofitClient.getService().getParentStudentDay(null).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                val body = response.body() ?: return
                val student = try { body.getAsJsonObject("student") } catch (_: Exception) { null }
                val name = try { student?.get("name")?.asString } catch (_: Exception) { null }
                val faceImg = try { student?.get("face_image")?.asString } catch (_: Exception) { null }

                root.findViewById<TextView>(R.id.tv_profile_name).text = name ?: "Student"

                if (!faceImg.isNullOrBlank()) {
                    try {
                        val bytes = android.util.Base64.decode(faceImg, android.util.Base64.DEFAULT)
                        val bmp = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                        if (bmp != null) {
                            root.findViewById<ImageView>(R.id.iv_profile_avatar).setImageBitmap(bmp)
                        }
                    } catch (_: Exception) {}
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {}
        })
    }

    private fun showFaceResetConfirmation() {
        androidx.appcompat.app.AlertDialog.Builder(requireContext())
            .setTitle("Change Registered Face")
            .setMessage("This will delete your current face data and require admin approval. Once approved, you'll be asked to scan your new face.")
            .setPositiveButton("Request Change") { _, _ -> submitFaceResetRequest() }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun submitFaceResetRequest() {
        val body = JsonObject().apply {
            addProperty("reason", "User requested face change from mobile app")
        }
        RetrofitClient.getService().requestFaceReset(body).enqueue(object : Callback<JsonObject> {
            override fun onResponse(call: Call<JsonObject>, response: Response<JsonObject>) {
                if (!isAdded) return
                if (response.isSuccessful) {
                    Toast.makeText(context, "Request sent to admin for approval", Toast.LENGTH_LONG).show()
                } else {
                    val msg = try {
                        Gson().fromJson(response.errorBody()?.string(), JsonObject::class.java)
                            ?.get("error")?.asString ?: "Failed to submit request"
                    } catch (_: Exception) { "Failed to submit request" }
                    Toast.makeText(context, msg, Toast.LENGTH_LONG).show()
                }
            }
            override fun onFailure(call: Call<JsonObject>, t: Throwable) {
                if (isAdded) Toast.makeText(context, "Network error", Toast.LENGTH_SHORT).show()
            }
        })
    }
}
