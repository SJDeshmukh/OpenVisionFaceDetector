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
import android.widget.ArrayAdapter;
import android.widget.AutoCompleteTextView;
import android.widget.Button;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.faceplugin.facerecognition.api.RetrofitClient;
import com.faceplugin.facerecognition.api.ShiftsResponse;
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
    private AutoCompleteTextView etShift;
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
        etShift = view.findViewById(R.id.etShift);
        // Initial empty state while loading
        String[] loadingShifts = new String[] {"Loading shifts..."};
        ArrayAdapter<String> adapter = new ArrayAdapter<>(requireContext(), android.R.layout.simple_dropdown_item_1line, loadingShifts);
        etShift.setAdapter(adapter);
        etShift.setEnabled(false); // Disable until loaded
        
        // Fetch dynamic shifts from backend
        fetchShifts(adapter, etShift);
        
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

    private void fetchShifts(ArrayAdapter<String> adapter, AutoCompleteTextView etShift) {
        RetrofitClient.getService().getShifts().enqueue(new Callback<ShiftsResponse>() {
            @Override
            public void onResponse(Call<ShiftsResponse> call, Response<ShiftsResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    List<String> dynamicShifts = response.body().getShifts();
                    if (dynamicShifts != null && !dynamicShifts.isEmpty()) {
                        adapter.clear();
                        adapter.addAll(dynamicShifts);
                        adapter.notifyDataSetChanged();
                        etShift.setEnabled(true);
                        etShift.setText(dynamicShifts.get(0), false); // Select first by default
                    } else {
                        adapter.clear();
                        adapter.add("No shifts found");
                        adapter.notifyDataSetChanged();
                    }
                }
            }

            @Override
            public void onFailure(Call<ShiftsResponse> call, Throwable t) {
                adapter.clear();
                adapter.add("Failed to load shifts");
                adapter.notifyDataSetChanged();
                t.printStackTrace();
            }
        });
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
            String shift = etShift.getText().toString().trim();
            
            boolean exists = dbManager.personExists(name);
            
            // Save to Local DB (Optimistic UI - marked as not synced)
            // Note: Local DB schema update for 'shift' is pending, so we might lose it locally if we don't update DBManager.
            // But requirement is backend sync. We will send it to backend regardless.
            dbManager.insertPerson(name, faceImage, templates, phone, department, designation, false);
            
            if (exists) {
                Toast.makeText(getContext(), "Updated existing user: " + name, Toast.LENGTH_SHORT).show();
            } else {
                Toast.makeText(getContext(), getString(R.string.person_enrolled) + " " + name, Toast.LENGTH_SHORT).show();
            }

            // Sync to Backend
            syncToBackend(name, templates, faceImage, phone, department, designation, shift);
            
            // Clear inputs
            etName.setText("");
            etMobile.setText("");
            etDepartment.setText("");
            etDesignation.setText("");
            etShift.setText("");
        }
    }

    private void syncToBackend(String name, byte[] templates, Bitmap faceImage, String phone, String department, String designation, String shift) {
        String templatesBase64 = Base64.encodeToString(templates, Base64.NO_WRAP);
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        faceImage.compress(Bitmap.CompressFormat.JPEG, 100, byteArrayOutputStream);
        String faceImageBase64 = Base64.encodeToString(byteArrayOutputStream.toByteArray(), Base64.NO_WRAP);

        SyncRequest syncRequest = new SyncRequest(name, templatesBase64, faceImageBase64, phone, department, designation, shift);
        RetrofitClient.getService().uploadFace(syncRequest).enqueue(new Callback<Void>() {
            @Override
            public void onResponse(Call<Void> call, Response<Void> response) {
                if (response.isSuccessful()) {
                    Toast.makeText(getContext(), "Synced to Cloud", Toast.LENGTH_SHORT).show();
                    if (dbManager != null) {
                        dbManager.updatePersonStatus(name, true);
                    }
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
