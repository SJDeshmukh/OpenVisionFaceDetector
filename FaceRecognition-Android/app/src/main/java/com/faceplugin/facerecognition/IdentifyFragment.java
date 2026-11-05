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
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;


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
    private View manualAttendancePanel;
    private View manualActionModeCard;
    private View manualActionModeDot;
    private TextView manualActionModeText;
    private TextView manualActionModeSubtitle;
    private com.google.android.material.button.MaterialButton checkInActionButton;
    private com.google.android.material.button.MaterialButton checkOutActionButton;
    private android.animation.ObjectAnimator checkInActionAnimator;
    private android.animation.ObjectAnimator checkOutActionAnimator;
    private volatile ManualAttendanceActionSelection manualAttendanceActionSelection =
            new ManualAttendanceActionSelection(null, 0L);
    private android.content.SharedPreferences appPreferences;
    private boolean preferenceListenerRegistered = false;
    private final java.util.Map<String, String> attendanceRejectionMessages = new java.util.concurrent.ConcurrentHashMap<>();
    private final android.content.SharedPreferences.OnSharedPreferenceChangeListener attendanceModeListener =
            (preferences, key) -> {
                if ("attendance_action_mode".equals(key) && getActivity() != null) {
                    getActivity().runOnUiThread(this::applyAttendanceActionMode);
                }
            };
    private android.net.ConnectivityManager.NetworkCallback networkCallback;
    private long lastNotRecognizedToastAtMs = 0L;
    private boolean vendorVerifyOnlyMode = false;
    private final java.util.Map<String, Long> lastEventSentAtMs = new java.util.concurrent.ConcurrentHashMap<>();
    private final FaceAppearanceTracker appearanceTracker = new FaceAppearanceTracker();
    private final ArrayDeque<AttendanceFeedback> attendanceFeedbackQueue = new ArrayDeque<>();
    private final java.util.Set<String> pendingCooldownFeedbackKeys = new java.util.HashSet<>();
    private final Handler attendanceFeedbackHandler = new Handler(Looper.getMainLooper());
    private boolean attendanceFeedbackShowing = false;
    private static final long ATTENDANCE_FEEDBACK_DISPLAY_MS = 1800L;
    private static final long ATTENDANCE_SUCCESS_VISUAL_MS = 2000L;
    private static final long COOLDOWN_FEEDBACK_REPEAT_MS = 2000L;

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
        final int faceIndex;
        final boolean attendanceEligible;

        RecognizedFaceMatch(Person person, FaceBox faceBox, String personId, String localUid,
                            float similarity, int faceIndex, boolean attendanceEligible) {
            this.person = person;
            this.faceBox = faceBox;
            this.personId = personId;
            this.localUid = localUid;
            this.similarity = similarity;
            this.faceIndex = faceIndex;
            this.attendanceEligible = attendanceEligible;
        }
    }

    private static class AttendanceFeedback {
        final String name;
        final String status;
        final boolean alreadyMarked;
        final String message;

        AttendanceFeedback(String name, String status, boolean alreadyMarked, String message) {
            this.name = name;
            this.status = status;
            this.alreadyMarked = alreadyMarked;
            this.message = message;
        }
    }

    private static class ManualAttendanceActionSelection {
        final String action;
        final long revision;

        ManualAttendanceActionSelection(String action, long revision) {
            this.action = action;
            this.revision = revision;
        }
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_identify, container, false);

        dbManager = new DBManager(requireContext().getApplicationContext());

        // --- Socket.IO Init ---
        android.content.SharedPreferences sharedPref = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
        appPreferences = sharedPref;
        String serverUrl = sharedPref.getString("server_url", null);
        if (serverUrl == null || serverUrl.isEmpty()) {
            serverUrl = RetrofitClient.getBaseUrl();
        }
        if (serverUrl != null && !serverUrl.isEmpty()) {
            try {
                IO.Options options = new IO.Options();
                options.reconnection = true;
                options.transports = new String[]{"websocket"};
                Map<String, List<String>> headers = new HashMap<>();
                headers.put("User-Agent", Collections.singletonList("openvisionx-android"));
                String socketToken = sharedPref.getString("token", null);
                if (socketToken != null && !socketToken.isEmpty()) {
                    headers.put("Authorization", Collections.singletonList("Bearer " + socketToken));
                }
                options.extraHeaders = headers;
                if (serverUrl.endsWith("/")) serverUrl = serverUrl.substring(0, serverUrl.length() - 1);
                mSocket = IO.socket(serverUrl, options);
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
        manualAttendancePanel = view.findViewById(R.id.manualAttendancePanel);
        manualActionModeCard = view.findViewById(R.id.manualActionModeCard);
        manualActionModeDot = view.findViewById(R.id.manualActionModeDot);
        manualActionModeText = view.findViewById(R.id.manualActionModeText);
        manualActionModeSubtitle = view.findViewById(R.id.manualActionModeSubtitle);
        checkInActionButton = view.findViewById(R.id.checkInActionButton);
        checkOutActionButton = view.findViewById(R.id.checkOutActionButton);
        if (checkInActionButton != null) {
            checkInActionButton.setCheckable(true);
            checkInActionButton.setOnClickListener(v -> selectManualAttendanceAction("CHECK_IN"));
        }
        if (checkOutActionButton != null) {
            checkOutActionButton.setCheckable(true);
            checkOutActionButton.setOnClickListener(v -> selectManualAttendanceAction("CHECK_OUT"));
        }
        applyAttendanceActionMode();
        if (networkStatusPill != null) {
            networkStatusPill.setOnClickListener(v -> {
                boolean isNowOnline = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
                updateNetworkHud(isNowOnline);
                if (isNowOnline) {
                    Toast.makeText(getContext(), "Syncing offline attendance...", Toast.LENGTH_SHORT).show();
                    AttendanceSyncWorker.syncNow(requireContext().getApplicationContext(), (syncedCount) -> {
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> {
                                if (syncedCount > 0) {
                                    Toast.makeText(getContext(), "Synced " + syncedCount + " attendance records!", Toast.LENGTH_SHORT).show();
                                } else {
                                    Toast.makeText(getContext(), "All attendance up to date.", Toast.LENGTH_SHORT).show();
                                }
                            });
                        }
                        return null;
                    });
                    SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                } else {
                    int pending = dbManager.getAttendanceQueue().size();
                    Toast.makeText(getContext(), "Offline: " + pending + " records waiting to sync", Toast.LENGTH_SHORT).show();
                }
            });
        }
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

    private boolean isManualAttendanceMode() {
        return appPreferences != null
                && "manual".equalsIgnoreCase(
                        appPreferences.getString("attendance_action_mode", "automatic"));
    }

    private long trustedAttendanceNowMillis() {
        if (appPreferences == null) return System.currentTimeMillis();
        long serverAnchor = appPreferences.getLong("server_clock_anchor_utc_ms", 0L);
        long elapsedAnchor = appPreferences.getLong("server_clock_anchor_elapsed_ms", 0L);
        long elapsedNow = android.os.SystemClock.elapsedRealtime();
        if (serverAnchor > 0L && elapsedAnchor > 0L && elapsedNow >= elapsedAnchor) {
            return serverAnchor + (elapsedNow - elapsedAnchor);
        }
        long offset = appPreferences.getLong("server_clock_offset_ms", 0L);
        return System.currentTimeMillis() + offset;
    }

    private void applyAttendanceActionMode() {
        if (manualAttendancePanel == null) return;
        boolean showManualControls = isManualAttendanceMode() && !isVendorVerifyOnlyMode();
        manualAttendancePanel.setVisibility(showManualControls ? View.VISIBLE : View.GONE);
        if (manualActionModeCard != null) {
            manualActionModeCard.setVisibility(showManualControls ? View.VISIBLE : View.GONE);
        }
        if (!showManualControls) {
            ManualAttendanceActionSelection currentSelection = manualAttendanceActionSelection;
            if (currentSelection.action != null) {
                manualAttendanceActionSelection =
                        new ManualAttendanceActionSelection(null, currentSelection.revision + 1L);
            }
            updateManualAttendanceModeUi(null, false);
        } else {
            updateManualAttendanceModeUi(manualAttendanceActionSelection.action, false);
        }
    }

    private void selectManualAttendanceAction(String action) {
        if (!isAttendanceStatus(action)) return;
        ManualAttendanceActionSelection currentSelection = manualAttendanceActionSelection;
        ManualAttendanceActionSelection nextSelection = new ManualAttendanceActionSelection(
                action.toUpperCase(Locale.US), currentSelection.revision + 1L);
        manualAttendanceActionSelection = nextSelection;
        updateManualAttendanceModeUi(nextSelection.action, true);
        appearanceTracker.clearAll();
        attendanceRejectionMessages.clear();
        lastEventSentAtMs.clear();
        matchGate.reset();
        lastProcessedPersonId = null;
        if (statusText != null) {
            statusText.setText("Ready to " + friendlyAttendanceStatus(action));
            statusText.setTextColor(ContextCompat.getColor(requireContext(), R.color.primary_soft_blue));
        }
    }

    private boolean isCurrentManualAction(String action, long revision) {
        ManualAttendanceActionSelection currentSelection = manualAttendanceActionSelection;
        return ManualAttendanceActionPolicy.isCurrentSelection(
                action, revision, currentSelection.action, currentSelection.revision);
    }

    private void updateManualAttendanceModeUi(String action, boolean animate) {
        boolean checkInSelected = "CHECK_IN".equalsIgnoreCase(action);
        boolean checkOutSelected = "CHECK_OUT".equalsIgnoreCase(action);
        boolean hasSelection = checkInSelected || checkOutSelected;

        if (checkInActionButton != null) {
            checkInActionButton.setChecked(checkInSelected);
            checkInActionButton.setContentDescription(
                    checkInSelected ? "Check In selected" : "Select Check In");
            checkInActionButton.setElevation(checkInSelected ? 10f : 2f);
            checkInActionAnimator = updateActionButtonAnimation(
                    checkInActionButton, checkInSelected, checkInActionAnimator);
        }
        if (checkOutActionButton != null) {
            checkOutActionButton.setChecked(checkOutSelected);
            checkOutActionButton.setContentDescription(
                    checkOutSelected ? "Check Out selected" : "Select Check Out");
            checkOutActionButton.setElevation(checkOutSelected ? 10f : 2f);
            checkOutActionAnimator = updateActionButtonAnimation(
                    checkOutActionButton, checkOutSelected, checkOutActionAnimator);
        }

        String heading;
        String subtitle;
        if (checkInSelected) {
            heading = "CHECK IN MODE";
            subtitle = "Recognized employees will be checked in";
        } else if (checkOutSelected) {
            heading = "CHECK OUT MODE";
            subtitle = "Recognized employees will be checked out";
        } else {
            heading = "SELECT CHECK IN OR CHECK OUT";
            subtitle = "Choose an action below before scanning";
        }

        if (manualActionModeCard != null) {
            manualActionModeCard.setBackgroundResource(
                    hasSelection ? R.drawable.bg_attendance_mode_active : R.drawable.bg_attendance_mode_idle);
            if (animate && hasSelection) {
                manualActionModeCard.setScaleX(0.985f);
                manualActionModeCard.setScaleY(0.985f);
                manualActionModeCard.animate()
                        .scaleX(1.0f)
                        .scaleY(1.0f)
                        .setDuration(220L)
                        .start();
            }
        }
        if (manualActionModeDot != null) {
            manualActionModeDot.setBackgroundResource(
                    hasSelection ? R.drawable.bg_attendance_mode_dot_active : R.drawable.bg_attendance_mode_dot_idle);
            manualActionModeDot.clearAnimation();
            if (hasSelection && getContext() != null) {
                manualActionModeDot.startAnimation(
                        android.view.animation.AnimationUtils.loadAnimation(requireContext(), R.anim.pulse));
            }
        }
        if (manualActionModeText != null) {
            manualActionModeText.animate().cancel();
            manualActionModeText.setText(heading);
            manualActionModeText.setTextColor(ContextCompat.getColor(
                    requireContext(), hasSelection ? R.color.status_success : R.color.text_primary));
            if (animate) {
                manualActionModeText.setAlpha(0f);
                manualActionModeText.setTranslationY(7f);
                manualActionModeText.animate()
                        .alpha(1f)
                        .translationY(0f)
                        .setDuration(220L)
                        .start();
            } else {
                manualActionModeText.setAlpha(1f);
                manualActionModeText.setTranslationY(0f);
            }
        }
        if (manualActionModeSubtitle != null) {
            manualActionModeSubtitle.setText(subtitle);
        }
    }

    private android.animation.ObjectAnimator updateActionButtonAnimation(
            View button,
            boolean selected,
            android.animation.ObjectAnimator currentAnimator) {
        if (currentAnimator != null) {
            currentAnimator.cancel();
        }
        button.animate().cancel();
        if (!selected) {
            button.animate()
                    .scaleX(1.0f)
                    .scaleY(1.0f)
                    .alpha(1.0f)
                    .setDuration(180L)
                    .start();
            return null;
        }

        button.setAlpha(1.0f);
        button.setScaleX(1.0f);
        button.setScaleY(1.0f);
        android.animation.PropertyValuesHolder scaleX =
                android.animation.PropertyValuesHolder.ofFloat(View.SCALE_X, 1.0f, 1.025f, 1.0f);
        android.animation.PropertyValuesHolder scaleY =
                android.animation.PropertyValuesHolder.ofFloat(View.SCALE_Y, 1.0f, 1.025f, 1.0f);
        android.animation.ObjectAnimator animator = android.animation.ObjectAnimator.ofPropertyValuesHolder(
                button, scaleX, scaleY);
        animator.setDuration(1500L);
        animator.setInterpolator(new android.view.animation.AccelerateDecelerateInterpolator());
        animator.setRepeatCount(android.animation.ValueAnimator.INFINITE);
        animator.setRepeatMode(android.animation.ValueAnimator.RESTART);
        animator.start();
        return animator;
    }

    @Override
    public void onResume() {
        super.onResume();
        if (appPreferences != null && !preferenceListenerRegistered) {
            appPreferences.registerOnSharedPreferenceChangeListener(attendanceModeListener);
            preferenceListenerRegistered = true;
        }
        applyAttendanceActionMode();
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
        lastProcessedPersonId = null;
        hideScreenSaver(); // Start with screen active
        vendorVerifyOnlyMode = isVendorVerifyOnlyMode();
        if (statusText != null) {
            statusText.setText(vendorVerifyOnlyMode ? "Show a face to verify registration..." : "Looking for a registered face...");
        }
        updateSimilarityHud(0f);
        registerNetworkCallback();
        try {
            boolean online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
            updateNetworkHud(online);
            if (online) {
                AttendanceSyncWorker.syncNow(requireContext().getApplicationContext());
                SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
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
        unregisterNetworkCallback();
        if (manualActionModeDot != null) {
            manualActionModeDot.clearAnimation();
        }
        if (checkInActionAnimator != null) {
            checkInActionAnimator.cancel();
            checkInActionAnimator = null;
        }
        if (checkOutActionAnimator != null) {
            checkOutActionAnimator.cancel();
            checkOutActionAnimator = null;
        }
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

    private void registerNetworkCallback() {
        try {
            if (getContext() == null || networkCallback != null) return;
            android.net.ConnectivityManager cm = (android.net.ConnectivityManager) requireContext().getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm != null) {
                networkCallback = new android.net.ConnectivityManager.NetworkCallback() {
                    @Override
                    public void onAvailable(@NonNull android.net.Network network) {
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> {
                                updateNetworkHud(true);
                                Context ctx = getContext();
                                if (ctx != null) {
                                    AttendanceSyncWorker.syncNow(ctx.getApplicationContext());
                                    SyncScheduler.scheduleImmediate(ctx.getApplicationContext());
                                }
                            });
                        }
                    }

                    @Override
                    public void onLost(@NonNull android.net.Network network) {
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> updateNetworkHud(false));
                        }
                    }
                };
                android.net.NetworkRequest req = new android.net.NetworkRequest.Builder()
                        .addCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
                        .build();
                cm.registerNetworkCallback(req, networkCallback);
            }
        } catch (Exception ignored) {}
    }

    private void unregisterNetworkCallback() {
        try {
            if (networkCallback != null && getContext() != null) {
                android.net.ConnectivityManager cm = (android.net.ConnectivityManager) requireContext().getSystemService(Context.CONNECTIVITY_SERVICE);
                if (cm != null) {
                    cm.unregisterNetworkCallback(networkCallback);
                }
                networkCallback = null;
            }
        } catch (Exception ignored) {}
    }

    private boolean isVendorVerifyOnlyMode() {
        try {
            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
            String role = prefs.getString("role", null);
            if (role == null || role.trim().isEmpty()) {
                role = prefs.getString("offline_saved_role", "user");
            }
            // Attendance is an explicit kiosk/user capability. Vendor and admin
            // Identify tabs verify enrollment only and must never create an event.
            return !RecognitionModePolicy.canMarkAttendance(role);
        } catch (Exception ignored) {
            return false; // Default to allow attendance on error so offline punches are recorded
        }
    }

    @Override
    public void onPause() {
        super.onPause();
        if (appPreferences != null && preferenceListenerRegistered) {
            appPreferences.unregisterOnSharedPreferenceChangeListener(attendanceModeListener);
            preferenceListenerRegistered = false;
        }
        pauseResources();
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        attendanceFeedbackHandler.removeCallbacksAndMessages(null);
        attendanceFeedbackQueue.clear();
        pendingCooldownFeedbackKeys.clear();
        attendanceFeedbackShowing = false;
        attendanceRejectionMessages.clear();
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
        sendPersonEvent(detected, recognized, personId, localUid, name, confidence, bitmap,
                true, null, manualAttendanceActionSelection.revision);
    }

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String localUid, String name, float confidence, Bitmap bitmap, boolean triggerUiEffects) {
        sendPersonEvent(detected, recognized, personId, localUid, name, confidence, bitmap,
                triggerUiEffects, null, manualAttendanceActionSelection.revision);
    }

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String localUid, String name, float confidence, Bitmap bitmap, boolean triggerUiEffects, String requestedStatus) {
        sendPersonEvent(detected, recognized, personId, localUid, name, confidence, bitmap,
                triggerUiEffects, requestedStatus, manualAttendanceActionSelection.revision);
    }

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String localUid,
                                 String name, float confidence, Bitmap bitmap, boolean triggerUiEffects,
                                 String requestedStatus, long manualActionRevisionAtDispatch) {
        GreetingService service = RetrofitClient.getAttendanceService();
        // Downscale to 320px width to cut encoding time (~300ms -> ~25ms) and payload (~800KB -> ~25KB)
        Bitmap resized = Utils.resizeBitmap(bitmap, 320);
        byte[] attendanceImageJpeg = null;
        String imageBase64 = null;
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            if (resized != null && !resized.isRecycled() && resized.compress(Bitmap.CompressFormat.JPEG, 80, output)) {
                attendanceImageJpeg = output.toByteArray();
                imageBase64 = Base64.encodeToString(attendanceImageJpeg, Base64.NO_WRAP);
            }
        } catch (Exception | OutOfMemoryError e) {
            Log.e(TAG, "Unable to encode attendance thumbnail", e);
        }
        if (resized != null && resized != bitmap) resized.recycle();
        final byte[] retryImageJpeg = attendanceImageJpeg;

        boolean isAttendance = true;

        // Generate timestamp from mobile
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
        String timestamp = sdf.format(new Date(trustedAttendanceNowMillis()));

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
        final String eventTrackKey = attendanceTrackKey(finalPersonId, localUid, name);

        if (!online) {
            if ((resolvedBackendId != null && !resolvedBackendId.isEmpty()) || (localUid != null && !localUid.isEmpty())) {
                if (isAttendance) {
                    boolean explicitStatus = isAttendanceStatus(requestedStatus);
                    String predicted = explicitStatus ? requestedStatus : dbManager.predictNextAttendanceStatus(resolvedBackendId, localUid, name);
                    dbManager.insertAttendanceQueue(resolvedBackendId, localUid, name, timestamp, predicted, bitmap, false, explicitStatus);
                    boolean actionStillCurrent = !explicitStatus
                            || isCurrentManualAction(requestedStatus, manualActionRevisionAtDispatch);
                    if (actionStillCurrent) {
                        appearanceTracker.mark(eventTrackKey, predicted, System.currentTimeMillis());
                    }
                    announceAttendanceSavedOffline(
                            Collections.singletonList(name),
                            Collections.singletonList(predicted));
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
        final boolean explicitStatus = isAttendanceStatus(requestedStatus);
        if (explicitStatus) request.setStatus(requestedStatus);
        request.setModeAtCreation(explicitStatus ? "manual" : "automatic");
        String requestDeviceId = null;
        try {
            String deviceId = Settings.Secure.getString(requireContext().getContentResolver(), Settings.Secure.ANDROID_ID);
            requestDeviceId = deviceId;
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
        request.setSourceEventId(PersonEventRequest.buildSourceEventId(
                requestDeviceId, finalPersonId, localUid, timestamp));

        // Persist locally before making the request. The kiosk confirms this
        // local punch immediately and lets the server reconcile it in the
        // background. This keeps online and offline capture equally responsive.
        final String previousStatus = dbManager.getAttendanceStateStatus(finalPersonId, localUid, name);
        final String previousTimestamp = dbManager.getLastAttendanceTimestamp(finalPersonId, localUid, name);
        final String optimisticStatus = explicitStatus
                ? requestedStatus
                : dbManager.predictNextAttendanceStatus(finalPersonId, localUid, name);
        // Persist before the request. If the process dies or the response is lost,
        // WorkManager retries the exact same idempotency key.
        final long pendingQueueId = dbManager.insertAttendanceQueueJpeg(
                finalPersonId, localUid, name, timestamp, optimisticStatus, retryImageJpeg, false, explicitStatus);
        final boolean optimisticActionStillCurrent = !explicitStatus
                || isCurrentManualAction(requestedStatus, manualActionRevisionAtDispatch);
        final boolean optimisticFeedbackShown = pendingQueueId > 0
                && triggerUiEffects && optimisticActionStillCurrent;
        if (optimisticFeedbackShown) {
            appearanceTracker.mark(eventTrackKey, optimisticStatus, System.currentTimeMillis());
            enqueueAttendanceFeedback(name, optimisticStatus, false);
        }

        service.sendPersonEvent(request).enqueue(new Callback<GreetingResponse>() {
            @Override
            public void onResponse(Call<GreetingResponse> call, Response<GreetingResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    GreetingResponse greeting = response.body();
                    String status = greeting.getStatus();
                    boolean confirmed = !Boolean.FALSE.equals(greeting.getAccepted()) &&
                            ("CHECK_IN".equalsIgnoreCase(status) || "CHECK_OUT".equalsIgnoreCase(status));
                    if (confirmed) {
                        attendanceRejectionMessages.remove(eventTrackKey);
                        boolean serverResultNeedsFeedback =
                                AttendanceConfirmationPolicy.shouldAnnounceServerResult(
                                        optimisticStatus, status, optimisticFeedbackShown);
                        boolean actionStillCurrent = !explicitStatus
                                || isCurrentManualAction(requestedStatus, manualActionRevisionAtDispatch);
                        if (actionStillCurrent && serverResultNeedsFeedback) {
                            appearanceTracker.mark(eventTrackKey, status, System.currentTimeMillis());
                        }
                        try {
                            String stateStatus = greeting.getLatestStatus();
                            if (stateStatus == null || stateStatus.isEmpty()) {
                                stateStatus = status;
                            }
                            String stateTimestamp = greeting.getLatestTimestamp();
                            if (stateTimestamp == null || stateTimestamp.isEmpty()) {
                                stateTimestamp = greeting.getTimestamp();
                            }
                            if (stateTimestamp == null || stateTimestamp.isEmpty()) {
                                stateTimestamp = timestamp;
                            }
                            dbManager.upsertAttendanceState(finalPersonId, localUid, name, stateStatus, stateTimestamp);
                            if (pendingQueueId > 0) dbManager.deleteQueueItem((int) pendingQueueId);
                        } catch (Exception ignored) {}
                        // The local result has already been announced. Speak
                        // again only when the server reconciles it to a different
                        // status, or when local feedback could not be shown.
                        if (triggerUiEffects && serverResultNeedsFeedback) {
                            enqueueAttendanceFeedback(name, status, false);
                        }
                    } else if (Boolean.FALSE.equals(greeting.getAccepted()) && isFinalAttendanceRejection(greeting.getReason())) {
                        try {
                            if (pendingQueueId > 0) dbManager.deleteQueueItem((int) pendingQueueId);
                            dbManager.restoreAttendanceState(finalPersonId, localUid, name, timestamp,
                                    previousStatus, previousTimestamp);
                            if (isAttendanceStatus(greeting.getLatestStatus())
                                    && greeting.getLatestTimestamp() != null
                                    && !greeting.getLatestTimestamp().isEmpty()) {
                                dbManager.upsertAttendanceState(finalPersonId, localUid, name,
                                        greeting.getLatestStatus(), greeting.getLatestTimestamp());
                            }
                        } catch (Exception ignored) {}
                        boolean actionStillCurrent = !explicitStatus
                                || isCurrentManualAction(requestedStatus, manualActionRevisionAtDispatch);
                        if (triggerUiEffects && actionStillCurrent) {
                            String markedStatus = greeting.getStatus();
                            if (!isAttendanceStatus(markedStatus)) {
                                markedStatus = isAttendanceStatus(requestedStatus) ? requestedStatus : previousStatus;
                            }
                            if (isAttendanceStatus(markedStatus)) {
                                String rejectionMessage = greeting.getText();
                                if (rejectionMessage == null || rejectionMessage.trim().isEmpty()) {
                                    rejectionMessage = name + ", attendance is already marked";
                                }
                                attendanceRejectionMessages.put(eventTrackKey, rejectionMessage);
                                if (appearanceTracker.markCooldownAndRequestFeedback(
                                        eventTrackKey, markedStatus, System.currentTimeMillis(),
                                        COOLDOWN_FEEDBACK_REPEAT_MS)) {
                                    enqueueAttendanceFeedback(name, markedStatus, true, rejectionMessage);
                                }
                            }
                        }
                    } else {
                        try {
                            if (pendingQueueId > 0) dbManager.markQueueItemRetry((int) pendingQueueId, "Unconfirmed server response");
                            AttendanceSyncWorker.scheduleImmediate(requireContext().getApplicationContext());
                        } catch (Exception ignored) {}
                        if (triggerUiEffects && getActivity() != null) {
                            getActivity().runOnUiThread(() ->
                                    Toast.makeText(getContext(), "Attendance saved; cloud confirmation pending", Toast.LENGTH_LONG).show());
                        }
                    }
                } else {
                    int code = response.code();
                    boolean retryable = code == 401 || code == 403 || code == 408 || code == 429 || code >= 500;
                    try {
                        if (pendingQueueId > 0) {
                            if (retryable) {
                                dbManager.markQueueItemRetry((int) pendingQueueId, "HTTP " + code);
                            } else {
                                dbManager.markQueueItemFailed((int) pendingQueueId, "HTTP " + code);
                                dbManager.restoreAttendanceState(finalPersonId, localUid, name, timestamp,
                                        previousStatus, previousTimestamp);
                                appearanceTracker.clearMark(eventTrackKey);
                            }
                        }
                        if (retryable && code != 401 && code != 403) {
                            AttendanceSyncWorker.scheduleImmediate(requireContext().getApplicationContext());
                        }
                    } catch (Exception ignored) {}
                    if (triggerUiEffects && getActivity() != null) {
                        getActivity().runOnUiThread(() -> {
                            String errorMsg = retryable
                                    ? "Attendance saved; cloud sync pending"
                                    : "Attendance rejected by server";
                            Toast.makeText(getContext(), errorMsg, Toast.LENGTH_LONG).show();
                            if (!retryable && statusText != null) statusText.setText("Attendance failed");
                        });
                    }
                }
            }

            @Override
            public void onFailure(Call<GreetingResponse> call, Throwable t) {
                Log.e(TAG, "API Error", t);
                // The event was persisted before the request; retain that exact
                // queue row and idempotency key for retry.
                if (isAttendance) {
                    try {
                        if (pendingQueueId > 0) dbManager.markQueueItemRetry((int) pendingQueueId, t.getClass().getSimpleName());
                        AttendanceSyncWorker.scheduleImmediate(requireContext().getApplicationContext());
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

    private boolean isAttendanceStatus(String status) {
        return "CHECK_IN".equalsIgnoreCase(status) || "CHECK_OUT".equalsIgnoreCase(status);
    }

    private boolean isFinalAttendanceRejection(String reason) {
        return "cooldown".equals(reason)
                || "already_checked_in".equals(reason)
                || "already_checked_out".equals(reason)
                || "not_checked_in".equals(reason)
                || "manual_action_required".equals(reason);
    }

    private String friendlyAttendanceStatus(String status) {
        return "CHECK_OUT".equalsIgnoreCase(status) ? "Check Out" : "Check In";
    }

    private void enqueueAttendanceFeedback(String name, String status, boolean alreadyMarked) {
        enqueueAttendanceFeedback(name, status, alreadyMarked, null);
    }

    private void enqueueAttendanceFeedback(String name, String status, boolean alreadyMarked, String customMessage) {
        if (!isAttendanceStatus(status) || getActivity() == null) return;
        getActivity().runOnUiThread(() -> {
            if (!isAdded()) return;
            String cooldownKey = name == null ? "" : name.trim().toLowerCase(Locale.US);
            if (alreadyMarked && !pendingCooldownFeedbackKeys.add(cooldownKey)) return;
            attendanceFeedbackQueue.offer(new AttendanceFeedback(name, status.toUpperCase(Locale.US), alreadyMarked, customMessage));
            showNextAttendanceFeedback();
        });
    }

    private void showNextAttendanceFeedback() {
        if (attendanceFeedbackShowing || !isAdded()) return;
        AttendanceFeedback feedback = attendanceFeedbackQueue.poll();
        if (feedback == null) return;

        attendanceFeedbackShowing = true;
        if (feedback.alreadyMarked) {
            String message = feedback.message != null && !feedback.message.trim().isEmpty()
                    ? feedback.message
                    : feedback.name + " — " + friendlyAttendanceStatus(feedback.status) + " already marked";
            if (faceView != null) faceView.startCooldownBorderAnimation();
            if (statusText != null) {
                statusText.setText(message);
                statusText.setTextColor(ContextCompat.getColor(requireContext(), R.color.vision_error));
            }
            Toast.makeText(requireContext(), message, Toast.LENGTH_LONG).show();
            speakAlreadyMarked(feedback.name, feedback.status);
        } else {
            playAttendanceSound(feedback.status);
            speakAttendanceGreeting(feedback.name, feedback.status);
            showStatusOverlay(feedback.status);
            showAttendanceToast(feedback.name, feedback.status);
            if (statusText != null) {
                statusText.setText(feedback.name + " " + friendlyAttendanceStatus(feedback.status));
            }
        }

        attendanceFeedbackHandler.postDelayed(() -> {
            attendanceFeedbackShowing = false;
            if (feedback.alreadyMarked) {
                String cooldownKey = feedback.name == null
                        ? "" : feedback.name.trim().toLowerCase(Locale.US);
                pendingCooldownFeedbackKeys.remove(cooldownKey);
            }
            if (statusText != null && isAdded()) {
                statusText.setTextColor(ContextCompat.getColor(requireContext(), R.color.primary_soft_blue));
            }
            showNextAttendanceFeedback();
        }, ATTENDANCE_FEEDBACK_DISPLAY_MS);
    }

    private void speakAlreadyMarked(String name, String status) {
        speakAttendanceMessage(AttendanceVoiceMessage.alreadyMarked(name, status));
    }

    private void speakAttendanceMessage(String message) {
        try {
            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
            if (!prefs.getBoolean("voice_greeting_enabled", true) || tts == null) return;
            tts.speak(message, TextToSpeech.QUEUE_FLUSH, null, "attendance_already_marked");
        } catch (Exception ignored) {}
    }

    private float faceAreaRatio(FaceBox faceBox, int frameWidth, int frameHeight) {
        if (faceBox == null || frameWidth <= 0 || frameHeight <= 0) return 0f;
        float width = Math.max(0f, faceBox.x2 - faceBox.x1);
        float height = Math.max(0f, faceBox.y2 - faceBox.y1);
        return (width * height) / ((float) frameWidth * (float) frameHeight);
    }

    private String attendanceTrackKey(String personId, String localUid, String name) {
        if (personId != null && !personId.isEmpty()) return personId;
        if (localUid != null && !localUid.isEmpty()) return "local:" + localUid;
        return "name:" + (name == null ? "unknown" : name);
    }

    private void renderAttendanceFaceStates(
            List<String> namesForBoxes,
            int faceCount,
            List<RecognizedFaceMatch> matches) {
        List<String> labels = new java.util.ArrayList<>(namesForBoxes);
        List<Integer> visualStates = new java.util.ArrayList<>();
        for (int i = 0; i < faceCount; i++) visualStates.add(FaceView.ATTENDANCE_NONE);
        long nowMs = System.currentTimeMillis();
        for (RecognizedFaceMatch match : matches) {
            String key = attendanceTrackKey(match.personId, match.localUid, match.person.name);
            if (!appearanceTracker.isMarked(key)) continue;
            if (match.faceIndex >= 0 && match.faceIndex < visualStates.size()) {
                int trackerState = appearanceTracker.getVisualState(
                        key, nowMs, ATTENDANCE_SUCCESS_VISUAL_MS);
                int visualState = trackerState == FaceAppearanceTracker.VISUAL_SUCCESS
                        ? FaceView.ATTENDANCE_SUCCESS
                        : trackerState == FaceAppearanceTracker.VISUAL_COOLDOWN
                        ? FaceView.ATTENDANCE_COOLDOWN
                        : trackerState == FaceAppearanceTracker.VISUAL_PENDING
                        ? FaceView.ATTENDANCE_PENDING
                        : FaceView.ATTENDANCE_NONE;
                visualStates.set(match.faceIndex, visualState);
                if (visualState == FaceView.ATTENDANCE_NONE) continue;
                String status = appearanceTracker.getStatus(key);
                String suffix = visualState == FaceView.ATTENDANCE_PENDING
                        ? "Attendance saved • Syncing"
                        : visualState == FaceView.ATTENDANCE_COOLDOWN
                        ? attendanceRejectionMessages.getOrDefault(key, "Attendance already marked")
                        : isAttendanceStatus(status)
                        ? friendlyAttendanceStatus(status) + " successful"
                        : "Attendance successful";
                labels.set(match.faceIndex, match.person.name + " • " + suffix);
            }
        }
        if (getActivity() != null) {
            getActivity().runOnUiThread(() -> {
                if (faceView == null) return;
                faceView.setRecognizedNames(labels);
                faceView.setAttendanceVisualStates(visualStates);
            });
        }
    }

    private void speakAttendanceGreeting(String name, String status) {
        try {
            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
            if (!prefs.getBoolean("voice_greeting_enabled", true) || tts == null) return;
            String greeting = AttendanceVoiceMessage.success(name, status);
            tts.speak(greeting, TextToSpeech.QUEUE_FLUSH, null, "attendance_greeting");
        } catch (Exception ignored) {}
    }

    private void announceAttendanceSavedOffline(List<String> names, List<String> statuses) {
        String spokenMessage = AttendanceVoiceMessage.savedOffline(names, statuses);
        StringBuilder displayNamesBuilder = new StringBuilder();
        if (names != null) {
            for (String name : names) {
                if (displayNamesBuilder.length() > 0) displayNamesBuilder.append(", ");
                displayNamesBuilder.append(name == null ? "Employee" : name);
            }
        }
        String displayNames = displayNamesBuilder.length() == 0
                ? "employee" : displayNamesBuilder.toString();
        try {
            android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
            if (prefs.getBoolean("voice_greeting_enabled", true) && tts != null) {
                tts.speak(
                        spokenMessage,
                        TextToSpeech.QUEUE_FLUSH,
                        null,
                        "attendance_offline_saved");
            }
        } catch (Exception ignored) {}
        if (getActivity() != null) {
            getActivity().runOnUiThread(() -> {
                Toast.makeText(getContext(), "Attendance saved offline for " + displayNames, Toast.LENGTH_SHORT).show();
                if (statusText != null) statusText.setText("Saved offline: " + displayNames);
                if (faceView != null) {
                    faceView.startSuccessCircleAnimation();
                    faceView.startSuccessBorderAnimation();
                }
            });
        }
    }

    private void showStatusOverlay(String status) {
        if (getActivity() == null) return;
        triggerHapticFeedback(status);
        getActivity().runOnUiThread(() -> {
            if (faceView != null) {
                faceView.startSuccessBorderAnimation();
            }
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

            int configuredMaxFaces = FaceProcessingLimitPolicy.DEFAULT_LIMIT;
            try {
                android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
                configuredMaxFaces = FaceProcessingLimitPolicy.clamp(
                        prefs.getInt("max_faces_per_frame", FaceProcessingLimitPolicy.DEFAULT_LIMIT));
            } catch (Exception ignored) {}
            FaceDetectionParam faceDetectionParam = FacePipeline.secureDetectionParams(requireContext());
            faceDetectionParam.max_faces = configuredMaxFaces;
            List<FaceBox> faceBoxes = LocalFaceEngineFacade.INSTANCE.faceDetection(finalProcessed, faceDetectionParam);
            appearanceTracker.expireStale(currentTime);

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

                // Multi-face batch scanning is limited per tenant by SuperAdmin.
                int maxFacesToProcess = FaceProcessingLimitPolicy.processedCount(
                        faceBoxes.size(), configuredMaxFaces);
                java.util.List<Integer> prioritizedFaceIndexes = new java.util.ArrayList<>();
                for (int i = 0; i < faceBoxes.size(); i++) prioritizedFaceIndexes.add(i);
                prioritizedFaceIndexes.sort((left, right) -> Float.compare(
                        faceAreaRatio(faceBoxes.get(right), finalProcessed.getWidth(), finalProcessed.getHeight()),
                        faceAreaRatio(faceBoxes.get(left), finalProcessed.getWidth(), finalProcessed.getHeight())));
                java.util.Set<Integer> faceIndexesToProcess = new java.util.HashSet<>(
                        prioritizedFaceIndexes.subList(0, maxFacesToProcess));
                float largestFaceAreaRatio = prioritizedFaceIndexes.isEmpty() ? 0f
                        : faceAreaRatio(faceBoxes.get(prioritizedFaceIndexes.get(0)),
                        finalProcessed.getWidth(), finalProcessed.getHeight());
                for (int i = 0; i < faceBoxes.size(); i++) {
                    FaceBox faceBox = faceBoxes.get(i);
                    String nameForBox = "Unknown";

                    if (faceIndexesToProcess.contains(i) && FacePipeline.recognitionReady(requireContext(), faceBox,
                            finalProcessed.getWidth(), finalProcessed.getHeight())) {
                        byte[] templates = LocalFaceEngineFacade.INSTANCE.templateExtraction(finalProcessed, faceBox);

                        float maxSimilarityForBox = 0f;
                        Person bestForBox = null;
                        if (templates != null) {
                            Person[] people;
                            synchronized (DBManager.personList) {
                                people = DBManager.personList.toArray(new Person[0]);
                            }
                            FaceGalleryMatcher.Match galleryMatch =
                                    FaceGalleryMatcher.bestMatch(templates, people);
                            if (galleryMatch != null) {
                                maxSimilarityForBox = galleryMatch.similarity;
                                bestForBox = galleryMatch.person;
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
                                boolean attendanceEligible = AttendanceCaptureZonePolicy.isEligible(
                                        faceBox.x1, faceBox.y1, faceBox.x2, faceBox.y2,
                                        finalProcessed.getWidth(), finalProcessed.getHeight(),
                                        largestFaceAreaRatio);
                                batchMatches.add(new RecognizedFaceMatch(
                                        bestForBox, faceBox, pid, luid, maxSimilarityForBox,
                                        i, attendanceEligible));
                                if (!attendanceEligible) {
                                    nameForBox = bestForBox.name + " • Move closer";
                                }
                            }
                        }
                    } else if (!FacePipeline.isLive(requireContext(), faceBox, false)) {
                        Log.w(TAG, "Liveness failed: score=" + faceBox.liveness
                                + ", label=" + faceBox.livenessLabel
                                + ", configuredThreshold=" + SettingsActivity.getLivenessThreshold(requireContext()));
                    }

                    namesForBoxes.add(nameForBox);
                }

                for (RecognizedFaceMatch match : batchMatches) {
                    String key = attendanceTrackKey(match.personId, match.localUid, match.person.name);
                    appearanceTracker.observe(key, currentTime);
                }
                renderAttendanceFaceStates(namesForBoxes, faceBoxes.size(), batchMatches);

                updateSimilarityHud(highestSimilarityInFrame);

                if (!batchMatches.isEmpty()) {
                    consecutiveUnknownFrames = 0;
                    List<RecognizedFaceMatch> readyToMark = new java.util.ArrayList<>();
                    int cooldown = 30;
                    try {
                        android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
                        cooldown = prefs.getInt("cooldown_seconds", 30);
                    } catch (Exception ignored) {}

                    final boolean manualAttendanceMode = isManualAttendanceMode();
                    final ManualAttendanceActionSelection actionSelectionAtRecognition =
                            manualAttendanceActionSelection;
                    final String manualAction = actionSelectionAtRecognition.action;
                    final long manualActionRevisionAtRecognition = actionSelectionAtRecognition.revision;
                    boolean onlineAtRecognition = false;
                    try {
                        onlineAtRecognition = NetworkUtils.INSTANCE.isOnline(
                                requireContext().getApplicationContext());
                    } catch (Exception ignored) {}
                    for (RecognizedFaceMatch match : batchMatches) {
                        String confirmationKey = match.personId;
                        if (confirmationKey == null || confirmationKey.isEmpty()) {
                            confirmationKey = "local:" + (match.localUid == null ? "" : match.localUid);
                        }
                        if (confirmationKey.equals("local:")) confirmationKey = "name:" + match.person.name;

                        String trackKey = attendanceTrackKey(match.personId, match.localUid, match.person.name);
                        // A continuously visible face can only create one event,
                        // even when the configured cooldown expires while it is
                        // still in front of the camera.
                        if (appearanceTracker.isMarked(trackKey)) {
                            if (!vendorVerifyOnlyMode && !isVendorVerifyOnlyMode()
                                    && match.attendanceEligible) {
                                String markedStatus = appearanceTracker.getStatus(trackKey);
                                if (isAttendanceStatus(markedStatus)
                                        && appearanceTracker.requestCooldownFeedbackIfDue(
                                                trackKey, currentTime,
                                                ATTENDANCE_SUCCESS_VISUAL_MS,
                                                COOLDOWN_FEEDBACK_REPEAT_MS)) {
                                    enqueueAttendanceFeedback(
                                            match.person.name, markedStatus, true,
                                            attendanceRejectionMessages.get(trackKey));
                                }
                            }
                            continue;
                        }

                        // Background faces remain recognized and tracked but
                        // cannot mark attendance until they enter the capture zone.
                        if (!match.attendanceEligible) {
                            continue;
                        }

                        if (manualAttendanceMode) {
                            if (!isAttendanceStatus(manualAction)) {
                                if (getActivity() != null) {
                                    getActivity().runOnUiThread(() -> {
                                        if (statusText != null) {
                                            statusText.setText("Select Check In or Check Out");
                                        }
                                    });
                                }
                                continue;
                            }
                            // Online, the shared backend timeline is authoritative
                            // across all kiosks. Offline, use the local shift-day
                            // state to prevent repeated explicit actions.
                            if (!onlineAtRecognition) {
                                String[] localState = dbManager.getAttendanceStateRow(
                                        match.personId, match.localUid, match.person.name);
                                String lastStateStatus = localState != null ? localState[0] : null;
                                String lastOperationalDate = localState != null ? localState[1] : null;
                                ManualAttendanceActionPolicy.Decision decision =
                                        ManualAttendanceActionPolicy.decide(
                                                manualAction,
                                                lastStateStatus,
                                                lastOperationalDate,
                                                DBManager.getOperationalDate(trustedAttendanceNowMillis()),
                                                match.person.name);
                                if (!decision.allowed) {
                                    attendanceRejectionMessages.put(trackKey, decision.message);
                                    if (appearanceTracker.markCooldownAndRequestFeedback(
                                            trackKey, manualAction, currentTime,
                                            COOLDOWN_FEEDBACK_REPEAT_MS)) {
                                        enqueueAttendanceFeedback(
                                                match.person.name, manualAction, true, decision.message);
                                    }
                                    continue;
                                }
                            }
                        }

                        if (!matchGate.accept(confirmationKey, currentTime)) {
                            continue;
                        }

                        boolean allow = manualAttendanceMode;
                        String lastTs = dbManager.getLastAttendanceTimestamp(match.personId, match.localUid, match.person.name);
                        if (!manualAttendanceMode && (lastTs == null || lastTs.isEmpty())) {
                            allow = true;
                        } else if (!manualAttendanceMode) {
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
                        if (!manualAttendanceMode && lastLocal != null) {
                            long nowMs = System.currentTimeMillis();
                            long deltaSec = (nowMs - lastLocal) / 1000;
                            if (deltaSec >= 0 && deltaSec < cooldown) {
                                allow = false;
                            }
                        }

                        if (allow) {
                            readyToMark.add(match);
                        } else if (!vendorVerifyOnlyMode && !isVendorVerifyOnlyMode()) {
                            String lastStatus = dbManager.getLastAttendanceStatus(
                                    match.personId, match.localUid, match.person.name);
                            if (isAttendanceStatus(lastStatus)
                                    && appearanceTracker.markCooldownAndRequestFeedback(
                                            trackKey, lastStatus, currentTime,
                                            COOLDOWN_FEEDBACK_REPEAT_MS)) {
                                enqueueAttendanceFeedback(match.person.name, lastStatus, true);
                            }
                        }
                    }

                    renderAttendanceFaceStates(namesForBoxes, faceBoxes.size(), batchMatches);

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

                    boolean online = onlineAtRecognition;

                    if (manualAttendanceMode
                            && !isCurrentManualAction(
                                    manualAction, manualActionRevisionAtRecognition)) {
                        return;
                    }

                    if (!online) {
                        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
                        String timestamp = sdf.format(new Date(trustedAttendanceNowMillis()));

                        List<String> markedNames = new java.util.ArrayList<>();
                        List<String> markedStatuses = new java.util.ArrayList<>();
                        for (RecognizedFaceMatch match : readyToMark) {
                            if (manualAttendanceMode
                                    && !isCurrentManualAction(
                                            manualAction, manualActionRevisionAtRecognition)) {
                                break;
                            }
                            String predicted = manualAttendanceMode
                                    ? manualAction
                                    : dbManager.predictNextAttendanceStatus(match.personId, match.localUid, match.person.name);
                            dbManager.insertAttendanceQueue(
                                    match.personId, match.localUid, match.person.name,
                                    timestamp, predicted, finalProcessed, false,
                                    manualAttendanceMode);
                            String trackKey = attendanceTrackKey(match.personId, match.localUid, match.person.name);
                            boolean actionStillCurrent = !manualAttendanceMode
                                    || isCurrentManualAction(
                                            manualAction, manualActionRevisionAtRecognition);
                            if (actionStillCurrent) {
                                appearanceTracker.mark(trackKey, predicted, currentTime);
                                try { lastEventSentAtMs.put(trackKey, System.currentTimeMillis()); } catch (Exception ignored) {}
                            }
                            markedNames.add(match.person.name);
                            markedStatuses.add(predicted);
                        }

                        if (!markedNames.isEmpty()) {
                            renderAttendanceFaceStates(namesForBoxes, faceBoxes.size(), batchMatches);
                            announceAttendanceSavedOffline(markedNames, markedStatuses);
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
                            String trackKey = attendanceTrackKey(single.personId, single.localUid, single.person.name);
                            lastProcessedPersonId = trackKey;
                            String predicted = dbManager.predictNextAttendanceStatus(
                                    single.personId, single.localUid, single.person.name);
                            appearanceTracker.markPending(trackKey, predicted, currentTime);
                            if (manualAttendanceMode
                                    && !isCurrentManualAction(
                                            manualAction, manualActionRevisionAtRecognition)) {
                                appearanceTracker.clearMark(trackKey);
                                return;
                            }
                            try { lastEventSentAtMs.put(trackKey, System.currentTimeMillis()); } catch (Exception ignored) {}
                            sendPersonEvent(true, true, single.personId, single.localUid,
                                    single.person.name, single.similarity, finalProcessed,
                                    true, manualAttendanceMode ? manualAction : null,
                                    manualActionRevisionAtRecognition);
                        } else {
                            for (RecognizedFaceMatch match : readyToMark) {
                                String trackKey = attendanceTrackKey(match.personId, match.localUid, match.person.name);
                                String predicted = dbManager.predictNextAttendanceStatus(
                                        match.personId, match.localUid, match.person.name);
                                appearanceTracker.markPending(trackKey, predicted, currentTime);
                                if (manualAttendanceMode
                                        && !isCurrentManualAction(
                                                manualAction, manualActionRevisionAtRecognition)) {
                                    appearanceTracker.clearMark(trackKey);
                                    continue;
                                }
                                try { lastEventSentAtMs.put(trackKey, System.currentTimeMillis()); } catch (Exception ignored) {}
                                // Each response is announced separately so mixed check-ins and check-outs
                                // use the exact status confirmed by the backend.
                                sendPersonEvent(true, true, match.personId, match.localUid,
                                        match.person.name, match.similarity, finalProcessed,
                                        true, manualAttendanceMode ? manualAction : null,
                                        manualActionRevisionAtRecognition);
                            }
                        }
                        renderAttendanceFaceStates(namesForBoxes, faceBoxes.size(), batchMatches);
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
