package com.faceplugin.facerecognition;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.util.Base64;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.faceplugin.facerecognition.api.RetrofitClient;
import com.faceplugin.facerecognition.api.SyncRequest;
import com.google.android.material.textfield.TextInputEditText;
import com.ocp.facesdk.FaceBox;
import com.ocp.facesdk.FaceSDK;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.List;
import java.util.Random;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class EnrollFragment extends Fragment {

    private TextInputEditText etName;
    private TextInputEditText etMobile;
    private TextInputEditText etDepartment;
    private TextInputEditText etDesignation;
    private Button btnProceed;
    private DBManager dbManager;

    private ActivityResultLauncher<Intent> cameraLauncher;
    private ActivityResultLauncher<Intent> galleryLauncher;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_enroll, container, false);

        etName = view.findViewById(R.id.etName);
        etMobile = view.findViewById(R.id.etMobile);
        etDepartment = view.findViewById(R.id.etDepartment);
        etDesignation = view.findViewById(R.id.etDesignation);
        btnProceed = view.findViewById(R.id.btnProceed);
        dbManager = new DBManager(requireContext());
        dbManager.loadPerson();

        // Initialize Launchers
        cameraLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
                        String imageUriString = result.getData().getStringExtra("image_uri");
                        if (imageUriString != null) {
                            Uri imageUri = Uri.parse(imageUriString);
                            // Process in background to avoid UI blocking/ANR
                            new Thread(() -> {
                                try {
                                    Bitmap bitmap = Utils.getCorrectlyOrientedImage(requireContext(), imageUri);
                                    if (bitmap != null) {
                                        getActivity().runOnUiThread(() -> processImage(bitmap));
                                    } else {
                                        getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Failed to load image bitmap", Toast.LENGTH_SHORT).show());
                                    }
                                } catch (Exception e) {
                                    e.printStackTrace();
                                    getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Failed to load image", Toast.LENGTH_SHORT).show());
                                }
                            }).start();
                        } else {
                            Bundle extras = result.getData().getExtras();
                            if (extras != null) {
                                Bitmap imageBitmap = (Bitmap) extras.get("data");
                                if (imageBitmap != null) {
                                    processImage(imageBitmap);
                                }
                            }
                        }
                    }
                }
        );

        galleryLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
                        Uri selectedImage = result.getData().getData();
                        try {
                            Bitmap bitmap = Utils.getCorrectlyOrientedImage(requireContext(), selectedImage);
                            processImage(bitmap);
                        } catch (IOException e) {
                            e.printStackTrace();
                        }
                    }
                }
        );

        btnProceed.setOnClickListener(v -> {
            String name = etName.getText().toString().trim();
            if (TextUtils.isEmpty(name)) {
                etName.setError("Name is required");
                return;
            }

            // Launch Camera (or Dialog to choose Camera/Gallery)
            // For now, let's just launch Camera for "Screen 2" requirement
            Intent intent = new Intent(requireContext(), CaptureActivity.class);
            intent.putExtra("is_capture_only", true);
            cameraLauncher.launch(intent);
        });

        return view;
    }

    private void processImage(Bitmap bitmap) {
        // Run Face Detection
        List<FaceBox> faceBoxes = FaceSDK.faceDetection(bitmap, null);

        if (faceBoxes == null || faceBoxes.isEmpty()) {
            Toast.makeText(getContext(), getString(R.string.no_face_detected), Toast.LENGTH_SHORT).show();
        } else if (faceBoxes.size() > 1) {
            Toast.makeText(getContext(), getString(R.string.multiple_face_detected), Toast.LENGTH_SHORT).show();
        } else {
            FaceBox faceBox = faceBoxes.get(0);
            Bitmap faceImage = Utils.cropFace(bitmap, faceBox);
            byte[] templates = FaceSDK.templateExtraction(bitmap, faceBox);

            String name = etName.getText().toString().trim();
            if (name.isEmpty()) {
                name = "Person" + new Random().nextInt(10000);
            }
            String phone = etMobile.getText().toString().trim();
            String department = etDepartment.getText().toString().trim();
            String designation = etDesignation.getText().toString().trim();
            
            // Save to Local DB
            dbManager.insertPerson(name, faceImage, templates, phone, department, designation);
            Toast.makeText(getContext(), getString(R.string.person_enrolled) + " " + name, Toast.LENGTH_SHORT).show();

            // Sync to Backend
            syncToBackend(name, templates, faceImage, phone, department, designation);
            
            // Clear inputs
            etName.setText("");
            etMobile.setText("");
            etDepartment.setText("");
            etDesignation.setText("");
        }
    }

    private void syncToBackend(String name, byte[] templates, Bitmap faceImage, String phone, String department, String designation) {
        String templatesBase64 = Base64.encodeToString(templates, Base64.NO_WRAP);
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        faceImage.compress(Bitmap.CompressFormat.JPEG, 100, byteArrayOutputStream);
        String faceImageBase64 = Base64.encodeToString(byteArrayOutputStream.toByteArray(), Base64.NO_WRAP);

        SyncRequest syncRequest = new SyncRequest(name, templatesBase64, faceImageBase64, phone, department, designation);
        RetrofitClient.getService().uploadFace(syncRequest).enqueue(new Callback<Void>() {
            @Override
            public void onResponse(Call<Void> call, Response<Void> response) {
                if (response.isSuccessful()) {
                    Toast.makeText(getContext(), "Synced to Cloud", Toast.LENGTH_SHORT).show();
                } else {
                     Toast.makeText(getContext(), "Sync Failed: " + response.code(), Toast.LENGTH_SHORT).show();
                }
            }

            @Override
            public void onFailure(Call<Void> call, Throwable t) {
                t.printStackTrace();
                Toast.makeText(getContext(), "Sync Error", Toast.LENGTH_SHORT).show();
            }
        });
    }
}
