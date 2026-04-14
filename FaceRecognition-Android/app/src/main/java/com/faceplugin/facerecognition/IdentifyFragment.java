package com.faceplugin.facerecognition;

import static androidx.camera.core.ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.media.Image;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.util.Size;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;
import android.os.Handler;
import android.os.Looper;
import android.view.WindowManager;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.OptIn;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ExperimentalGetImage;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.faceplugin.facerecognition.api.GreetingResponse;
import com.faceplugin.facerecognition.api.GreetingService;
import com.faceplugin.facerecognition.api.PersonEventRequest;
import com.faceplugin.facerecognition.api.RetrofitClient;
import com.google.common.util.concurrent.ListenableFuture;
import com.ocp.facesdk.FaceBox;
import com.ocp.facesdk.FaceDetectionParam;
import com.ocp.facesdk.FaceSDK;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.Locale;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import android.util.Base64;
import java.io.ByteArrayOutputStream;
import com.faceplugin.facerecognition.api.StreamRequest;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

import android.media.AudioManager;
import android.media.ToneGenerator;
import android.provider.Settings;
import io.socket.client.IO;
import io.socket.client.Socket;
import org.json.JSONObject;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.net.URISyntaxException;

import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;

public class IdentifyFragment extends Fragment implements TextToSpeech.OnInitListener {

    static String TAG = IdentifyFragment.class.getSimpleName();
    static int PREVIEW_WIDTH = 720;
    static int PREVIEW_HEIGHT = 1280;

    public static String BASE_URL = BuildConfig.BASE_URL; 
    private Socket mSocket;

    private TextToSpeech tts;

    private ExecutorService cameraExecutorService;
    private PreviewView viewFinder;
    private Preview preview = null;
    private ImageAnalysis imageAnalyzer = null;
    private Camera camera = null;
    private CameraSelector cameraSelector = null;
    private ProcessCameraProvider cameraProvider = null;

    private FaceView faceView;
    private ExecutorService streamExecutorService;
    private TextView statusText;
    private FrameLayout screenSaverView;
    private DBManager dbManager;
    private android.widget.ImageView ivStatusOverlay;
    private TextView tvStatusOverlay;
    private View similarityBarFill;
    private View similarityBarContainer;
    private TextView similarityLabel;
    private View syncOrb;
    private TextView networkStatusPill;
    private long lastNotRecognizedToastAtMs = 0L;
    private boolean vendorVerifyOnlyMode = false;
    private java.util.Map<String, Long> lastEventSentAtMs = new java.util.HashMap<>();

    // Power Saving / Screen Saver
    private Handler powerSaveHandler = new Handler(Looper.getMainLooper());
    private boolean isPowerSaveTimerRunning = false;
    private boolean isScreenSaverActive = false;
    private static final long POWER_SAVE_DELAY = 5000; // 5 seconds
    
    private Runnable powerSaveRunnable = new Runnable() {
        @Override
        public void run() {
            showScreenSaver();
        }
    };

    // Debounce for Unknown state to prevent flickering
    private int consecutiveUnknownFrames = 0;
    private static final int UNKNOWN_THRESHOLD = 3;

    private String lastProcessedPersonId = null;
    private long resumeTime = 0L;
    private long lastStreamTime = 0L;
    private int frameCounter = 0;
    private boolean highPerformanceMode = false;
    private WebRTCManager webrtcManager;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_identify, container, false);

        dbManager = new DBManager(requireContext().getApplicationContext());
        dbManager.loadPerson(); // Load faces when fragment is created

        // --- Socket.IO Init ---
        android.content.SharedPreferences sharedPref = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
        String serverUrl = sharedPref.getString("server_url", null);
        if (serverUrl == null || serverUrl.isEmpty()) {
            serverUrl = RetrofitClient.getBaseUrl();
        }
        if (serverUrl != null && !serverUrl.isEmpty()) {
            try {
                IO.Options options = new IO.Options();
                options.reconnection = true;
                Map<String, List<String>> headers = new HashMap<>();
                headers.put("User-Agent", Collections.singletonList("openvisionx-android"));
                options.extraHeaders = headers;
                if (serverUrl.endsWith("/")) serverUrl = serverUrl.substring(0, serverUrl.length() - 1);
                mSocket = IO.socket(serverUrl, options);
                mSocket.on("persons_updated", (Object... args) -> {
                    try {
                        Context ctx = requireContext().getApplicationContext();
                        Constraints constraints = new Constraints.Builder()
                                .setRequiredNetworkType(NetworkType.CONNECTED)
                                .build();
                        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(FaceDownloadWorker.class)
                                .setConstraints(constraints)
                                .build();
                        WorkManager.getInstance(ctx)
                                .enqueueUniqueWork("face-download", ExistingWorkPolicy.REPLACE, req);
                    } catch (Exception ignored) {}
                });
                mSocket.connect();

                // WebRTC Signaling initialization
                String deviceId = Settings.Secure.getString(requireContext().getContentResolver(), Settings.Secure.ANDROID_ID);
                int vendorId = sharedPref.getInt("vendor_id", 0);
                webrtcManager = new WebRTCManager(requireContext().getApplicationContext(), mSocket, vendorId, deviceId);

            } catch (Exception e) {
                e.printStackTrace();
            }
        }
        // ----------------------

        viewFinder = view.findViewById(R.id.preview);
        faceView = view.findViewById(R.id.faceView);
        statusText = view.findViewById(R.id.statusText);
        screenSaverView = view.findViewById(R.id.screenSaverView);
        ivStatusOverlay = view.findViewById(R.id.ivStatusOverlay);
        tvStatusOverlay = view.findViewById(R.id.tvStatusOverlay);
        similarityBarContainer = view.findViewById(R.id.similarityBarContainer);
        similarityBarFill = view.findViewById(R.id.similarityBarFill);
        similarityLabel = view.findViewById(R.id.similarityLabel);
        syncOrb = view.findViewById(R.id.syncOrb);
        networkStatusPill = view.findViewById(R.id.networkStatusPill);
        vendorVerifyOnlyMode = isVendorVerifyOnlyMode();

        // Keep screen on
        if (getActivity() != null) {
            getActivity().getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }

        cameraExecutorService = Executors.newFixedThreadPool(1);
        streamExecutorService = Executors.newSingleThreadExecutor();
        tts = new TextToSpeech(requireContext(), this);

        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_DENIED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 1);
        } else {
            viewFinder.post(this::setUpCamera);
        }

        highPerformanceMode = SettingsActivity.isHighPerformanceMode(requireContext());
        if (faceView != null) {
            faceView.setMeshEnabled(false);
        }

        return view;
    }

    @Override
    public void onResume() {
        super.onResume();
        if (!isHidden()) {
            resumeResources();
        }
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        if (hidden) {
            pauseResources();
        } else {
            resumeResources();
        }
    }

    private void resumeResources() {
        try {
            if (dbManager != null) {
                dbManager.loadPerson();
            }
        } catch (Exception ignored) {}
        lastProcessedPersonId = null;
        hideScreenSaver(); // Start with screen active
        vendorVerifyOnlyMode = isVendorVerifyOnlyMode();
        if (statusText != null) {
            statusText.setText(vendorVerifyOnlyMode ? "Show a face to verify registration..." : "Looking for a registered face...");
        }
        updateSimilarityHud(0f);
        try {
            boolean online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
            updateNetworkHud(online);
            if (online) {
                android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
                String token = prefs.getString("token", null);
                if (token != null && !token.isEmpty()) {
                    SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                }
            }
        } catch (Exception ignored) {}
        
        // Re-bind camera if provider is available
        if (cameraProvider != null) {
            bindCameraUseCases();
        } else if (ContextCompat.checkSelfPermission(requireContext(), android.Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED) {
            if (viewFinder != null) {
                viewFinder.post(this::setUpCamera);
            }
        }
    }

    private void pauseResources() {
        if (faceView != null) {
            faceView.setFaceBoxes(null);
        }
        if (tts != null) {
            tts.stop();
        }
        if (powerSaveHandler != null) {
            powerSaveHandler.removeCallbacks(powerSaveRunnable);
            isPowerSaveTimerRunning = false;
        }
        if (cameraProvider != null) {
            cameraProvider.unbindAll();
        }
    }

    private boolean isVendorVerifyOnlyMode() {
        try {
            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
            String role = prefs.getString("role", null);
            
            // If role is null, we check if we have a vendor_id but no company_id? 
            // Or just default to attendance. 
            // Most reliable: if role is explicitly "user", enable attendance.
            // For anything else (admin, vendor, superadmin, null), disable attendance.
            if (role == null) {
                // If we don't know the role, let's see if we have a token.
                // If we have a token but no role, it might be an old session.
                // To be safe, if it's NOT "user", it's verify only.
                return true; 
            }
            
            return !"user".equalsIgnoreCase(role);
        } catch (Exception ignored) {
            return true; // Default to verify only on error
        }
    }

    @Override
    public void onPause() {
        super.onPause();
        pauseResources();
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        if (webrtcManager != null) {
            webrtcManager.dispose();
            webrtcManager = null;
        }
        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }
        if (tts != null) {
            tts.shutdown();
        }
        if (cameraExecutorService != null) {
            cameraExecutorService.shutdown();
        }
        if (streamExecutorService != null) {
            streamExecutorService.shutdown();
        }
        if (powerSaveHandler != null) {
            powerSaveHandler.removeCallbacks(powerSaveRunnable);
        }
        if (getActivity() != null) {
            getActivity().getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == 1) {
            if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
                    == PackageManager.PERMISSION_GRANTED) {
                viewFinder.post(this::setUpCamera);
            }
        }
    }

    private void setUpCamera() {
        ListenableFuture<ProcessCameraProvider> cameraProviderFuture = ProcessCameraProvider.getInstance(requireContext());
        cameraProviderFuture.addListener(() -> {
            try {
                cameraProvider = cameraProviderFuture.get();
                bindCameraUseCases();
            } catch (ExecutionException | InterruptedException e) {
                e.printStackTrace();
            }
        }, ContextCompat.getMainExecutor(requireContext()));
    }

    @SuppressLint({"RestrictedApi", "UnsafeExperimentalUsageError", "UnsafeOptInUsageError"})
    private void bindCameraUseCases() {
        int rotation = viewFinder.getDisplay().getRotation();
        Size targetSize = Utils.getOptimalResolution(requireContext());

        cameraSelector = new CameraSelector.Builder().requireLensFacing(SettingsActivity.getCameraLens(requireContext())).build();

        preview = new Preview.Builder()
                .setTargetResolution(targetSize)
                .setTargetRotation(rotation)
                .build();

        imageAnalyzer = new ImageAnalysis.Builder()
                .setBackpressureStrategy(STRATEGY_KEEP_ONLY_LATEST)
                .setTargetResolution(targetSize)
                .setTargetRotation(rotation)
                .build();

        imageAnalyzer.setAnalyzer(cameraExecutorService, new FaceAnalyzer());

        cameraProvider.unbindAll();

        try {
            camera = cameraProvider.bindToLifecycle(
                    getViewLifecycleOwner(), cameraSelector, preview, imageAnalyzer);

            preview.setSurfaceProvider(viewFinder.getSurfaceProvider());
        } catch (Exception exc) {
            exc.printStackTrace();
        }
    }

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String localUid, String name, float confidence, Bitmap bitmap) {
        GreetingService service = RetrofitClient.getService();
        String imageBase64 = Utils.bitmapToBase64(bitmap);

        boolean isAttendance = true;

        // Generate timestamp from mobile
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
        String timestamp = sdf.format(new Date());

        boolean online = false;
        try {
            online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
        } catch (Exception ignored) {}
        String resolvedBackendId = personId;
        if ((resolvedBackendId == null || resolvedBackendId.isEmpty()) && localUid != null && !localUid.isEmpty()) {
            try {
                String resolved = dbManager.resolvePersonId(localUid);
                if (resolved != null && !resolved.isEmpty()) {
                    resolvedBackendId = resolved;
                } else {
                    resolvedBackendId = "local:" + localUid;
                }
            } catch (Exception ignored) {
                resolvedBackendId = "local:" + localUid;
            }
        }

        final String finalPersonId = resolvedBackendId;

        if (!online) {
            if (resolvedBackendId != null && !resolvedBackendId.isEmpty()) {
                if (isAttendance) {
                    String predicted = dbManager.predictNextAttendanceStatus(resolvedBackendId, localUid, name);
                    dbManager.insertAttendanceQueue(resolvedBackendId, localUid, name, timestamp, predicted, bitmap, false);
                    playAttendanceSound(predicted);
                    showStatusOverlay(predicted);
                    showAttendanceToast(name, predicted);
                    if (getActivity() != null) {
                        String finalPredicted = predicted;
                        getActivity().runOnUiThread(() -> {
                            if (statusText != null) statusText.setText(name + " " + finalPredicted);
                        });
                    }
                    try { SyncScheduler.scheduleImmediate(requireContext().getApplicationContext()); } catch (Exception ignored) {}
                }
            } else {
                if (getActivity() != null) {
                    getActivity().runOnUiThread(() -> {
                        Toast.makeText(getContext(), "Sync required: missing person ID", Toast.LENGTH_LONG).show();
                        if (statusText != null) statusText.setText("Sync required");
                    });
                }
            }
            return;
        }


        PersonEventRequest request = new PersonEventRequest(detected, recognized, finalPersonId, name, confidence, imageBase64, isAttendance, timestamp);
        try {
            String deviceId = Settings.Secure.getString(requireContext().getContentResolver(), Settings.Secure.ANDROID_ID);
            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
            String deviceName = prefs.getString("device_name", null);
            if (deviceName == null || deviceName.isEmpty()) {
                if (deviceId != null && deviceId.length() >= 8) {
                    deviceName = "Mobile " + deviceId.substring(0, 8);
                } else {
                    deviceName = "Mobile";
                }
            }
            request.setDeviceId(deviceId);
            request.setDeviceName(deviceName);
            int vendorId = prefs.getInt("vendor_id", -1);
            if (vendorId > 0) request.setVendorId(vendorId);
            String btype = prefs.getString("selected_business_type_code", null);
            if (btype == null || btype.isEmpty()) {
                btype = prefs.getString("selected_business_type", null);
            }
            if (btype != null && !btype.isEmpty()) {
                request.setBusinessType(btype.toLowerCase());
            }
        } catch (Exception ignored) {}

        service.sendPersonEvent(request).enqueue(new Callback<GreetingResponse>() {
            @Override
            public void onResponse(Call<GreetingResponse> call, Response<GreetingResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    GreetingResponse greeting = response.body();
                    if (greeting.isSpeak()) {
                        showAttendanceToast(name, greeting.getStatus());

                        // Play Sound based on Status (Check-In vs Check-Out)
                        String status = greeting.getStatus();
                        if (status != null) {
                             playAttendanceSound(status);
                             showStatusOverlay(status);
                             try {
                                 if (isAttendance) {
                                     dbManager.upsertAttendanceState(finalPersonId, localUid, name, status, timestamp);
                                 }
                             } catch (Exception ignored) {}
                        } else {
                            
                        } 
                    }
                } else {
                    // Handle API Errors (e.g., 403 Suspended)
                    if (getActivity() != null) {
                        getActivity().runOnUiThread(() -> {
                            String errorMsg = "Attendance Failed";
                            try {
                                if (response.errorBody() != null) {
                                    // Simple parsing of JSON error {"error": "..."}
                                    String errorBody = response.errorBody().string();
                                    if (errorBody.contains("error")) {
                                        // Extract value after "error": "
                                        int start = errorBody.indexOf("\"error\"") + 9;
                                        int end = errorBody.indexOf("\"", start);
                                        // Adjust parsing if needed, or just show generic if complex
                                        if (start > 8 && end > start) {
                                            errorMsg = errorBody.substring(start, end);
                                            // Cleanup escaped chars if any
                                            errorMsg = errorMsg.replace("\\", "");
                                        }
                                    }
                                }
                            } catch (Exception e) {
                                e.printStackTrace();
                            }
                            
                            Toast.makeText(getContext(), errorMsg, Toast.LENGTH_LONG).show();
                            // Optional: Play error sound
                            // playAttendanceSound("ERROR"); 
                        });
                    }
                }
            }

            @Override
            public void onFailure(Call<GreetingResponse> call, Throwable t) {
                Log.e(TAG, "API Error", t);
                
                // Offline Fallback
                if (getActivity() != null) {
                    getActivity().runOnUiThread(() -> {
                        if (isAttendance) {
                            String predicted = dbManager.predictNextAttendanceStatus(finalPersonId, localUid, name);
                            dbManager.insertAttendanceQueue(finalPersonId, localUid, name, timestamp, predicted, bitmap, false);
                            playAttendanceSound(predicted);
                            showStatusOverlay(predicted);
                            showAttendanceToast(name, predicted);
                            if (statusText != null) statusText.setText(name + " " + predicted);
                            try {
                                SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                            } catch (Exception e) {
                                e.printStackTrace();
                            }
                        } else {
                            Toast.makeText(getContext(), "Offline: API Error", Toast.LENGTH_SHORT).show();
                        }
                    });
                }
            }
        });
    }

    private void playAttendanceSound(String status) {
        new Thread(() -> {
            try {
                // STREAM_ALARM forces loud play regardless of media volume
                android.media.ToneGenerator toneGen = new android.media.ToneGenerator(android.media.AudioManager.STREAM_ALARM, 100);
                if ("CHECK_IN".equals(status)) {
                    // Check In Sound - Fast Double Beep
                    toneGen.startTone(android.media.ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 150);
                    Thread.sleep(200);
                    toneGen.startTone(android.media.ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 150);
                    Thread.sleep(200);
                } else {
                    // Check Out Sound - Single Long Distinct Beep
                    toneGen.startTone(android.media.ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 600);
                    Thread.sleep(650);
                }
                toneGen.release();
            } catch (Exception e) {
                e.printStackTrace();
            }
        }).start();
    }

    private void showStatusOverlay(String status) {
        if (getActivity() == null) return;
        getActivity().runOnUiThread(() -> {
            if ("CHECK_IN".equals(status)) {
                if (ivStatusOverlay != null) {
                    ivStatusOverlay.setImageResource(R.drawable.ic_check_in_success);
                    ivStatusOverlay.clearColorFilter();
                    statusText.setTextColor(getResources().getColor(R.color.vision_success));
                    ivStatusOverlay.setVisibility(View.VISIBLE);
                    ivStatusOverlay.setAlpha(1f);
                    ivStatusOverlay.animate().alpha(0f).setDuration(800).withEndAction(() -> {
                        ivStatusOverlay.setVisibility(View.GONE);
                        statusText.setTextColor(getResources().getColor(R.color.primary_soft_blue));
                    }).start();
                }
                if (faceView != null) {
                    faceView.startSuccessCircleAnimation();
                }
                if (tvStatusOverlay != null) {
                    tvStatusOverlay.setVisibility(View.GONE);
                }
            } else {
                if (ivStatusOverlay != null) {
                    ivStatusOverlay.setVisibility(View.GONE);
                }
                if (tvStatusOverlay != null) {
                    tvStatusOverlay.setText("👋");
                    tvStatusOverlay.setTextColor(getResources().getColor(android.R.color.holo_blue_light));
                    statusText.setTextColor(getResources().getColor(android.R.color.holo_blue_light));
                    tvStatusOverlay.setVisibility(View.VISIBLE);
                    tvStatusOverlay.setAlpha(1f);
                    try {
                        android.animation.ObjectAnimator swing1 = android.animation.ObjectAnimator.ofFloat(tvStatusOverlay, "rotation", -20f, 20f);
                        swing1.setDuration(200);
                        android.animation.ObjectAnimator swing2 = android.animation.ObjectAnimator.ofFloat(tvStatusOverlay, "rotation", -10f, 10f);
                        swing2.setDuration(200);
                        android.animation.ObjectAnimator settle = android.animation.ObjectAnimator.ofFloat(tvStatusOverlay, "rotation", 0f);
                        settle.setDuration(150);
                        android.animation.AnimatorSet set = new android.animation.AnimatorSet();
                        set.playSequentially(swing1, swing2, settle);
                        set.start();
                    } catch (Exception ignored) {}
                    tvStatusOverlay.animate().alpha(0f).setDuration(900).withEndAction(() -> {
                        tvStatusOverlay.setVisibility(View.GONE);
                        statusText.setTextColor(getResources().getColor(R.color.primary_soft_blue));
                    }).start();
                }
                if (faceView != null) {
                    faceView.startSuccessCircleAnimation();
                }
            }
        });
    }

    private void showVerifyOverlay() {
        if (getActivity() == null) return;
        getActivity().runOnUiThread(() -> {
            if (ivStatusOverlay != null && isAdded()) {
                ivStatusOverlay.setImageResource(R.drawable.ic_check_in_success);
                ivStatusOverlay.clearColorFilter();
                ivStatusOverlay.setVisibility(View.VISIBLE);
                ivStatusOverlay.setAlpha(1f);
                ivStatusOverlay.animate().alpha(0f).setDuration(800).withEndAction(() -> {
                    if (ivStatusOverlay != null) {
                        ivStatusOverlay.setVisibility(View.GONE);
                    }
                }).start();
            }
            if (tvStatusOverlay != null) {
                tvStatusOverlay.setVisibility(View.GONE);
            }
            if (faceView != null) {
                faceView.startSuccessCircleAnimation();
            }
        });
    }

    private void showVerifyToast(String name) {
        if (getActivity() == null || getContext() == null) return;
        String message = "✔ Verified: " + name;
        getActivity().runOnUiThread(() -> {
            Toast toast = Toast.makeText(getContext(), message, Toast.LENGTH_SHORT);
            toast.show();
            new Handler(Looper.getMainLooper()).postDelayed(toast::cancel, 1000);
        });
    }

    private void showNotRecognizedToast() {
        if (getActivity() == null || getContext() == null) return;
        long now = System.currentTimeMillis();
        if (now - lastNotRecognizedToastAtMs < 1200) return;
        lastNotRecognizedToastAtMs = now;
        Toast toast = Toast.makeText(getContext(), "Not recognized", Toast.LENGTH_SHORT);
        toast.show();
        new Handler(Looper.getMainLooper()).postDelayed(toast::cancel, 1000);
    }

    private void updateNetworkHud(boolean online) {
        if (getContext() == null || syncOrb == null || networkStatusPill == null) return;
        String text = online ? "ONLINE" : "OFFLINE";
        networkStatusPill.setText(text);
        networkStatusPill.setTextColor(ContextCompat.getColor(requireContext(), android.R.color.black));
        networkStatusPill.setBackgroundResource(online ? R.drawable.bg_network_status_online : R.drawable.bg_network_status_offline);
        syncOrb.setVisibility(View.GONE);
    }

    private void showAttendanceToast(String name, String status) {
        if (getActivity() == null || getContext() == null) return;
        String friendlyStatus = "Check in";
        if ("CHECK_OUT".equals(status)) {
            friendlyStatus = "Check out";
        }
        String message = "✔️ 👋 " + name + " " + friendlyStatus;
        getActivity().runOnUiThread(() -> {
            Toast toast = Toast.makeText(getContext(), message, Toast.LENGTH_SHORT);
            toast.show();
            new Handler(Looper.getMainLooper()).postDelayed(toast::cancel, 1000);
        });
    }

    private void updateSimilarityHud(float similarity) {
        try {
            float clamped = Math.max(0f, Math.min(similarity, 1f));
            int percent = Math.round(clamped * 100f);
            if (getActivity() != null) {
                getActivity().runOnUiThread(() -> {
                    if (similarityLabel != null) {
                        similarityLabel.setText("Match: " + percent + "%");
                    }
                    if (similarityBarContainer != null && similarityBarFill != null) {
                        int containerWidth = similarityBarContainer.getWidth();
                        if (containerWidth > 0) {
                            int fillWidth = Math.round(containerWidth * clamped);
                            android.view.ViewGroup.LayoutParams lp = similarityBarFill.getLayoutParams();
                            lp.width = fillWidth;
                            similarityBarFill.setLayoutParams(lp);
                        }
                    }
                });
            }
        } catch (Exception ignored) {}
    }

    private void showScreenSaver() {
        if (!isScreenSaverActive && screenSaverView != null) {
            screenSaverView.setVisibility(View.VISIBLE);
            isScreenSaverActive = true;
            isPowerSaveTimerRunning = false; // Timer finished
        }
    }

    private void hideScreenSaver() {
        if (isScreenSaverActive && screenSaverView != null) {
            screenSaverView.setVisibility(View.GONE);
            isScreenSaverActive = false;
        }
        // Always ensure timer is reset when hiding (or trying to hide)
        // logic handled in caller
    }

    @Override
    public void onInit(int status) {
        if (status == TextToSpeech.SUCCESS) {
            int result = tts.setLanguage(Locale.US);
            if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                Log.e(TAG, "This Language is not supported");
            }
        } else {
            Log.e(TAG, "Initilization Failed!");
        }
    }

    class FaceAnalyzer implements ImageAnalysis.Analyzer {
        @OptIn(markerClass = ExperimentalGetImage.class)
        @Override
        public void analyze(@NonNull ImageProxy imageProxy) {
            analyzeImage(imageProxy);
        }
    }

    private void sendStreamFrame(Bitmap originalBitmap) {
        if (webrtcManager != null) {
            webrtcManager.onNewFrame(originalBitmap);
        }

        // --- Restored: Direct upload for Dashboard visibility ---
        // Resize for speed (e.g., 320px width)
        int width = 320;
        int height = (int) (originalBitmap.getHeight() * ((float) width / originalBitmap.getWidth()));
        final Bitmap scaled = Bitmap.createScaledBitmap(originalBitmap, width, height, false);
        
        if (streamExecutorService == null || streamExecutorService.isShutdown()) {
            if (scaled != originalBitmap) scaled.recycle();
            return;
        }

        streamExecutorService.execute(() -> {
            try {
                ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
                scaled.compress(Bitmap.CompressFormat.JPEG, 60, byteArrayOutputStream);
                byte[] byteArray = byteArrayOutputStream.toByteArray();
                String encoded = Base64.encodeToString(byteArray, Base64.NO_WRAP);
                String base64Image = "data:image/jpeg;base64," + encoded;

                // Get Vendor ID
                if (getContext() == null) return;
                android.content.SharedPreferences prefs = getContext().getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE);
                int vendorId = prefs.getInt("vendor_id", -1);
                Integer vendorIdObj = (vendorId != -1) ? vendorId : null;

                float batteryLevel = Utils.getBatteryLevel(getContext());
                String deviceId = android.provider.Settings.Secure.getString(getContext().getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
                String deviceName = prefs.getString("device_name", "Mobile Device");

                StreamRequest request = new StreamRequest(base64Image, vendorIdObj, deviceId, deviceName, batteryLevel);
                RetrofitClient.getService().uploadStreamFrame(request).enqueue(new Callback<Void>() {
                    @Override
                    public void onResponse(Call<Void> call, Response<Void> response) {}
                    @Override
                    public void onFailure(Call<Void> call, Throwable t) {}
                });
            } catch (Exception e) {
                e.printStackTrace();
            } finally {
                if (scaled != originalBitmap) {
                    scaled.recycle();
                }
            }
        });
        // --------------------------------------------------------
    }

    @OptIn(markerClass = ExperimentalGetImage.class)
    private void analyzeImage(ImageProxy imageProxy) {
        Bitmap processedFrameBitmap = null;
        try {
            android.media.Image inputMediaImage = imageProxy.getImage();
            if (inputMediaImage == null) {
                imageProxy.close();
                return;
            }

            // Hardened conversion handles padding (fixes Redmi/OEM detection failures)
            byte[] nv21 = Utils.yuv420ToNv21(inputMediaImage);

            int rotationDegrees = imageProxy.getImageInfo().getRotationDegrees();
            int lensFacing = SettingsActivity.getCameraLens(requireContext());
            int cameraMode = Utils.getCameraMode(rotationDegrees, lensFacing);

            // Diagnostic logging for Redmi/OEM troubleshooting
            if (frameCounter % 60 == 0) {
                Log.d(TAG, "Analysis Frame: " + inputMediaImage.getWidth() + "x" + inputMediaImage.getHeight() + 
                    ", rot: " + rotationDegrees + ", mode: " + cameraMode + ", buffer: " + nv21.length);
            }

            processedFrameBitmap = FaceSDKWrapper.INSTANCE.yuv2Bitmap(nv21, inputMediaImage.getWidth(), inputMediaImage.getHeight(), cameraMode);

            if (processedFrameBitmap == null) {
                imageProxy.close();
                return;
            }

            final Bitmap finalProcessed = processedFrameBitmap;

            // --- Streaming Logic ---
            long currentTime = System.currentTimeMillis();
            if (currentTime - lastStreamTime > 1000) { // 1 FPS
                lastStreamTime = currentTime;
                sendStreamFrame(finalProcessed);
            }
            // -----------------------

            // Grace period check (e.g. 3 seconds after resume)
            if (currentTime - resumeTime < 3000) {
                 imageProxy.close();
                 return;
            }

            FaceDetectionParam faceDetectionParam = new FaceDetectionParam();
            faceDetectionParam.check_liveness = true;
            try {
                faceDetectionParam.check_liveness_level = SettingsActivity.getLivenessLevel(requireContext());
            } catch (Exception ignored) {}
            List<FaceBox> faceBoxes = FaceSDKWrapper.INSTANCE.faceDetection(finalProcessed, faceDetectionParam);

            if (getActivity() != null) {
                getActivity().runOnUiThread(() -> {
                    faceView.setFrameSize(new Size(finalProcessed.getWidth(), finalProcessed.getHeight()));
                    faceView.setFaceBoxes(faceBoxes);
                    
                    if (faceBoxes.size() > 0) {
                        // Face Detected - Reset Power Save Timer
                        hideScreenSaver();
                        if (isPowerSaveTimerRunning) {
                            powerSaveHandler.removeCallbacks(powerSaveRunnable);
                            isPowerSaveTimerRunning = false;
                        }
                        updateSimilarityHud(0f);
                    } else {
                        // No Face Detected
                        if (faceBoxes.isEmpty()) {
                            // Reset if no face detected (existing logic)
                            if (lastProcessedPersonId != null) {
                                lastProcessedPersonId = null;
                                statusText.setText("Looking for a registered face...");
                                statusText.setTextColor(getResources().getColor(R.color.primary_soft_blue));
                                faceView.setRecognizedName(null);
                            }
                            updateSimilarityHud(0f);
                            
                            // Start Power Save Timer if not running and screen not already black
                            if (!isScreenSaverActive && !isPowerSaveTimerRunning) {
                                powerSaveHandler.postDelayed(powerSaveRunnable, POWER_SAVE_DELAY);
                                isPowerSaveTimerRunning = true;
                            }
                        }
                    }
                });
            }

            // --- Performance Optimization: Frame Skipping ---
            frameCounter++;
            if (highPerformanceMode && frameCounter % 3 != 0 && faceBoxes.size() > 0) {
                imageProxy.close();
                return;
            }
            // ------------------------------------------------

            if (faceBoxes.size() > 0) {
                float livenessThreshold = 0.8f;
                float identifyThreshold = 0.8f;
                try {
                    livenessThreshold = SettingsActivity.getLivenessThreshold(requireContext());
                    identifyThreshold = SettingsActivity.getIdentifyThreshold(requireContext());
                } catch (Exception ignored) {}
                List<String> namesForBoxes = new java.util.ArrayList<>();
                float bestSimilarity = 0f;
                Person bestPerson = null;
                FaceBox bestFaceBox = null;
                String bestPersonId = "";
                String bestLocalUid = "";

                for (int i = 0; i < faceBoxes.size(); i++) {
                    FaceBox faceBox = faceBoxes.get(i);
                    String nameForBox = "Unknown";

                    if (faceBox.liveness > livenessThreshold) {
                        byte[] templates = FaceSDKWrapper.INSTANCE.templateExtraction(finalProcessed, faceBox);

                        float maxSimilarityForBox = 0f;
                        Person bestForBox = null;
                        if (templates != null) {
                            for (Person person : DBManager.personList) {
                                float similarity = FaceSDKWrapper.INSTANCE.similarityCalculation(templates, person.templates);
                                if (similarity > maxSimilarityForBox) {
                                    maxSimilarityForBox = similarity;
                                    bestForBox = person;
                                }
                            }
                            
                            // Diagnostic Log
                            if (bestForBox != null) {
                                Log.i(TAG, "Match found: " + bestForBox.name + " (" + (maxSimilarityForBox * 100) + "%)");
                            } else {
                                Log.d(TAG, "No match found. Max similarity: " + (maxSimilarityForBox * 100) + "%");
                            }
                        }

                        if (bestForBox != null && maxSimilarityForBox > identifyThreshold) {
                            nameForBox = bestForBox.name;
                            if (maxSimilarityForBox > bestSimilarity) {
                                bestSimilarity = maxSimilarityForBox;
                                bestPerson = bestForBox;
                                bestFaceBox = faceBox;
                                bestPersonId = bestForBox.id != null ? bestForBox.id : "";
                                bestLocalUid = bestForBox.localUid != null ? bestForBox.localUid : "";
                            }
                        }
                    } else {
                         // Liveness failed - possible source of Redmi recognition issues
                         Log.w(TAG, "Liveness failed: " + faceBox.liveness + " (Threshold: " + livenessThreshold + ")");
                    }

                    namesForBoxes.add(nameForBox);
                }

                if (getActivity() != null) {
                    List<String> finalNamesForBoxes = namesForBoxes;
                    getActivity().runOnUiThread(() -> {
                        faceView.setRecognizedNames(finalNamesForBoxes);
                    });
                }

                updateSimilarityHud(bestSimilarity);

                if (bestPerson != null && bestSimilarity > identifyThreshold) {
                    consecutiveUnknownFrames = 0;
                    String personId = bestPersonId;
                    String localUid = bestLocalUid;
                    if ((personId == null || personId.isEmpty()) && localUid != null && !localUid.isEmpty()) {
                        try {
                            String resolved = dbManager.resolvePersonId(localUid);
                            if (resolved != null && !resolved.isEmpty()) {
                                personId = resolved;
                            }
                        } catch (Exception ignored) {}
                    }

                    if (vendorVerifyOnlyMode) {
                        String key = personId;
                        if (key == null) key = "";
                        if (key.isEmpty()) {
                            key = "local:" + (localUid != null && !localUid.isEmpty() ? localUid : "unknown");
                        }
                        if (!key.equals(lastProcessedPersonId)) {
                            lastProcessedPersonId = key;
                            String finalName = bestPerson.name;
                            if (getActivity() != null) {
                                getActivity().runOnUiThread(() -> {
                                    if (statusText != null) statusText.setText("Verified " + finalName);
                                });
                            }
                            showVerifyOverlay();
                            showVerifyToast(finalName);
                        }
                        return;
                    }

                    boolean online = false;
                    try {
                        online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
                    } catch (Exception ignored) {}

                    if (!online) {
                        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
                        String timestamp = sdf.format(new Date());
                        int cooldown = 30;
                        try {
                            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
                            cooldown = prefs.getInt("cooldown_seconds", 30);
                        } catch (Exception ignored) {}
                        boolean withinCooldown = false;
                        try {
                            String lastTs = dbManager.getLastAttendanceTimestamp(personId, localUid, bestPerson.name);
                            if (lastTs != null && !lastTs.isEmpty()) {
                                SimpleDateFormat sdf2 = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
                                long lastMs = sdf2.parse(lastTs).getTime();
                                long nowMs = sdf2.parse(timestamp).getTime();
                                long deltaSec = (nowMs - lastMs) / 1000;
                                if (deltaSec >= 0 && deltaSec < cooldown) {
                                    withinCooldown = true;
                                }
                            }
                        } catch (Exception ignored) {}
                        String k = personId;
                        if (k == null || k.isEmpty()) {
                            k = "local:" + (localUid != null && !localUid.isEmpty() ? localUid : "unknown");
                        }
                        try {
                            Long lastLocal = lastEventSentAtMs.get(k);
                            if (lastLocal != null) {
                                long nowMs = System.currentTimeMillis();
                                long deltaSec = (nowMs - lastLocal) / 1000;
                                if (deltaSec >= 0 && deltaSec < cooldown) {
                                    withinCooldown = true;
                                }
                            }
                        } catch (Exception ignored) {}
                        if (!withinCooldown) {
                            String predicted = dbManager.predictNextAttendanceStatus(personId, localUid, bestPerson.name);
                            dbManager.insertAttendanceQueue(personId, localUid, bestPerson.name, timestamp, predicted, finalProcessed, false);
                            playAttendanceSound(predicted);
                            showStatusOverlay(predicted);
                            if (getActivity() != null) {
                                String finalPredicted = predicted;
                                String finalName = bestPerson.name;
                                getActivity().runOnUiThread(() -> {
                                    if (statusText != null) statusText.setText(finalName + " " + finalPredicted);
                                });
                            }
                            try { lastEventSentAtMs.put(k, System.currentTimeMillis()); } catch (Exception ignored) {}
                            try {
                                SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                            } catch (Exception e) {
                                e.printStackTrace();
                            }
                        }
                        return;
                    }

                    String key = personId;
                    if (key.isEmpty()) {
                        key = "local:" + (!localUid.isEmpty() ? localUid : "unknown");
                    }

                    boolean allowByCooldown = false;
                    try {
                        android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
                        int cooldown = prefs.getInt("cooldown_seconds", 30);
                        String lastTs = dbManager.getLastAttendanceTimestamp(personId, localUid, bestPerson.name);
                        if (lastTs == null || lastTs.isEmpty()) {
                            allowByCooldown = true;
                        } else {
                            SimpleDateFormat sdf2 = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
                            String nowStr = sdf2.format(new Date());
                            long lastMs = sdf2.parse(lastTs).getTime();
                            long nowMs = sdf2.parse(nowStr).getTime();
                            long deltaSec = (nowMs - lastMs) / 1000;
                            allowByCooldown = (deltaSec >= cooldown || deltaSec < 0);
                        }
                    } catch (Exception ignored) {}

                    try {
                        Long lastLocal = lastEventSentAtMs.get(key);
                        if (lastLocal != null) {
                            long nowMs = System.currentTimeMillis();
                            int cooldown = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE).getInt("cooldown_seconds", 30);
                            long deltaSec = (nowMs - lastLocal) / 1000;
                            if (!(deltaSec >= cooldown || deltaSec < 0)) {
                                allowByCooldown = false;
                            }
                        }
                    } catch (Exception ignored) {}

                    if (allowByCooldown) {
                        lastProcessedPersonId = key;

                        if (getActivity() != null) {
                            String finalName = bestPerson.name;
                            getActivity().runOnUiThread(() -> {
                                statusText.setText("Verifying " + finalName + "...");
                            });
                        }

                        sendPersonEvent(true, true, personId, localUid, bestPerson.name, bestSimilarity, finalProcessed);
                        try { lastEventSentAtMs.put(key, System.currentTimeMillis()); } catch (Exception ignored) {}
                    } else {
                        if (getActivity() != null) {
                            String finalName = bestPerson.name;
                            getActivity().runOnUiThread(() -> {
                                statusText.setText(finalName + " — please wait (cooldown)");
                            });
                        }
                    }

                } else {
                    consecutiveUnknownFrames++;

                    if (getActivity() != null) {
                        getActivity().runOnUiThread(() -> {
                            if (lastProcessedPersonId != null) {
                                if (consecutiveUnknownFrames > UNKNOWN_THRESHOLD) {
                                    lastProcessedPersonId = null;
                                    statusText.setText("Face not recognized");
                                    showNotRecognizedToast();
                                    updateSimilarityHud(0f);
                                }
                            } else {
                                showNotRecognizedToast();
                                updateSimilarityHud(0f);
                            }
                        });
                    }
                }
            }

        } catch (Exception e) {
            e.printStackTrace();
        } finally {
            if (processedFrameBitmap != null && !processedFrameBitmap.isRecycled()) {
                processedFrameBitmap.recycle();
            }
            imageProxy.close();
        }
    }
}
