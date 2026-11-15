package com.faceplugin.facerecognition;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.util.Base64;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.io.ByteArrayOutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

import com.faceplugin.faceengine.FaceBox;
import com.faceplugin.facerecognition.api.GreetingService;
import com.faceplugin.facerecognition.api.RetrofitClient;
import com.faceplugin.facerecognition.api.UploadFaceResponse;
import com.google.gson.JsonObject;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class UsersFragment extends Fragment {

    private RecyclerView recyclerView;
    private UserAdapter adapter;
    private DBManager dbManager;
    private ActivityResultLauncher<Intent> cameraLauncher;
    private Person pendingPersonForRegistration;

    private EditText etSearch;
    private ImageView btnClearSearch;
    private TextView tvUserCount;
    private View llEmptyState;
    private TextView tvEmptyMessage;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        cameraLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
                        String imageUriString = result.getData().getStringExtra("image_uri");
                        byte[] capturedTemplate = result.getData().getByteArrayExtra("face_template");
                        boolean capturedVerified = result.getData().getBooleanExtra("face_verified", false);
                        if (imageUriString != null) {
                            Uri imageUri = Uri.parse(imageUriString);
                            new Thread(() -> {
                                try {
                                    Bitmap bitmap = Utils.getCorrectlyOrientedImage(requireContext(), imageUri);
                                    if (bitmap != null) {
                                        if (getActivity() != null) getActivity().runOnUiThread(() ->
                                                processCameraResult(bitmap, capturedTemplate, capturedVerified));
                                    } else {
                                        if (getActivity() != null) getActivity().runOnUiThread(() -> Toast.makeText(getContext(), "Failed to load image", Toast.LENGTH_SHORT).show());
                                    }
                                } catch (Exception e) {
                                    e.printStackTrace();
                                }
                            }).start();
                        } else {
                            Bundle extras = result.getData().getExtras();
                            if (extras != null) {
                                Bitmap imageBitmap = (Bitmap) extras.get("data");
                                if (imageBitmap != null) {
                                    processCameraResult(imageBitmap, capturedTemplate, capturedVerified);
                                }
                            }
                        }
                    }
                }
        );
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_users, container, false);
        
        dbManager = new DBManager(requireContext().getApplicationContext());

        etSearch = view.findViewById(R.id.et_search);
        btnClearSearch = view.findViewById(R.id.btn_clear_search);
        tvUserCount = view.findViewById(R.id.tv_user_count);
        llEmptyState = view.findViewById(R.id.ll_empty_state);
        tvEmptyMessage = view.findViewById(R.id.tv_empty_message);

        recyclerView = view.findViewById(R.id.recycler_users);
        recyclerView.setLayoutManager(new GridLayoutManager(getContext(), 2));
        
        if (DBManager.personList != null) {
             adapter = new UserAdapter(DBManager.personList, dbManager);
             adapter.setOnUserDeleteListener(new UserAdapter.OnUserDeleteListener() {
                 @Override
                 public void onDeleteUser(Person person, int position) {
                     showDeleteConfirmationDialog(person, position);
                 }
             });

             // Quick click to register or re-register/update face
             adapter.setOnUserClickListener((person, position) -> {
                 boolean hasFace = (person.templates != null && person.templates.length > 0);
                 String title = hasFace ? "Update Face" : "Register Face";
                 String message = hasFace
                         ? "Face is already registered for " + person.name + ".\n\nWould you like to capture a new photo and update their face?"
                         : "No face registered for " + person.name + ".\n\nWould you like to capture and register their face now?";
                 String actionBtn = hasFace ? "Update Face" : "Register Face";

                 new AlertDialog.Builder(getContext())
                         .setTitle(title)
                         .setMessage(message)
                         .setPositiveButton(actionBtn, (dialog, which) -> {
                             pendingPersonForRegistration = person;
                             Intent intent = new Intent(requireContext(), CaptureActivity.class);
                             intent.putExtra("is_capture_only", true);
                             cameraLauncher.launch(intent);
                         })
                         .setNegativeButton("Cancel", null)
                         .show();
             });

             adapter.setOnFilterResultListener(this::updateCountAndEmptyState);
             recyclerView.setAdapter(adapter);
             updateCountAndEmptyState(adapter.getItemCount());
        }

        // Search text watcher for real-time filtering
        if (etSearch != null) {
            etSearch.addTextChangedListener(new TextWatcher() {
                @Override
                public void beforeTextChanged(CharSequence s, int start, int count, int after) {}

                @Override
                public void onTextChanged(CharSequence s, int start, int before, int count) {
                    if (btnClearSearch != null) {
                        btnClearSearch.setVisibility(s != null && s.length() > 0 ? View.VISIBLE : View.GONE);
                    }
                    if (adapter != null) {
                        adapter.filter(s != null ? s.toString() : "");
                    }
                }

                @Override
                public void afterTextChanged(Editable s) {}
            });
        }

        if (btnClearSearch != null) {
            btnClearSearch.setOnClickListener(v -> {
                if (etSearch != null) {
                    etSearch.setText("");
                    if (getContext() != null) {
                        InputMethodManager imm = (InputMethodManager) getContext().getSystemService(Activity.INPUT_METHOD_SERVICE);
                        if (imm != null) imm.hideSoftInputFromWindow(etSearch.getWindowToken(), 0);
                    }
                }
            });
        }

        return view;
    }

    private void updateCountAndEmptyState(int count) {
        if (tvUserCount != null) {
            tvUserCount.setText(count + (count == 1 ? " User" : " Users"));
        }
        if (llEmptyState != null && recyclerView != null) {
            if (count == 0) {
                llEmptyState.setVisibility(View.VISIBLE);
                recyclerView.setVisibility(View.GONE);
                String q = (etSearch != null && etSearch.getText() != null) ? etSearch.getText().toString().trim() : "";
                if (tvEmptyMessage != null) {
                    tvEmptyMessage.setText(q.isEmpty() ? "No registered users" : "No users found matching \"" + q + "\"");
                }
            } else {
                llEmptyState.setVisibility(View.GONE);
                recyclerView.setVisibility(View.VISIBLE);
            }
        }
    }

    private void showDeleteConfirmationDialog(Person person, int position) {
        new AlertDialog.Builder(getContext())
                .setTitle("Delete User")
                .setMessage("Are you sure you want to delete " + person.name + "?")
                .setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface dialog, int which) {
                        deleteUser(person, position);
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void deleteUser(Person person, int position) {
        // 1. Delete thoroughly from Local DB & in-memory cache
        if (person.id != null && !person.id.isEmpty()) {
            dbManager.deletePersonById(person.id);
        }
        if (person.localUid != null && !person.localUid.isEmpty()) {
            dbManager.deletePersonByLocalUid(person.localUid);
        }
        if ((person.id == null || person.id.isEmpty()) && (person.localUid == null || person.localUid.isEmpty())) {
            dbManager.deletePerson(person.name);
        }
        
        // 2. Update UI
        if (adapter != null) adapter.removeUser(person);
        Toast.makeText(getContext(), "Deleted locally", Toast.LENGTH_SHORT).show();

        if (person != null && !person.synced) {
            return;
        }

        boolean online = false;
        try {
            online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
        } catch (Exception ignored) {}

        android.content.SharedPreferences prefs = requireContext().getApplicationContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE);
        String baseUrl = prefs.getString("server_url", RetrofitClient.getBaseUrl());
        String token = prefs.getString("token", null);
        if (baseUrl != null) RetrofitClient.setBaseUrl(baseUrl);
        if (token != null) RetrofitClient.setAuthToken(token);

        if (token == null || token.trim().isEmpty() || !online) {
            queueDelete(person);
            try {
                DeleteSyncWorker.Companion.scheduleImmediate(requireContext().getApplicationContext());
            } catch (Exception ignored) {}
            return;
        }

        GreetingService service = RetrofitClient.getService();
        boolean hasId = person.id != null && !person.id.trim().isEmpty();
        Call<Void> call = hasId ? service.deleteFaceById(person.id) : service.deleteFace(person.name);
        call.enqueue(new Callback<Void>() {
            @Override
            public void onResponse(Call<Void> call, Response<Void> response) {
                if (response.isSuccessful() || response.code() == 404) {
                    if (getActivity() != null) {
                        Toast.makeText(getContext(), "Deleted from cloud", Toast.LENGTH_SHORT).show();
                    }
                } else {
                    queueDelete(person);
                    try {
                        DeleteSyncWorker.Companion.scheduleImmediate(requireContext().getApplicationContext());
                    } catch (Exception ignored) {}
                }
            }

            @Override
            public void onFailure(Call<Void> call, Throwable t) {
                queueDelete(person);
                try {
                    DeleteSyncWorker.Companion.scheduleImmediate(requireContext().getApplicationContext());
                } catch (Exception ignored) {}
            }
        });
    }

    private void queueDelete(Person person) {
        try {
            String pid = (person != null && person.id != null) ? person.id : null;
            String localUid = (person != null && person.localUid != null) ? person.localUid : null;
            String name = (person != null && person.name != null) ? person.name : null;
            String ts = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(new Date());
            dbManager.insertDeleteQueue(pid, localUid, name, ts);
        } catch (Exception ignored) {}
    }
    
    @Override
    public void onResume() {
        super.onResume();
        if (!isHidden()) {
            refreshList();
        }
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        if (!hidden) {
            refreshList();
        }
    }

    public void refreshList() {
        if (adapter != null) {
            adapter.replaceUsers(DBManager.personList);
            updateCountAndEmptyState(adapter.getItemCount());
        }
    }

    private void processCameraResult(Bitmap bitmap, byte[] capturedTemplate, boolean capturedVerified) {
        if (pendingPersonForRegistration == null) return;
        List<FaceBox> faceBoxes = LocalFaceEngineFacade.INSTANCE.faceDetection(
                bitmap, FacePipeline.enrollmentDetectionParams(requireContext()));
        boolean hasCapturedTemplate = capturedVerified
                && capturedTemplate != null && capturedTemplate.length > 0;

        if ((faceBoxes == null || faceBoxes.isEmpty()) && !hasCapturedTemplate) {
            Toast.makeText(getContext(), getString(R.string.no_face_detected), Toast.LENGTH_SHORT).show();
            return;
        } else if (faceBoxes.size() > 1 && !hasCapturedTemplate) {
            Toast.makeText(getContext(), getString(R.string.multiple_face_detected), Toast.LENGTH_SHORT).show();
            return;
        }
        
        FaceBox faceBox = faceBoxes == null || faceBoxes.isEmpty() ? null : faceBoxes.get(0);
        if (!hasCapturedTemplate && !FacePipeline.recognitionReady(
                requireContext(), faceBox, bitmap.getWidth(), bitmap.getHeight(), true)) {
            Toast.makeText(getContext(), "A clear front-facing face is required", Toast.LENGTH_SHORT).show();
            return;
        }
        Bitmap faceImage = faceBox == null ? bitmap : Utils.cropFace(bitmap, faceBox);
        byte[] templates = hasCapturedTemplate ? capturedTemplate
                : LocalFaceEngineFacade.INSTANCE.templateExtraction(bitmap, faceBox);
        
        if (templates == null) {
            Toast.makeText(getContext(), "Failed to extract face template", Toast.LENGTH_SHORT).show();
            return;
        }

        // Duplication check
        float maxSimilarity = 0f;
        Person[] people;
        synchronized (DBManager.personList) {
            people = DBManager.personList.toArray(new Person[0]);
        }
        Person matchedPerson = null;
        for (Person p : people) {
            if (p == null) continue;
            if (p.localUid != null && p.localUid.equals(pendingPersonForRegistration.localUid)) continue;
            if (p.id != null && pendingPersonForRegistration.id != null && p.id.equals(pendingPersonForRegistration.id)) continue;
            try {
                if (p.templates != null && p.templates.length > 0) {
                    float s = LocalFaceEngineFacade.INSTANCE.similarityCalculation(templates, p.templates);
                    if (s > maxSimilarity) {
                        maxSimilarity = s;
                        matchedPerson = p;
                    }
                }
            } catch (Exception ignored) {}
        }

        if (maxSimilarity > SettingsActivity.getIdentifyThreshold(requireContext())) {
            String matchedName = (matchedPerson != null && matchedPerson.name != null) ? matchedPerson.name : "someone else";
            Toast.makeText(getContext(), "This face is already registered to: " + matchedName, Toast.LENGTH_LONG).show();
            return;
        }

        final Person targetPerson = pendingPersonForRegistration;
        pendingPersonForRegistration = null;

        boolean isOnline = false;
        try {
            isOnline = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
        } catch (Exception ignored) {}

        boolean cloudSync = "true".equalsIgnoreCase(
                requireContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE)
                        .getString("cloud_sync", "true"));

        if (isOnline && cloudSync) {
            Toast.makeText(getContext(), "Validating face for " + targetPerson.name + "...", Toast.LENGTH_SHORT).show();
            syncFaceToBackend(targetPerson, templates, faceImage);
        } else {
            dbManager.updatePersonFaceByLocalUid(targetPerson.localUid, faceImage, templates, false);
            if (adapter != null) adapter.invalidateFace(targetPerson);
            Toast.makeText(getContext(), "Registered face locally (Offline); will sync when online", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    public void onDestroyView() {
        if (adapter != null) {
            adapter.release();
            adapter = null;
        }
        if (recyclerView != null) {
            recyclerView.setAdapter(null);
            recyclerView = null;
        }
        super.onDestroyView();
    }

    private void syncFaceToBackend(Person person, byte[] templates, Bitmap faceImage) {
        String templatesBase64 = Base64.encodeToString(templates, Base64.NO_WRAP);
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        
        Bitmap uploadBmp = faceImage;
        boolean needsRecycle = false;
        if (faceImage != null) {
            int maxDim = Math.max(faceImage.getWidth(), faceImage.getHeight());
            if (maxDim > 480) {
                float scale = 480f / maxDim;
                int w = Math.round(faceImage.getWidth() * scale);
                int h = Math.round(faceImage.getHeight() * scale);
                uploadBmp = Bitmap.createScaledBitmap(faceImage, w, h, true);
                needsRecycle = true;
            }
            uploadBmp.compress(Bitmap.CompressFormat.JPEG, 80, byteArrayOutputStream);
            if (needsRecycle && uploadBmp != faceImage) {
                uploadBmp.recycle();
            }
        }
        String faceImageBase64 = Base64.encodeToString(byteArrayOutputStream.toByteArray(), Base64.NO_WRAP);

        JsonObject json = new JsonObject();
        if (person.id != null && !person.id.isEmpty()) {
            json.addProperty("person_id", person.id);
        }
        
        // Add vendor_id as a fallback for authentication
        if (getContext() != null) {
            int vendorId = getContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE).getInt("vendor_id", -1);
            if (vendorId != -1) {
                json.addProperty("vendor_id", vendorId);
            }
        }

        json.addProperty("name", person.name);
        json.addProperty("templates", templatesBase64);
        json.addProperty("face_image", faceImageBase64);
        json.addProperty("phone", person.phone != null ? person.phone : "");
        json.addProperty("department", person.department != null ? person.department : "");
        json.addProperty("designation", person.designation != null ? person.designation : "");
        json.addProperty("shift", person.shift != null ? person.shift : "");
        if (person.localUid != null && !person.localUid.isEmpty()) {
            json.addProperty("local_uid", person.localUid);
        }

        RetrofitClient.getService().uploadFace(json).enqueue(new Callback<UploadFaceResponse>() {
            @Override
            public void onResponse(Call<UploadFaceResponse> call, Response<UploadFaceResponse> response) {
                if (response.isSuccessful()) {
                    dbManager.updatePersonFaceByLocalUid(person.localUid, faceImage, templates, true);
                    if (getContext() != null) Toast.makeText(getContext(), "Face Registered & Synced for " + person.name, Toast.LENGTH_SHORT).show();
                    String newId = null;
                    Integer assignedDisplayId = null;
                    try {
                        UploadFaceResponse body = response.body();
                        if (body != null && body.getPersonId() != null) {
                            newId = String.valueOf(body.getPersonId());
                        }
                        if (body != null) assignedDisplayId = body.getDisplayId();
                    } catch (Exception ignored) {}
                    if (newId != null && !newId.isEmpty()) {
                        if (assignedDisplayId != null && assignedDisplayId > 0) {
                            dbManager.updatePersonAfterSyncByLocalUid(person.localUid, newId, assignedDisplayId);
                        } else {
                            dbManager.updatePersonAfterSyncByLocalUid(person.localUid, newId);
                        }
                    } else {
                        dbManager.updatePersonStatusByLocalUid(person.localUid, true);
                    }
                    if (adapter != null) adapter.invalidateFace(person);
                } else {
                    String errorMsg = "Sync Failed: " + response.code();
                    try {
                        String errorBody = response.errorBody() != null ? response.errorBody().string() : null;
                        if (errorBody != null && !errorBody.isEmpty() && errorBody.contains("\"error\"")) {
                            int start = errorBody.indexOf("\"error\"") + 9;
                            int end = errorBody.indexOf("\"", start);
                            if (start > 8 && end > start) {
                                errorMsg = errorBody.substring(start, end).replace("\\", "");
                            }
                        }
                    } catch (Exception ignored) {}

                    int code = response.code();
                    if (code == 409 || code == 400 || code == 403 || code == 422) {
                        // Hard server rejection (duplicate face, parent duplicate, etc.)
                        // Clear rejected face data. NEVER DELETE THE ROSTER MEMBER!
                        dbManager.clearPersonFaceByLocalUid(person.localUid);
                        if (adapter != null) {
                            adapter.invalidateFace(person);
                            adapter.replaceUsers(DBManager.personList);
                        }
                    } else {
                        // Transient failure: save locally with synced = 0 for background worker retry
                        dbManager.updatePersonFaceByLocalUid(person.localUid, faceImage, templates, false);
                        if (adapter != null) adapter.invalidateFace(person);
                    }
                    if (getContext() != null) Toast.makeText(getContext(), errorMsg, Toast.LENGTH_LONG).show();
                }
            }
            @Override
            public void onFailure(Call<UploadFaceResponse> call, Throwable t) {
                t.printStackTrace();
                // Network error mid-request: save locally with synced = 0 so background worker syncs when online
                dbManager.updatePersonFaceByLocalUid(person.localUid, faceImage, templates, false);
                if (adapter != null) adapter.invalidateFace(person);
                if (getContext() != null) Toast.makeText(getContext(), "Network error during sync; saved locally for retry", Toast.LENGTH_SHORT).show();
            }
        });
    }
}
