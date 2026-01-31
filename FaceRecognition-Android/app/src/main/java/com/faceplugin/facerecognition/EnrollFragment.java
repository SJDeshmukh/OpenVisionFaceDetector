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
import android.widget.Spinner;
import android.widget.ArrayAdapter;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.faceplugin.facerecognition.api.RetrofitClient;
import com.faceplugin.facerecognition.api.SyncRequest;
import com.google.android.material.textfield.TextInputEditText;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.ocp.facesdk.FaceBox;
import com.ocp.facesdk.FaceSDK;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.ArrayList;
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
    private Spinner spShift;
    private Button btnProceed;
    private android.widget.LinearLayout containerDetails;
    private com.google.android.material.textfield.TextInputLayout tilName;
    private com.google.android.material.textfield.TextInputLayout tilMobile;
    private com.google.android.material.textfield.TextInputLayout tilDepartment;
    private com.google.android.material.textfield.TextInputLayout tilDesignation;
    private android.widget.LinearLayout llShift;
    private DBManager dbManager;
    private List<String> shiftNames = new ArrayList<>();
    private ArrayAdapter<String> shiftAdapter;
    private java.util.Map<String, View> dynamicViews = new java.util.HashMap<>();
    private java.util.Map<String, String> dynamicFieldConfig = new java.util.HashMap<>();
    private java.util.List<byte[]> capturedTemplates = new java.util.ArrayList<>();
    private java.util.List<String> capturedSideImages = new java.util.ArrayList<>();
    private Bitmap capturedFrontImage = null;
    private int enrollStep = 0;

    private ActivityResultLauncher<Intent> cameraLauncher;
    private ActivityResultLauncher<Intent> galleryLauncher;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_enroll, container, false);

        containerDetails = view.findViewById(R.id.containerDetails);
        etName = view.findViewById(R.id.etName);
        etMobile = view.findViewById(R.id.etMobile);
        etDepartment = view.findViewById(R.id.etDepartment);
        etDesignation = view.findViewById(R.id.etDesignation);
        spShift = view.findViewById(R.id.spShift);
        
        tilName = view.findViewById(R.id.tilName);
        tilMobile = view.findViewById(R.id.tilMobile);
        tilDepartment = view.findViewById(R.id.tilDepartment);
        tilDesignation = view.findViewById(R.id.tilDesignation);
        llShift = view.findViewById(R.id.llShift);
        
        // Hide all fields initially to ensure no default data is shown as per requirement
        if (tilName != null) tilName.setVisibility(View.GONE);
        if (tilMobile != null) tilMobile.setVisibility(View.GONE);
        if (tilDepartment != null) tilDepartment.setVisibility(View.GONE);
        if (tilDesignation != null) tilDesignation.setVisibility(View.GONE);
        if (llShift != null) llShift.setVisibility(View.GONE);
        
        btnProceed = view.findViewById(R.id.btnProceed);
        dbManager = new DBManager(requireContext());
        // dbManager.loadPerson(); // Removed to prevent redundant loading and race conditions with MainActivity

        // Setup Spinner
        shiftNames.add("No Shift"); // Default
        shiftAdapter = new ArrayAdapter<>(requireContext(), android.R.layout.simple_spinner_item, shiftNames);
        shiftAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spShift.setAdapter(shiftAdapter);

        fetchShifts();
        fetchRegistrationConfig();

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
            enrollStep = 0;
            android.widget.Toast.makeText(getContext(), "Look straight", android.widget.Toast.LENGTH_SHORT).show();
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
            String shift = spShift.getSelectedItem() != null ? spShift.getSelectedItem().toString() : "";
            if (shift.equals("No Shift")) shift = "";
            if (enrollStep == 0) {
                float maxSimilarityFront = 0f;
                for (Person p : DBManager.personList) {
                    try {
                        float s = FaceSDK.similarityCalculation(templates, p.templates);
                        if (s > maxSimilarityFront) maxSimilarityFront = s;
                    } catch (Exception ignored) {}
                }
                if (maxSimilarityFront > SettingsActivity.getIdentifyThreshold(requireContext())) {
                    Toast.makeText(getContext(), "Already registered", Toast.LENGTH_SHORT).show();
                    capturedTemplates.clear();
                    capturedSideImages.clear();
                    capturedFrontImage = null;
                    enrollStep = 0;
                    return;
                }
                capturedFrontImage = faceImage;
                capturedTemplates.add(templates);
                enrollStep = 1;
                android.widget.Toast.makeText(getContext(), "Look left", android.widget.Toast.LENGTH_SHORT).show();
                Intent intent = new Intent(requireContext(), CaptureActivity.class);
                intent.putExtra("is_capture_only", true);
                cameraLauncher.launch(intent);
                return;
            } else if (enrollStep == 1) {
                capturedTemplates.add(templates);
                java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
                faceImage.compress(Bitmap.CompressFormat.JPEG, 90, bos);
                capturedSideImages.add(Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP));
                enrollStep = 2;
                android.widget.Toast.makeText(getContext(), "Look right", android.widget.Toast.LENGTH_SHORT).show();
                Intent intent = new Intent(requireContext(), CaptureActivity.class);
                intent.putExtra("is_capture_only", true);
                cameraLauncher.launch(intent);
                return;
            } else if (enrollStep == 2) {
                capturedTemplates.add(templates);
                java.io.ByteArrayOutputStream bos2 = new java.io.ByteArrayOutputStream();
                faceImage.compress(Bitmap.CompressFormat.JPEG, 90, bos2);
                capturedSideImages.add(Base64.encodeToString(bos2.toByteArray(), Base64.NO_WRAP));
            }
            boolean exists = dbManager.personExists(name);
            // Save to Local DB (Optimistic UI - marked as not synced)
            // Note: Local DB schema update for 'shift' is pending, so we might lose it locally if we don't update DBManager.
            // But requirement is backend sync. We will send it to backend regardless.
            dbManager.insertPerson(name, capturedFrontImage, capturedTemplates.get(0), phone, department, designation, shift, false);
            if (exists) {
                Toast.makeText(getContext(), "Updated existing user: " + name, Toast.LENGTH_SHORT).show();
            } else {
                Toast.makeText(getContext(), getString(R.string.person_enrolled) + " " + name, Toast.LENGTH_SHORT).show();
            }

            // Sync to Backend
            JsonObject dynamicData = new JsonObject();
            for (java.util.Map.Entry<String, View> entry : dynamicViews.entrySet()) {
                 View v = entry.getValue();
                 String key = entry.getKey();
                 String value = "";
                 if (v instanceof android.widget.EditText) {
                     value = ((android.widget.EditText) v).getText().toString();
                 } else if (v instanceof Spinner) {
                     Object selected = ((Spinner) v).getSelectedItem();
                     if (selected != null) value = selected.toString();
                 }
                 
                 if ("required".equals(dynamicFieldConfig.get(key)) && value.isEmpty()) {
                      Toast.makeText(getContext(), key + " is required", Toast.LENGTH_SHORT).show();
                      return;
                 }
                 dynamicData.addProperty(key, value);
            }

            com.google.gson.JsonArray templatesListJson = new com.google.gson.JsonArray();
            for (byte[] t : capturedTemplates) {
                templatesListJson.add(Base64.encodeToString(t, Base64.NO_WRAP));
            }
            com.google.gson.JsonArray faceImagesListJson = new com.google.gson.JsonArray();
            for (String imgB64 : capturedSideImages) {
                faceImagesListJson.add(imgB64);
            }
            syncToBackend(name, capturedTemplates.get(0), capturedFrontImage, phone, department, designation, shift, dynamicData, templatesListJson, faceImagesListJson);
            capturedTemplates.clear();
            capturedSideImages.clear();
            capturedFrontImage = null;
            enrollStep = 0;
            
            // Clear inputs
            etName.setText("");
            etMobile.setText("");
            etDepartment.setText("");
            etDesignation.setText("");
            spShift.setSelection(0);
        }
    }

    private void fetchShifts() {
        // First try to fetch list of companies for this vendor
        RetrofitClient.getService().getCompanies().enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(Call<JsonObject> call, Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null) {
                    try {
                        JsonObject root = response.body();
                        if (root.has("companies")) {
                            JsonArray companies = root.getAsJsonArray("companies");
                            if (companies.size() > 0) {
                                // Use the first company found
                                JsonObject firstCompany = companies.get(0).getAsJsonObject();
                                int companyId = firstCompany.get("id").getAsInt();
                                fetchCompanyShifts(companyId);
                                return;
                            }
                        }
                    } catch (Exception e) {
                        e.printStackTrace();
                    }
                }
                // Fallback to default if failed
                fetchCompanyShifts(getDefaultCompanyId());
            }

            @Override
            public void onFailure(Call<JsonObject> call, Throwable t) {
                t.printStackTrace();
                fetchCompanyShifts(getDefaultCompanyId());
            }
        });
    }

    private int getDefaultCompanyId() {
        int companyId = 1;
        if (getContext() != null) {
            android.content.SharedPreferences prefs = getContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE);
            companyId = prefs.getInt("company_id", 1);
        }
        return companyId;
    }

    private void fetchCompanyShifts(int companyId) {
        RetrofitClient.getService().getCompany(companyId).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(Call<JsonObject> call, Response<JsonObject> response) {
                if (response.isSuccessful() && response.body() != null) {
                    try {
                        JsonObject company = response.body();
                        if (company.has("shifts")) {
                            JsonArray shiftsArray = company.getAsJsonArray("shifts");
                            shiftNames.clear();
                            shiftNames.add("No Shift");
                            for (JsonElement s : shiftsArray) {
                                JsonObject shiftObj = s.getAsJsonObject();
                                if (shiftObj.has("name") && shiftObj.has("active") && shiftObj.get("active").getAsBoolean()) {
                                    shiftNames.add(shiftObj.get("name").getAsString());
                                }
                            }
                            if (getActivity() != null) {
                                getActivity().runOnUiThread(() -> shiftAdapter.notifyDataSetChanged());
                            }
                        }
                    } catch (Exception e) {
                        e.printStackTrace();
                    }
                }
            }

            @Override
            public void onFailure(Call<JsonObject> call, Throwable t) {
                t.printStackTrace();
            }
        });
    }

    private void fetchRegistrationConfig() {
        if (!isAdded()) return;
        android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE);
        int vendorId = prefs.getInt("vendor_id", -1);
        if (vendorId == -1) return;

        RetrofitClient.getService().getRegistrationConfig(vendorId).enqueue(new Callback<JsonObject>() {
            @Override
            public void onResponse(Call<JsonObject> call, Response<JsonObject> response) {
                try {
                    if (response.isSuccessful() && response.body() != null) {
                        JsonObject body = response.body();
                        if (body.has("config") && !body.get("config").isJsonNull()) {
                            JsonArray config = body.getAsJsonArray("config");
                            if (getActivity() != null && isAdded()) {
                                getActivity().runOnUiThread(() -> renderDynamicFields(config));
                            }
                        }
                    }
                } catch (Exception e) {
                    e.printStackTrace();
                }
            }

            @Override
            public void onFailure(Call<JsonObject> call, Throwable t) {
                t.printStackTrace();
            }
        });
    }

    private void renderDynamicFields(JsonArray config) {
        android.util.Log.e("AppCrash", "renderDynamicFields started with " + config.size() + " items");
        try {
            if (!isAdded() || getContext() == null) return;
            
            // Standard fields are already hidden in onCreateView

            for (JsonElement el : config) {
                if (!el.isJsonObject()) continue;
                JsonObject field = el.getAsJsonObject();
                if (!field.has("field") || !field.has("type") || !field.has("label")) continue;
                
                String key = field.get("field").getAsString();
                String label = field.get("label").getAsString();
                String type = field.get("type").getAsString();
                boolean required = field.has("required") && field.get("required").getAsBoolean();
    
                dynamicFieldConfig.put(key, required ? "required" : "optional");
    
                // Map standard fields back to existing UI elements
                if (key.equalsIgnoreCase("name") || key.equalsIgnoreCase("full_name")) {
                    if (tilName != null) {
                        tilName.setHint(label);
                        tilName.setVisibility(View.VISIBLE);
                    }
                    continue; 
                }
                if (key.equalsIgnoreCase("phone") || key.equalsIgnoreCase("mobile") || key.equalsIgnoreCase("phone_number")) {
                    if (tilMobile != null) {
                        tilMobile.setHint(label);
                        tilMobile.setVisibility(View.VISIBLE);
                    }
                    continue;
                }
                if (key.equalsIgnoreCase("department")) {
                    if (tilDepartment != null) {
                        tilDepartment.setHint(label);
                        tilDepartment.setVisibility(View.VISIBLE);
                    }
                    continue;
                }
                if (key.equalsIgnoreCase("designation")) {
                    if (tilDesignation != null) {
                        tilDesignation.setHint(label);
                        tilDesignation.setVisibility(View.VISIBLE);
                    }
                    continue;
                }
                if (key.equalsIgnoreCase("shift")) {
                    if (llShift != null) {
                        llShift.setVisibility(View.VISIBLE);
                    }
                    continue;
                }

                if (dynamicViews.containsKey(key)) continue;
    
                if (type.equals("text") || type.equals("number")) {
                    com.google.android.material.textfield.TextInputLayout til = new com.google.android.material.textfield.TextInputLayout(requireContext());
                    til.setLayoutParams(new android.widget.LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT));
                    til.setHint(label);
                    til.setBoxBackgroundMode(com.google.android.material.textfield.TextInputLayout.BOX_BACKGROUND_OUTLINE);
                    // Note: Using hardcoded colors for simplicity as accessing R.color from context requires more verbose code or ensure imports
                    // But we are in Fragment, so requireContext() works.
                    // Assuming R.color.vision_blue exists as per existing XML.
                    
                    android.widget.LinearLayout.LayoutParams params = (android.widget.LinearLayout.LayoutParams) til.getLayoutParams();
                    params.setMargins(0, 0, 0, (int)(16 * getResources().getDisplayMetrics().density));
                    til.setLayoutParams(params);

                    com.google.android.material.textfield.TextInputEditText et = new com.google.android.material.textfield.TextInputEditText(til.getContext());
                    et.setLayoutParams(new android.widget.LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT));
                    et.setInputType(type.equals("number") ? android.text.InputType.TYPE_CLASS_NUMBER : android.text.InputType.TYPE_CLASS_TEXT);

                    til.addView(et);
                    containerDetails.addView(til);
                    dynamicViews.put(key, et);
                } else if (type.equals("select")) {
                    android.widget.TextView tv = new android.widget.TextView(requireContext());
                    tv.setText(label);
                    containerDetails.addView(tv);
    
                    Spinner spinner = new Spinner(requireContext());
                    List<String> options = new ArrayList<>();
                    if (field.has("options") && field.get("options").isJsonArray()) {
                        JsonArray opts = field.getAsJsonArray("options");
                        for (JsonElement o : opts) options.add(o.getAsString());
                    }
                    
                    ArrayAdapter<String> adapter = new ArrayAdapter<>(requireContext(), android.R.layout.simple_spinner_item, options);
                    adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
                    spinner.setAdapter(adapter);
                    
                    android.widget.LinearLayout.LayoutParams params = new android.widget.LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            (int)(48 * getResources().getDisplayMetrics().density));
                    params.setMargins(0, 8, 0, 32);
                    spinner.setLayoutParams(params);
    
                    containerDetails.addView(spinner);
                    dynamicViews.put(key, spinner);
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
            if (getActivity() != null) {
                Toast.makeText(getActivity(), "Error rendering fields: " + e.getMessage(), Toast.LENGTH_SHORT).show();
            }
        }
    }

    private void syncToBackend(String name, byte[] templates, Bitmap faceImage, String phone, String department, String designation, String shift, JsonObject dynamicData, com.google.gson.JsonArray templatesListJson, com.google.gson.JsonArray faceImagesListJson) {
        String templatesBase64 = Base64.encodeToString(templates, Base64.NO_WRAP);
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        faceImage.compress(Bitmap.CompressFormat.JPEG, 100, byteArrayOutputStream);
        String faceImageBase64 = Base64.encodeToString(byteArrayOutputStream.toByteArray(), Base64.NO_WRAP);

        JsonObject json = new JsonObject();
        json.addProperty("name", name);
        json.addProperty("templates", templatesBase64);
        if (templatesListJson != null) {
            json.add("templates_list", templatesListJson);
        }
        if (faceImagesListJson != null) {
            json.add("face_images_list", faceImagesListJson);
        }
        json.addProperty("face_image", faceImageBase64);
        json.addProperty("phone", phone);
        json.addProperty("department", department);
        json.addProperty("designation", designation);
        json.addProperty("shift", shift);
        
        // Add dynamic fields
        for (String key : dynamicData.keySet()) {
            json.add(key, dynamicData.get(key));
        }

        RetrofitClient.getService().uploadFace(json).enqueue(new Callback<Void>() {
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
