package com.faceplugin.facerecognition;

import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.faceplugin.facerecognition.api.GreetingService;
import com.faceplugin.facerecognition.api.RetrofitClient;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.util.Base64;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import com.ocp.facesdk.FaceBox;
import com.faceplugin.facerecognition.api.UploadFaceResponse;
import com.google.gson.JsonObject;
import java.io.ByteArrayOutputStream;
import java.util.List;

public class UsersFragment extends Fragment {

    private RecyclerView recyclerView;
    private UserAdapter adapter;
    private DBManager dbManager;
    private ActivityResultLauncher<Intent> cameraLauncher;
    private Person pendingPersonForRegistration;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        cameraLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
                        String imageUriString = result.getData().getStringExtra("image_uri");
                        if (imageUriString != null) {
                            Uri imageUri = Uri.parse(imageUriString);
                            new Thread(() -> {
                                try {
                                    Bitmap bitmap = Utils.getCorrectlyOrientedImage(requireContext(), imageUri);
                                    if (bitmap != null) {
                                        if (getActivity() != null) getActivity().runOnUiThread(() -> processCameraResult(bitmap));
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
                                    processCameraResult(imageBitmap);
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
        dbManager.loadPerson(); // Ensure latest data is loaded

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
             adapter.setOnUserClickListener((person, position) -> {
                 if (person.templates == null || person.templates.length == 0) {
                     showRegisterFaceDialog(person);
                 } else {
                     Toast.makeText(getContext(), "Face already registered for " + person.name, Toast.LENGTH_SHORT).show();
                 }
             });
             recyclerView.setAdapter(adapter);
        }

        return view;
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
        // 1. Delete from Local DB
        boolean hasId = person.id != null && !person.id.isEmpty();
        if (hasId) {
            dbManager.deletePersonById(person.id);
        } else {
            dbManager.deletePerson(person.name);
        }
        
        // 2. Update UI
        adapter.notifyItemRemoved(position);
        adapter.notifyItemRangeChanged(position, adapter.getItemCount());
        Toast.makeText(getContext(), "Deleted locally", Toast.LENGTH_SHORT).show();

        if (person != null && !person.synced) {
            return;
        }

        boolean online = false;
        try {
            online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
        } catch (Exception ignored) {}

        // 3. Delete from Backend (or queue if offline)
        if (!online) {
            queueDelete(person);
            try {
                SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
            } catch (Exception ignored) {}
            return;
        }

        GreetingService service = RetrofitClient.getService();
        Call<Void> call = hasId ? service.deleteFaceById(person.id) : service.deleteFace(person.name);
        call.enqueue(new Callback<Void>() {
            @Override
            public void onResponse(Call<Void> call, Response<Void> response) {
                if (response.isSuccessful()) {
                    if (getActivity() != null) {
                         Toast.makeText(getContext(), "Deleted from backend", Toast.LENGTH_SHORT).show();
                    }
                } else {
                    queueDelete(person);
                    try {
                        SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                    } catch (Exception ignored) {}
                }
            }

            @Override
            public void onFailure(Call<Void> call, Throwable t) {
                queueDelete(person);
                try {
                    SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
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
        try {
            if (dbManager != null) {
                dbManager.loadPerson();
            }
        } catch (Exception ignored) {}
        if (adapter != null) adapter.notifyDataSetChanged();
    }

    private void showRegisterFaceDialog(Person person) {
        new AlertDialog.Builder(getContext())
                .setTitle("Register Face")
                .setMessage("No face registered for " + person.name + ". Would you like to register their face now?")
                .setPositiveButton("Register", (dialog, which) -> {
                    pendingPersonForRegistration = person;
                    Intent intent = new Intent(requireContext(), CaptureActivity.class);
                    intent.putExtra("is_capture_only", true);
                    cameraLauncher.launch(intent);
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void processCameraResult(Bitmap bitmap) {
        if (pendingPersonForRegistration == null) return;
        List<FaceBox> faceBoxes = FaceSDKWrapper.INSTANCE.faceDetection(bitmap, null);

        if (faceBoxes == null || faceBoxes.isEmpty()) {
            Toast.makeText(getContext(), getString(R.string.no_face_detected), Toast.LENGTH_SHORT).show();
            return;
        } else if (faceBoxes.size() > 1) {
            Toast.makeText(getContext(), getString(R.string.multiple_face_detected), Toast.LENGTH_SHORT).show();
            return;
        }
        
        FaceBox faceBox = faceBoxes.get(0);
        Bitmap faceImage = Utils.cropFace(bitmap, faceBox);
        byte[] templates = FaceSDKWrapper.INSTANCE.templateExtraction(bitmap, faceBox);
        
        if (templates == null) {
            Toast.makeText(getContext(), "Failed to extract face template", Toast.LENGTH_SHORT).show();
            return;
        }

        // Duplication check
        float maxSimilarity = 0f;
        for (Person p : DBManager.personList) {
            if (p.localUid != null && p.localUid.equals(pendingPersonForRegistration.localUid)) continue;
            if (p.id != null && pendingPersonForRegistration.id != null && p.id.equals(pendingPersonForRegistration.id)) continue;
            try {
                if (p.templates != null && p.templates.length > 0) {
                    float s = FaceSDKWrapper.INSTANCE.similarityCalculation(templates, p.templates);
                    if (s > maxSimilarity) maxSimilarity = s;
                }
            } catch (Exception ignored) {}
        }

        if (maxSimilarity > SettingsActivity.getIdentifyThreshold(requireContext())) {
            Toast.makeText(getContext(), "This face is already registered to someone else.", Toast.LENGTH_SHORT).show();
            return;
        }

        dbManager.updatePersonFaceByLocalUid(pendingPersonForRegistration.localUid, faceImage, templates);
        adapter.notifyDataSetChanged();

        if (NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext()) &&
            "true".equalsIgnoreCase(requireContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE).getString("cloud_sync", "true"))) {
            syncFaceToBackend(pendingPersonForRegistration, templates, faceImage);
        } else {
            Toast.makeText(getContext(), "Registered face locally (Offline)", Toast.LENGTH_SHORT).show();
        }
        
        pendingPersonForRegistration = null;
    }

    private void syncFaceToBackend(Person person, byte[] templates, Bitmap faceImage) {
        String templatesBase64 = Base64.encodeToString(templates, Base64.NO_WRAP);
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        faceImage.compress(Bitmap.CompressFormat.JPEG, 100, byteArrayOutputStream);
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

        RetrofitClient.getService().uploadFace(json).enqueue(new Callback<UploadFaceResponse>() {
            @Override
            public void onResponse(Call<UploadFaceResponse> call, Response<UploadFaceResponse> response) {
                if (response.isSuccessful()) {
                    if (getContext() != null) Toast.makeText(getContext(), "Face Synced to Cloud", Toast.LENGTH_SHORT).show();
                    String newId = null;
                    try {
                        UploadFaceResponse body = response.body();
                        if (body != null && body.getPersonId() != null) {
                            newId = String.valueOf(body.getPersonId());
                        }
                    } catch (Exception ignored) {}
                    if (newId != null && !newId.isEmpty()) {
                         dbManager.updatePersonAfterSyncByLocalUid(person.localUid, newId);
                    } else {
                         dbManager.updatePersonStatusByLocalUid(person.localUid, true);
                    }
                } else {
                    if (getContext() != null) Toast.makeText(getContext(), "Sync Failed: " + response.code(), Toast.LENGTH_SHORT).show();
                }
            }
            @Override
            public void onFailure(Call<UploadFaceResponse> call, Throwable t) {
                t.printStackTrace();
                if (getContext() != null) Toast.makeText(getContext(), "Network error during sync", Toast.LENGTH_SHORT).show();
            }
        });
    }
}
