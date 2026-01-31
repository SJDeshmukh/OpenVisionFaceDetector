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
import java.net.URISyntaxException;

public class IdentifyFragment extends Fragment implements TextToSpeech.OnInitListener {

    static String TAG = IdentifyFragment.class.getSimpleName();
    static int PREVIEW_WIDTH = 720;
    static int PREVIEW_HEIGHT = 1280;

    public static String BASE_URL = "http://192.168.1.102:5001"; // Default
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
    private TextView statusText;
    private FrameLayout screenSaverView;
    private DBManager dbManager;
    private android.widget.ImageView ivStatusOverlay;
    private TextView tvStatusOverlay;

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
    private long lastStreamTime = 0;
    private long resumeTime = 0;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_identify, container, false);

        dbManager = new DBManager(requireContext());
        dbManager.loadPerson(); // Load faces when fragment is created

        // --- Socket.IO Init ---
        android.content.SharedPreferences sharedPref = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
        String serverUrl = sharedPref.getString("server_url", BASE_URL);
        if (serverUrl != null && !serverUrl.isEmpty()) {
            try {
                IO.Options options = new IO.Options();
                options.reconnection = true;
                if (serverUrl.endsWith("/")) serverUrl = serverUrl.substring(0, serverUrl.length() - 1);
                mSocket = IO.socket(serverUrl, options);
                mSocket.connect();
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

        // Keep screen on
        if (getActivity() != null) {
            getActivity().getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }

        cameraExecutorService = Executors.newFixedThreadPool(1);
        tts = new TextToSpeech(requireContext(), this);

        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_DENIED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 1);
        } else {
            viewFinder.post(this::setUpCamera);
        }

        return view;
    }

    @Override
    public void onResume() {
        super.onResume();
        lastProcessedPersonId = null;
        hideScreenSaver(); // Start with screen active
        if (statusText != null) {
            statusText.setText("Looking for a registered face...");
        }
        
        // Try to sync offline queue
        syncOfflineQueue();
    }

    @Override
    public void onPause() {
        super.onPause();
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
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
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

        cameraSelector = new CameraSelector.Builder().requireLensFacing(SettingsActivity.getCameraLens(requireContext())).build();

        preview = new Preview.Builder()
                .setTargetResolution(new Size(PREVIEW_WIDTH, PREVIEW_HEIGHT))
                .setTargetRotation(rotation)
                .build();

        imageAnalyzer = new ImageAnalysis.Builder()
                .setBackpressureStrategy(STRATEGY_KEEP_ONLY_LATEST)
                .setTargetResolution(new Size(PREVIEW_WIDTH, PREVIEW_HEIGHT))
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

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String localUid, String name, float confidence, Bitmap image) {
        GreetingService service = RetrofitClient.getService();
        String imageBase64 = Utils.bitmapToBase64(image);

        // Determine attendance flag based on User Role
        // If Admin/Vendor -> is_attendance = false (Testing Mode: No Cooldown, No DB Record)
        // If User/Kiosk -> is_attendance = true (Production Mode: Cooldown, DB Record)
        android.content.SharedPreferences prefs = requireContext().getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
        String role = prefs.getString("role", "user");
        boolean isAttendance = "user".equalsIgnoreCase(role);

        // Generate timestamp from mobile
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
        String timestamp = sdf.format(new Date());

        if (isAttendance) {
            boolean online = false;
            try {
                online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
            } catch (Exception ignored) {}
            if (!online || personId == null || personId.isEmpty()) {
                dbManager.insertAttendanceQueue(personId, localUid, name, timestamp, "pending", image, false);
                Toast.makeText(getContext(), "Offline: Attendance Saved", Toast.LENGTH_SHORT).show();
                playAttendanceSound("CHECK_IN");
                showStatusOverlay("CHECK_IN");
                try {
                    SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                } catch (Exception e) {
                    e.printStackTrace();
                }
                return;
            }
        }

        PersonEventRequest request = new PersonEventRequest(detected, recognized, personId, name, confidence, imageBase64, isAttendance, timestamp);

        service.sendPersonEvent(request).enqueue(new Callback<GreetingResponse>() {
            @Override
            public void onResponse(Call<GreetingResponse> call, Response<GreetingResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    GreetingResponse greeting = response.body();
                    if (greeting.isSpeak()) {
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> {
                                Toast.makeText(getContext(), greeting.getText(), Toast.LENGTH_LONG).show();
                            });
                        }

                        // Play Sound based on Status (Check-In vs Check-Out)
                        String status = greeting.getStatus();
                        if (status != null) {
                             playAttendanceSound(status);
                             showStatusOverlay(status);
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
                            dbManager.insertAttendanceQueue(personId, localUid, name, timestamp, "pending", image, false);
                            Toast.makeText(getContext(), "Offline: Attendance Saved", Toast.LENGTH_SHORT).show();
                            playAttendanceSound("CHECK_IN"); // Generic success sound
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
        try {
            ToneGenerator toneGen = new ToneGenerator(AudioManager.STREAM_MUSIC, 100);
            if ("CHECK_IN".equals(status)) {
                // Check In Sound - High Pitch "Success" feel
                toneGen.startTone(ToneGenerator.TONE_PROP_BEEP, 200); 
            } else {
                // Check Out Sound - Different Tone (Double beep or lower)
                toneGen.startTone(ToneGenerator.TONE_CDMA_ALERT_CALL_GUARD, 200);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void showStatusOverlay(String status) {
        if (getActivity() == null) return;
        getActivity().runOnUiThread(() -> {
            if ("CHECK_IN".equals(status)) {
                if (ivStatusOverlay != null) {
                    ivStatusOverlay.setImageResource(android.R.drawable.checkbox_on_background);
                    ivStatusOverlay.setColorFilter(getResources().getColor(android.R.color.holo_green_light));
                    statusText.setTextColor(getResources().getColor(android.R.color.holo_green_light));
                    ivStatusOverlay.setVisibility(View.VISIBLE);
                    ivStatusOverlay.setAlpha(1f);
                    ivStatusOverlay.animate().alpha(0f).setDuration(800).withEndAction(() -> {
                        ivStatusOverlay.setVisibility(View.GONE);
                        statusText.setTextColor(getResources().getColor(R.color.primary_soft_blue));
                    }).start();
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
            }
        });
    }

    private void syncOfflineQueue() {
        if (dbManager == null) return;
        
        new Thread(() -> {
            List<DBManager.QueueItem> queue = dbManager.getAttendanceQueue();
            if (queue.isEmpty()) return;

            Log.d(TAG, "Syncing " + queue.size() + " offline records...");
            
            for (DBManager.QueueItem item : queue) {
                // Create Request
                // Note: image in QueueItem is Base64 string, but might need formatting
                String base64Image = item.image; 
                // If stored as raw bytes, DBManager converts it. If stored as Base64, fine.
                // In DBManager.java, we encoded it: android.util.Base64.encodeToString(img, android.util.Base64.NO_WRAP);
                
                // We need to ensure it has the prefix if backend expects it? 
                // Utils.bitmapToBase64 usually adds nothing or ?
                // Let's check Utils.bitmapToBase64. 
                // Assuming Utils.bitmapToBase64 returns pure Base64.
                
                PersonEventRequest request = new PersonEventRequest(
                    true, // detected
                    true, // recognized
                    item.personId, // personId
                    item.name, // name
                    0.99f, // confidence (dummy)
                    base64Image,
                    true, // isAttendance (always true for offline queue?)
                    item.timestamp
                );
                
                try {
                    // Synchronous call since we are in a Thread
                    Response<GreetingResponse> response = RetrofitClient.getService().sendPersonEvent(request).execute();
                    if (response.isSuccessful()) {
                        Log.d(TAG, "Synced: " + item.name);
                        dbManager.deleteQueueItem(item.id);
                    } else {
                        Log.e(TAG, "Sync Failed for " + item.name + ": " + response.code());
                    }
                } catch (Exception e) {
                    Log.e(TAG, "Sync Exception", e);
                }
            }
        }).start();
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
        Context context = getContext();
        if (context == null || mSocket == null || !mSocket.connected()) return;

        new Thread(() -> {
            try {
                // Resize to reduce bandwidth (e.g., width 320px)
                int width = 320;
                int height = (int) (originalBitmap.getHeight() * ((float) width / originalBitmap.getWidth()));
                Bitmap scaled = Bitmap.createScaledBitmap(originalBitmap, width, height, false);

                ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
                scaled.compress(Bitmap.CompressFormat.JPEG, 60, byteArrayOutputStream);
                byte[] byteArray = byteArrayOutputStream.toByteArray();
                String encoded = Base64.encodeToString(byteArray, Base64.NO_WRAP);
                String base64Image = "data:image/jpeg;base64," + encoded;

                String deviceId = Settings.Secure.getString(context.getContentResolver(), Settings.Secure.ANDROID_ID);
                int vendorId = context.getSharedPreferences("app_prefs", Context.MODE_PRIVATE).getInt("vendor_id", 0);
                String deviceName = "Mobile " + deviceId.substring(0, 8);

                JSONObject data = new JSONObject();
                data.put("image", base64Image);
                data.put("vendor_id", vendorId);
                data.put("device_id", deviceId);
                data.put("device_name", deviceName);
                mSocket.emit("stream_frame", data);

            } catch (Exception e) {
                e.printStackTrace();
            }
        }).start();
    }

    @OptIn(markerClass = ExperimentalGetImage.class)
    private void analyzeImage(ImageProxy imageProxy) {
        try {
            Image image = imageProxy.getImage();
            if (image == null) {
                imageProxy.close();
                return;
            }

            Image.Plane[] planes = image.getPlanes();
            ByteBuffer yBuffer = planes[0].getBuffer();
            ByteBuffer uBuffer = planes[1].getBuffer();
            ByteBuffer vBuffer = planes[2].getBuffer();

            int ySize = yBuffer.remaining();
            int uSize = uBuffer.remaining();
            int vSize = vBuffer.remaining();

            byte[] nv21 = new byte[ySize + uSize + vSize];
            yBuffer.get(nv21, 0, ySize);
            vBuffer.get(nv21, ySize, vSize);
            uBuffer.get(nv21, ySize + vSize, uSize);

            int cameraMode = 7;
            if (SettingsActivity.getCameraLens(requireContext()) == CameraSelector.LENS_FACING_BACK) {
                cameraMode = 6;
            }
            Bitmap bitmap = FaceSDK.yuv2Bitmap(nv21, image.getWidth(), image.getHeight(), cameraMode);

            // --- Streaming Logic ---
            long currentTime = System.currentTimeMillis();
            if (currentTime - lastStreamTime > 1000) { // 1 FPS
                lastStreamTime = currentTime;
                sendStreamFrame(bitmap);
            }
            // -----------------------

            // Grace period check (e.g. 3 seconds after resume)
            if (currentTime - resumeTime < 3000) {
                 imageProxy.close();
                 return;
            }

            FaceDetectionParam faceDetectionParam = new FaceDetectionParam();
            faceDetectionParam.check_liveness = true;
            faceDetectionParam.check_liveness_level = SettingsActivity.getLivenessLevel(requireContext());
            List<FaceBox> faceBoxes = FaceSDK.faceDetection(bitmap, faceDetectionParam);

            if (getActivity() != null) {
                getActivity().runOnUiThread(() -> {
                    faceView.setFrameSize(new Size(bitmap.getWidth(), bitmap.getHeight()));
                    faceView.setFaceBoxes(faceBoxes);
                    
                    if (faceBoxes.size() > 0) {
                        // Face Detected - Reset Power Save Timer
                        hideScreenSaver();
                        if (isPowerSaveTimerRunning) {
                            powerSaveHandler.removeCallbacks(powerSaveRunnable);
                            isPowerSaveTimerRunning = false;
                        }
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
                            
                            // Start Power Save Timer if not running and screen not already black
                            if (!isScreenSaverActive && !isPowerSaveTimerRunning) {
                                powerSaveHandler.postDelayed(powerSaveRunnable, POWER_SAVE_DELAY);
                                isPowerSaveTimerRunning = true;
                            }
                        }
                    }
                });
            }

            if (faceBoxes.size() > 0) {
                FaceBox faceBox = faceBoxes.get(0);
                if (faceBox.liveness > SettingsActivity.getLivenessThreshold(requireContext())) {
                    byte[] templates = FaceSDK.templateExtraction(bitmap, faceBox);

                    float maxSimiarlity = 0;
                    Person maximiarlityPerson = null;
                    for (Person person : DBManager.personList) {
                        float similarity = FaceSDK.similarityCalculation(templates, person.templates);
                        if (similarity > maxSimiarlity) {
                            maxSimiarlity = similarity;
                            maximiarlityPerson = person;
                        }
                    }

                    if (maxSimiarlity > SettingsActivity.getIdentifyThreshold(requireContext())) {
                        consecutiveUnknownFrames = 0;
                        final Person identifiedPerson = maximiarlityPerson;
                        
                        // Check if this is a new person or re-entry
                        String personId = identifiedPerson.id != null ? identifiedPerson.id : "";
                        String localUid = identifiedPerson.localUid != null ? identifiedPerson.localUid : "";
                        String key = personId;
                        if (key.isEmpty()) {
                            key = "local:" + (!localUid.isEmpty() ? localUid : identifiedPerson.name);
                        }
                        if (!key.equals(lastProcessedPersonId)) {
                            lastProcessedPersonId = key;
                            
                            if (getActivity() != null) {
                                getActivity().runOnUiThread(() -> {
                                    faceView.setRecognizedName(identifiedPerson.name);
                                    statusText.setText("Verifying " + identifiedPerson.name + "...");
                                });
                            }

                            // Send to Backend
                            sendPersonEvent(true, true, personId, localUid, identifiedPerson.name, maxSimiarlity, bitmap);
                        }

                    } else {
                        // Not Recognized
                        consecutiveUnknownFrames++;
                        
                        if (getActivity() != null) {
                            getActivity().runOnUiThread(() -> {
                                if (lastProcessedPersonId != null) {
                                    // If we were verifying someone, don't switch to Unknown immediately
                                    if (consecutiveUnknownFrames > UNKNOWN_THRESHOLD) {
                                        lastProcessedPersonId = null;
                                        faceView.setRecognizedName("Unknown");
                                        statusText.setText("Face not recognized");
                                    }
                                } else {
                                    // No previous lock, show Unknown immediately
                                    faceView.setRecognizedName("Unknown");
                                }
                            });
                        }
                    }
                }
            }

        } catch (Exception e) {
            e.printStackTrace();
        } finally {
            imageProxy.close();
        }
    }
}
