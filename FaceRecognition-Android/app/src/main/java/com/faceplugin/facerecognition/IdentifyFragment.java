package com.faceplugin.facerecognition;

import static androidx.camera.core.ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Rect;
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
import com.faceplugin.faceengine.FaceBox;
import com.faceplugin.faceengine.FaceDetectionParam;

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
    private int activeLensFacing = CameraSelector.LENS_FACING_FRONT;
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

    // Sticky Recognition & Frame Skipping
    private String stickyPersonName = null;
    private String stickyPersonId = null;
    private float stickyConfidence = 0f;
    private int recognitionSkipCount = 0;
    // Recognition remains enabled on every analyzed frame so temporal confirmation
    // is based on fresh SDK results, never a cached identity.
    private static final int MAX_RECOGNITION_SKIP = 0;
    private android.graphics.Rect lastFaceRect = null;
    // Set to 1 so attendance is marked instantly on first recognized frame instead of waiting 3 consecutive frames
    private final ConsecutiveMatchGate matchGate = new ConsecutiveMatchGate(1, 2000L);

    private static class RecognizedFaceMatch {
        final Person person;
        final FaceBox faceBox;
        final String personId;
        final String localUid;
        final float similarity;

        RecognizedFaceMatch(Person person, FaceBox faceBox, String personId, String localUid, float similarity) {
            this.person = person;
            this.faceBox = faceBox;
            this.personId = personId;
            this.localUid = localUid;
            this.similarity = similarity;
        }
    }

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
                String socketToken = sharedPref.getString("token", null);
                if (socketToken != null && !socketToken.isEmpty()) {
                    headers.put("Authorization", Collections.singletonList("Bearer " + socketToken));
                }
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

        highPerformanceMode = SettingsActivity.isHighPerformanceMode(requireContext());
        if (faceView != null) {
            faceView.setMeshEnabled(false);
        }

        // Retry local model initialization here in case the splash flow did not load it.
        boolean modelsReady = LocalFaceEngineFacade.INSTANCE.isInitialized();
        if (!modelsReady) {
            int initResult = LocalFaceEngineFacade.INSTANCE.ensureInitialized(requireContext().getApplicationContext());
            modelsReady = initResult == LocalFaceEngineFacade.SUCCESS;
            if (initResult != LocalFaceEngineFacade.SUCCESS) {
                String errMsg = getModelErrorMessage(initResult);
                Log.e(TAG, "Local face model initialization failed: " + initResult + " — " + errMsg);
                if (statusText != null) {
                    statusText.setText("⚠ Face detection unavailable\n" + errMsg);
                    statusText.setTextColor(android.graphics.Color.parseColor("#FF5555"));
                }
            }
        }

        if (modelsReady) {
            if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, 1);
            } else {
                viewFinder.post(this::setUpCamera);
            }
        }

        return view;
    }

    private static String getModelErrorMessage(int code) {
        if (code == LocalFaceEngineFacade.INIT_FAILED) {
            return "Local ONNX models could not be loaded";
        }
        return "Unknown model error (" + code + ")";
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

            // Attendance is an explicit kiosk/user capability. Vendor and admin
            // Identify tabs verify enrollment only and must never create an event.
            return !RecognitionModePolicy.canMarkAttendance(role);
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
        if (!isAdded() || viewFinder == null || !LocalFaceEngineFacade.INSTANCE.isInitialized()) return;
        ListenableFuture<ProcessCameraProvider> cameraProviderFuture = ProcessCameraProvider.getInstance(requireContext());
        cameraProviderFuture.addListener(() -> {
            try {
                cameraProvider = cameraProviderFuture.get();
                bindCameraUseCases();
            } catch (ExecutionException e) {
                Log.e(TAG, "Unable to obtain CameraX provider", e);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                Log.e(TAG, "Interrupted while obtaining CameraX provider", e);
            }
        }, ContextCompat.getMainExecutor(requireContext()));
    }

    @SuppressLint({"RestrictedApi", "UnsafeExperimentalUsageError", "UnsafeOptInUsageError"})
    private void bindCameraUseCases() {
        int rotation = viewFinder.getDisplay().getRotation();
        Size targetSize = Utils.getOptimalResolution(requireContext());

        int requestedLens = SettingsActivity.getCameraLens(requireContext());
        activeLensFacing = requestedLens;
        cameraSelector = new CameraSelector.Builder().requireLensFacing(requestedLens).build();
        try {
            if (!cameraProvider.hasCamera(cameraSelector)) {
                int fallbackLens = requestedLens == CameraSelector.LENS_FACING_FRONT
                        ? CameraSelector.LENS_FACING_BACK : CameraSelector.LENS_FACING_FRONT;
                CameraSelector fallback = new CameraSelector.Builder().requireLensFacing(fallbackLens).build();
                if (cameraProvider.hasCamera(fallback)) {
                    cameraSelector = fallback;
                    activeLensFacing = fallbackLens;
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Unable to query camera availability; using configured lens", e);
        }

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
            Log.e(TAG, "Unable to bind camera use cases", exc);
            if (statusText != null) statusText.setText("Camera unavailable — close other camera apps and retry");
        }
    }

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String localUid, String name, float confidence, Bitmap bitmap) {
        sendPersonEvent(detected, recognized, personId, localUid, name, confidence, bitmap, true);
    }

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String localUid, String name, float confidence, Bitmap bitmap, boolean triggerUiEffects) {
        GreetingService service = RetrofitClient.getService();
        // Downscale to 320px width to cut encoding time (~300ms -> ~25ms) and payload (~800KB -> ~25KB)
        Bitmap resized = Utils.resizeBitmap(bitmap, 320);
        String imageBase64 = Utils.bitmapToBase64(resized);
        if (resized != bitmap) resized.recycle();

        boolean isAttendance = true;

        // Generate timestamp from mobile
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
        String timestamp = sdf.format(new Date());

        boolean online = false;
        try {
            online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
        } catch (Exception ignored) {}
        String resolvedBackendId = personId;
        if ((resolvedBackendId == null || resolvedBackendId.isEmpty() || resolvedBackendId.startsWith("local:")) && localUid != null && !localUid.isEmpty()) {
            try {
                String resolved = dbManager.resolvePersonId(localUid, name);
                if (resolved != null && !resolved.isEmpty() && !resolved.startsWith("local:")) {
                    resolvedBackendId = resolved;
                } else {
                    resolvedBackendId = null;
                }
            } catch (Exception ignored) {
                resolvedBackendId = null;
            }
        }
        if (resolvedBackendId != null && resolvedBackendId.startsWith("local:")) {
            resolvedBackendId = null;
        }

        final String finalPersonId = resolvedBackendId;

        if (!online) {
            if ((resolvedBackendId != null && !resolvedBackendId.isEmpty()) || (localUid != null && !localUid.isEmpty())) {
                if (isAttendance) {
                    String predicted = dbManager.predictNextAttendanceStatus(resolvedBackendId, localUid, name);
                    dbManager.insertAttendanceQueue(resolvedBackendId, localUid, name, timestamp, predicted, bitmap, false);
                    playAttendanceSound(predicted);
                    speakAttendanceGreeting(name, predicted);
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


        // Online attendance must use the server clock. A device clock can be wrong
        // or deliberately adjusted for an unrelated SDK/license check; forwarding
        // it would save today's attendance under the wrong calendar date.
        PersonEventRequest request = new PersonEventRequest(detected, recognized, finalPersonId, name, confidence, imageBase64, isAttendance, null);
        request.setSourceEventId((finalPersonId != null ? finalPersonId : "unknown") + ":" + timestamp);
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

        // Optimistic UI: predict and show result immediately without waiting for the API
        final String optimisticStatus = dbManager.predictNextAttendanceStatus(finalPersonId, localUid, name);
        if (triggerUiEffects && getActivity() != null) {
            getActivity().runOnUiThread(() -> {
                playAttendanceSound(optimisticStatus);
                speakAttendanceGreeting(name, optimisticStatus);
                showStatusOverlay(optimisticStatus);
                showAttendanceToast(name, optimisticStatus);
                if (statusText != null) statusText.setText(name + " " + optimisticStatus);
            });
        }

        service.sendPersonEvent(request).enqueue(new Callback<GreetingResponse>() {
            @Override
            public void onResponse(Call<GreetingResponse> call, Response<GreetingResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    GreetingResponse greeting = response.body();
                    if (greeting.isSpeak()) {
                        String status = greeting.getStatus();
                        if (status != null) {
                            try {
                                if (isAttendance) {
                                    dbManager.upsertAttendanceState(finalPersonId, localUid, name, status, timestamp);
                                }
                            } catch (Exception ignored) {}
                            // Correct UI only if server disagrees with our prediction
                            if (triggerUiEffects && !status.equalsIgnoreCase(optimisticStatus)) {
                                if (getActivity() != null) {
                                    getActivity().runOnUiThread(() -> {
                                        playAttendanceSound(status);
                                        showStatusOverlay(status);
                                        showAttendanceToast(name, status);
                                        if (statusText != null) statusText.setText(name + " " + status);
                                    });
                                }
                            }
                        }
                    }
                } else {
                    // Handle API Errors (e.g., 403 Suspended)
                    if (triggerUiEffects && getActivity() != null) {
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
                // UI already updated optimistically; just queue for retry
                if (isAttendance) {
                    try {
                        dbManager.insertAttendanceQueue(finalPersonId, localUid, name, timestamp, optimisticStatus, bitmap, false);
                        SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                    } catch (Exception ignored) {}
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

    private void speakAttendanceGreeting(String name, String status) {
        try {
            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
            if (!prefs.getBoolean("voice_greeting_enabled", true) || tts == null) return;
            String greeting = "CHECK_OUT".equalsIgnoreCase(status)
                    ? "Goodbye " + name
                    : "Welcome " + name;
            tts.speak(greeting, TextToSpeech.QUEUE_FLUSH, null, "attendance_greeting");
        } catch (Exception ignored) {}
    }

    private void showStatusOverlay(String status) {
        if (getActivity() == null) return;
        triggerHapticFeedback(status);
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
        triggerHapticFeedback("VERIFY");
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

    private void triggerHapticFeedback(String eventType) {
        try {
            android.os.Vibrator vibrator = (android.os.Vibrator) requireContext().getSystemService(Context.VIBRATOR_SERVICE);
            if (vibrator == null || !vibrator.hasVibrator()) return;
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                android.os.VibrationEffect effect;
                if ("CHECK_IN".equals(eventType)) {
                    // Double-pulse: strong hit + soft follow
                    long[] timings = {0, 60, 80, 35};
                    int[] amps = {0, 220, 0, 120};
                    effect = android.os.VibrationEffect.createWaveform(timings, amps, -1);
                } else if ("CHECK_OUT".equals(eventType)) {
                    // Single medium pulse
                    effect = android.os.VibrationEffect.createOneShot(75, 180);
                } else {
                    // Light tick for verify/unknown
                    effect = android.os.VibrationEffect.createOneShot(25, 100);
                }
                vibrator.vibrate(effect);
            } else {
                if ("CHECK_IN".equals(eventType)) {
                    vibrator.vibrate(new long[]{0, 60, 80, 35}, -1);
                } else {
                    vibrator.vibrate(new long[]{0, 75}, -1);
                }
            }
        } catch (Exception ignored) {}
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
                return;
            }

            // Hardened conversion handles padding (fixes Redmi/OEM detection failures)
            byte[] nv21 = Utils.yuv420ToNv21(inputMediaImage);

            int rotationDegrees = imageProxy.getImageInfo().getRotationDegrees();
            int cameraMode = Utils.getCameraMode(rotationDegrees, activeLensFacing);

            // Diagnostic logging for Redmi/OEM troubleshooting
            if (frameCounter % 60 == 0) {
                Log.d(TAG, "Analysis Frame: " + inputMediaImage.getWidth() + "x" + inputMediaImage.getHeight() + 
                    ", rot: " + rotationDegrees + ", mode: " + cameraMode + ", buffer: " + nv21.length);
            }

            processedFrameBitmap = LocalFaceEngineFacade.INSTANCE.yuv2Bitmap(nv21, inputMediaImage.getWidth(), inputMediaImage.getHeight(), cameraMode);

            if (processedFrameBitmap == null) {
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

            // Grace period check (1 second after resume — enough for camera stabilization)
            if (currentTime - resumeTime < 1000) {
                 return;
            }

            FaceDetectionParam faceDetectionParam = FacePipeline.secureDetectionParams(requireContext());
            List<FaceBox> faceBoxes = LocalFaceEngineFacade.INSTANCE.faceDetection(finalProcessed, faceDetectionParam);

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
                            matchGate.reset();
                            stickyPersonName = null;
                            stickyPersonId = null;
                            recognitionSkipCount = 0;
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
                return;
            }
            // ------------------------------------------------

            if (faceBoxes.size() > 0) {
                float identifyThreshold = 0.72f;  // lowered from 0.8 for faster first-frame acceptance
                try {
                    identifyThreshold = SettingsActivity.getIdentifyThreshold(requireContext());
                } catch (Exception ignored) {}

                List<String> namesForBoxes = new java.util.ArrayList<>();
                List<RecognizedFaceMatch> batchMatches = new java.util.ArrayList<>();
                java.util.Set<String> matchedPersonKeysInFrame = new java.util.HashSet<>();
                float highestSimilarityInFrame = 0f;

                // Multi-Face Batch Scanning: Process up to 5 faces simultaneously in a single frame
                int maxFacesToProcess = Math.min(faceBoxes.size(), 5);
                for (int i = 0; i < faceBoxes.size(); i++) {
                    FaceBox faceBox = faceBoxes.get(i);
                    String nameForBox = "Unknown";

                    if (i < maxFacesToProcess && FacePipeline.recognitionReady(requireContext(), faceBox,
                            finalProcessed.getWidth(), finalProcessed.getHeight())) {
                        byte[] templates = LocalFaceEngineFacade.INSTANCE.templateExtraction(finalProcessed, faceBox);

                        float maxSimilarityForBox = 0f;
                        Person bestForBox = null;
                        if (templates != null) {
                            Person[] people;
                            synchronized (DBManager.personList) {
                                people = DBManager.personList.toArray(new Person[0]);
                            }
                            for (Person person : people) {
                                if (person == null || person.templates == null || person.templates.length == 0) continue;
                                float similarity = LocalFaceEngineFacade.INSTANCE.similarityCalculation(templates, person.templates);
                                if (similarity > maxSimilarityForBox) {
                                    maxSimilarityForBox = similarity;
                                    bestForBox = person;
                                }
                            }
                        }

                        if (bestForBox != null && maxSimilarityForBox > identifyThreshold) {
                            nameForBox = bestForBox.name;
                            if (maxSimilarityForBox > highestSimilarityInFrame) {
                                highestSimilarityInFrame = maxSimilarityForBox;
                            }

                            String pid = bestForBox.id != null ? bestForBox.id : "";
                            String luid = bestForBox.localUid != null ? bestForBox.localUid : "";
                            if ((pid.isEmpty() || pid.startsWith("local:")) && !luid.isEmpty()) {
                                try {
                                    String resolved = dbManager.resolvePersonId(luid, bestForBox.name);
                                    if (resolved != null && !resolved.isEmpty() && !resolved.startsWith("local:")) {
                                        pid = resolved;
                                    }
                                } catch (Exception ignored) {}
                            }
                            if (pid.startsWith("local:")) {
                                pid = "";
                            }

                            String personKey = (!pid.isEmpty()) ? pid : (!luid.isEmpty() ? luid : bestForBox.name);
                            if (!matchedPersonKeysInFrame.contains(personKey)) {
                                matchedPersonKeysInFrame.add(personKey);
                                batchMatches.add(new RecognizedFaceMatch(bestForBox, faceBox, pid, luid, maxSimilarityForBox));
                            }
                        }
                    } else if (faceBox.liveness < 0.8f) {
                        Log.w(TAG, "Liveness failed: " + faceBox.liveness);
                    }

                    namesForBoxes.add(nameForBox);
                }

                if (getActivity() != null) {
                    List<String> finalNamesForBoxes = namesForBoxes;
                    getActivity().runOnUiThread(() -> {
                        faceView.setRecognizedNames(finalNamesForBoxes);
                    });
                }

                updateSimilarityHud(highestSimilarityInFrame);

                if (!batchMatches.isEmpty()) {
                    consecutiveUnknownFrames = 0;
                    List<RecognizedFaceMatch> readyToMark = new java.util.ArrayList<>();
                    int cooldown = 30;
                    try {
                        android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
                        cooldown = prefs.getInt("cooldown_seconds", 30);
                    } catch (Exception ignored) {}

                    for (RecognizedFaceMatch match : batchMatches) {
                        String confirmationKey = match.personId;
                        if (confirmationKey == null || confirmationKey.isEmpty()) {
                            confirmationKey = "local:" + (match.localUid == null ? "" : match.localUid);
                        }
                        if (confirmationKey.equals("local:")) confirmationKey = "name:" + match.person.name;

                        if (!matchGate.accept(confirmationKey, currentTime)) {
                            continue;
                        }

                        String trackKey = match.personId;
                        if (trackKey == null || trackKey.isEmpty()) {
                            trackKey = "local:" + (match.localUid != null && !match.localUid.isEmpty() ? match.localUid : match.person.name);
                        }

                        boolean allow = false;
                        String lastTs = dbManager.getLastAttendanceTimestamp(match.personId, match.localUid, match.person.name);
                        if (lastTs == null || lastTs.isEmpty()) {
                            allow = true;
                        } else {
                            long lastMs = -1;
                            for (String fmt : new String[]{"yyyy-MM-dd'T'HH:mm:ss.SSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ss"}) {
                                try {
                                    lastMs = new SimpleDateFormat(fmt, Locale.US).parse(lastTs).getTime();
                                    break;
                                } catch (Exception ignored2) {}
                            }
                            if (lastMs >= 0) {
                                long deltaSec = (System.currentTimeMillis() - lastMs) / 1000;
                                allow = (deltaSec >= cooldown || deltaSec < 0);
                            } else {
                                allow = true;
                            }
                        }

                        Long lastLocal = lastEventSentAtMs.get(trackKey);
                        if (lastLocal != null) {
                            long nowMs = System.currentTimeMillis();
                            long deltaSec = (nowMs - lastLocal) / 1000;
                            if (deltaSec >= 0 && deltaSec < cooldown) {
                                allow = false;
                            }
                        }

                        if (allow) {
                            readyToMark.add(match);
                        }
                    }

                    if (vendorVerifyOnlyMode || isVendorVerifyOnlyMode()) {
                        for (RecognizedFaceMatch match : readyToMark) {
                            String key = !match.personId.isEmpty() ? match.personId : ("local:" + match.localUid);
                            if (!key.equals(lastProcessedPersonId)) {
                                lastProcessedPersonId = key;
                                String finalName = match.person.name;
                                if (getActivity() != null) {
                                    getActivity().runOnUiThread(() -> {
                                        if (statusText != null) statusText.setText("Verified " + finalName);
                                    });
                                }
                                showVerifyOverlay();
                                showVerifyToast(finalName);
                            }
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

                        List<String> markedNames = new java.util.ArrayList<>();
                        for (RecognizedFaceMatch match : readyToMark) {
                            String predicted = dbManager.predictNextAttendanceStatus(match.personId, match.localUid, match.person.name);
                            dbManager.insertAttendanceQueue(match.personId, match.localUid, match.person.name, timestamp, predicted, finalProcessed, false);
                            String trackKey = !match.personId.isEmpty() ? match.personId : ("local:" + match.localUid);
                            try { lastEventSentAtMs.put(trackKey, System.currentTimeMillis()); } catch (Exception ignored) {}
                            markedNames.add(match.person.name);
                        }

                        if (!markedNames.isEmpty()) {
                            if (markedNames.size() == 1) {
                                String singleName = markedNames.get(0);
                                String predicted = dbManager.predictNextAttendanceStatus(readyToMark.get(0).personId, readyToMark.get(0).localUid, singleName);
                                playAttendanceSound(predicted);
                                speakAttendanceGreeting(singleName, predicted);
                                showStatusOverlay(predicted);
                                if (getActivity() != null) {
                                    getActivity().runOnUiThread(() -> {
                                        if (statusText != null) statusText.setText(singleName + " " + predicted);
                                    });
                                }
                            } else {
                                StringBuilder sb = new StringBuilder();
                                for (int k = 0; k < markedNames.size(); k++) {
                                    if (k > 0) sb.append(k == markedNames.size() - 1 ? " & " : ", ");
                                    sb.append(markedNames.get(k));
                                }
                                String batchNamesStr = sb.toString();
                                playAttendanceSound("CHECK_IN");
                                speakAttendanceGreeting(batchNamesStr, "CHECK_IN");
                                showStatusOverlay("CHECK_IN");
                                if (getActivity() != null) {
                                    getActivity().runOnUiThread(() -> {
                                        if (statusText != null) statusText.setText("Marked: " + batchNamesStr);
                                    });
                                }
                            }
                            try {
                                SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                            } catch (Exception ignored) {}
                        }
                        return;
                    }

                    // Online Batch Attendance
                    if (!readyToMark.isEmpty()) {
                        if (readyToMark.size() == 1) {
                            RecognizedFaceMatch single = readyToMark.get(0);
                            String trackKey = !single.personId.isEmpty() ? single.personId : ("local:" + single.localUid);
                            lastProcessedPersonId = trackKey;
                            try { lastEventSentAtMs.put(trackKey, System.currentTimeMillis()); } catch (Exception ignored) {}
                            sendPersonEvent(true, true, single.personId, single.localUid, single.person.name, single.similarity, finalProcessed, true);
                        } else {
                            List<String> names = new java.util.ArrayList<>();
                            for (RecognizedFaceMatch match : readyToMark) {
                                String trackKey = !match.personId.isEmpty() ? match.personId : ("local:" + match.localUid);
                                try { lastEventSentAtMs.put(trackKey, System.currentTimeMillis()); } catch (Exception ignored) {}
                                names.add(match.person.name);
                                sendPersonEvent(true, true, match.personId, match.localUid, match.person.name, match.similarity, finalProcessed, false);
                            }
                            StringBuilder sb = new StringBuilder();
                            for (int k = 0; k < names.size(); k++) {
                                if (k > 0) sb.append(k == names.size() - 1 ? " & " : ", ");
                                sb.append(names.get(k));
                            }
                            String batchNamesStr = sb.toString();
                            playAttendanceSound("CHECK_IN");
                            speakAttendanceGreeting(batchNamesStr, "CHECK_IN");
                            showStatusOverlay("CHECK_IN");
                            if (getActivity() != null) {
                                getActivity().runOnUiThread(() -> {
                                    if (statusText != null) statusText.setText("Marked: " + batchNamesStr);
                                });
                            }
                        }
                    }

                } else {
                    matchGate.reset();
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
