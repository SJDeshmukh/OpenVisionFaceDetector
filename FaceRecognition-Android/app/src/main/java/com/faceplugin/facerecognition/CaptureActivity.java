package com.faceplugin.facerecognition;


import static androidx.camera.core.ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.media.Image;
import android.os.Bundle;
import android.util.Log;
import android.util.Size;
import android.view.View;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.OptIn;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ExperimentalGetImage;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.constraintlayout.widget.ConstraintLayout;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;
import com.faceplugin.faceengine.FaceBox;
import com.faceplugin.faceengine.FaceDetectionParam;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import android.util.Base64;
import java.io.ByteArrayOutputStream;
import com.faceplugin.facerecognition.api.RetrofitClient;
import com.faceplugin.facerecognition.api.StreamRequest;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;
import io.socket.client.Socket;

public class CaptureActivity extends AppCompatActivity implements CaptureView.ViewModeChanged{

    static String TAG = CaptureActivity.class.getSimpleName();
    static int PREVIEW_WIDTH = 720;
    static int PREVIEW_HEIGHT = 1280;

    private ExecutorService cameraExecutorService;
    private PreviewView viewFinder;
    private Preview preview        = null;
    private ImageAnalysis imageAnalyzer  = null;
    private Camera camera         = null;
    private CameraSelector        cameraSelector = null;
    private int activeLensFacing = CameraSelector.LENS_FACING_FRONT;
    private ProcessCameraProvider cameraProvider = null;

    private CaptureView captureView;

    private TextView warningTxt;

    private TextView livenessTxt;

    private TextView qualityTxt;

    private TextView luminaceTxt;

    private ConstraintLayout lytCaptureResult;

    private Context context;

    private Bitmap capturedBitmap = null;

    private FaceBox capturedFace = null;
    private byte[] capturedTemplate = null;
    private final List<byte[]> enrollmentTemplates = new ArrayList<>();
    private boolean isCapturing = false;
    private int consecutiveValidFrames = 0;
    private static final int REQUIRED_VALID_FRAMES = 7;

    private boolean isCaptureOnly = false;
    private long lastStreamTime = 0;

    private boolean forceFrontCamera = false;
    private WebRTCManager webrtcManager;
    private Socket mSocket;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_capture);

        context = this;
        isCaptureOnly = getIntent().getBooleanExtra("is_capture_only", false);
        forceFrontCamera = getIntent().getBooleanExtra("force_front_camera", false);

        // --- Socket.IO & WebRTC Init ---
        android.content.SharedPreferences sharedPref = getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
        String serverUrl = sharedPref.getString("server_url", null);
        if (serverUrl == null || serverUrl.isEmpty()) {
            serverUrl = RetrofitClient.getBaseUrl();
        }
        if (serverUrl != null && !serverUrl.isEmpty()) {
            try {
                io.socket.client.IO.Options options = new io.socket.client.IO.Options();
                options.reconnection = true;
                java.util.Map<String, java.util.List<String>> headers = new java.util.HashMap<>();
                headers.put("User-Agent", java.util.Collections.singletonList("openvisionx-android"));
                String socketToken = sharedPref.getString("token", null);
                if (socketToken != null && !socketToken.isEmpty()) {
                    headers.put("Authorization", java.util.Collections.singletonList("Bearer " + socketToken));
                }
                options.extraHeaders = headers;
                if (serverUrl.endsWith("/")) serverUrl = serverUrl.substring(0, serverUrl.length() - 1);
                mSocket = io.socket.client.IO.socket(serverUrl, options);
                mSocket.connect();

                String deviceId = android.provider.Settings.Secure.getString(getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
                int vendorId = sharedPref.getInt("vendor_id", 0);
                webrtcManager = new WebRTCManager(getApplicationContext(), mSocket, vendorId, deviceId);
            } catch (Exception e) {
                android.util.Log.e(TAG, "Socket/WebRTC initialization failed", e);
            }
        }
        // ----------------------

        viewFinder = findViewById(R.id.preview);
        captureView = findViewById(R.id.captureView);
        warningTxt = findViewById(R.id.txtWarning);
        livenessTxt = findViewById(R.id.txtLiveness);
        qualityTxt = findViewById(R.id.txtQuality);
        luminaceTxt = findViewById(R.id.txtLuminance);
        lytCaptureResult = findViewById(R.id.lytCaptureResult);
        cameraExecutorService = Executors.newFixedThreadPool(1);
        
        android.widget.LinearLayout btnEnroll = findViewById(R.id.buttonEnroll);
        if (isCaptureOnly) {
             TextView tv = (TextView) btnEnroll.getChildAt(0);
             tv.setText("USE PHOTO");
        }

        int initResult = LocalFaceEngineFacade.INSTANCE.ensureInitialized(getApplicationContext());
        if (initResult != LocalFaceEngineFacade.SUCCESS) {
            Toast.makeText(this, "Local face models could not be loaded (error " + initResult + ")", Toast.LENGTH_LONG).show();
            return;
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_DENIED) {

            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.CAMERA}, 1);
        } else {
            viewFinder.post(() ->
            {
                setUpCamera();
            });
        }

        captureView.setViewModeInterface(this);
        captureView.setViewMode(CaptureView.VIEW_MODE.NO_FACE_PREPARE);

        findViewById(R.id.buttonEnroll).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                if (isCaptureOnly) {
                     performCapture();
                     return;
                }

                if (capturedBitmap == null || capturedFace == null
                        || capturedTemplate == null
                        || consecutiveValidFrames < REQUIRED_VALID_FRAMES
                        || !FacePipeline.isLive(context, capturedFace, true)) {
                    Toast.makeText(context, "Hold still until the live-face check completes", Toast.LENGTH_SHORT).show();
                    return;
                }

                new Thread(() -> {
                    Bitmap faceImage = Utils.cropFace(capturedBitmap, capturedFace);
                    byte[] templates = capturedTemplate;
                    if (templates == null || templates.length == 0) return;

                    DBManager dbManager = new DBManager(context);
                    final int min = 10000;
                    final int max = 20000;
                    final int random = new Random().nextInt((max - min) + 1) + min;

                    dbManager.insertPerson("Person" + random, faceImage, templates, "", "", "");
                    runOnUiThread(() -> {
                        Toast.makeText(context, getString(R.string.person_enrolled), Toast.LENGTH_SHORT).show();
                        finish();
                    });
                }).start();
            }
        });
    }

    @Override
    public void onResume() {
        super.onResume();
    }

    @Override
    public void onPause() {
        super.onPause();
        captureView.setFaceBoxes(null);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (webrtcManager != null) {
            webrtcManager.dispose();
            webrtcManager = null;
        }
        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }
        if (cameraExecutorService != null) {
            cameraExecutorService.shutdown();
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);

        if(requestCode == 1) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                    == PackageManager.PERMISSION_GRANTED) {

                viewFinder.post(() ->
                {
                    setUpCamera();
                });
            }
        }
    }

    private void setUpCamera()
    {
        if (isFinishing() || !LocalFaceEngineFacade.INSTANCE.isInitialized()) return;
        ListenableFuture<ProcessCameraProvider> cameraProviderFuture = ProcessCameraProvider.getInstance(CaptureActivity.this);
        cameraProviderFuture.addListener(() -> {

            // CameraProvider
            try {
                cameraProvider = cameraProviderFuture.get();
            } catch (ExecutionException e) {
                Log.e(TAG, "Unable to obtain CameraX provider", e);
                return;
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }

            // Build and bind the camera use cases
            bindCameraUseCases();

        }, ContextCompat.getMainExecutor(CaptureActivity.this));
    }

    @SuppressLint({"RestrictedApi", "UnsafeExperimentalUsageError", "UnsafeOptInUsageError"})
    private void bindCameraUseCases()
    {
        int rotation = viewFinder.getDisplay().getRotation();
        Size targetSize = Utils.getOptimalResolution(this);

        int defaultLens = SettingsActivity.getCameraLens(this);
        if (forceFrontCamera) {
            defaultLens = CameraSelector.LENS_FACING_FRONT;
        }
        activeLensFacing = defaultLens;

        cameraSelector = new CameraSelector.Builder().requireLensFacing(defaultLens).build();
        try {
            if (!cameraProvider.hasCamera(cameraSelector)) {
                int fallbackLens = defaultLens == CameraSelector.LENS_FACING_FRONT
                        ? CameraSelector.LENS_FACING_BACK : CameraSelector.LENS_FACING_FRONT;
                CameraSelector fallback = new CameraSelector.Builder().requireLensFacing(fallbackLens).build();
                if (cameraProvider.hasCamera(fallback)) {
                    cameraSelector = fallback;
                    activeLensFacing = fallbackLens;
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Unable to query camera availability", e);
        }

        preview = new Preview.Builder()
                .setTargetResolution(targetSize)
                .setTargetRotation(rotation)
                .build();

        imageAnalyzer = new ImageAnalysis.Builder()
                .setBackpressureStrategy(STRATEGY_KEEP_ONLY_LATEST)
                .setTargetResolution(targetSize)
                // Set initial target rotation, we will have to call this again if rotation changes
                // during the lifecycle of this use case
                .setTargetRotation(rotation)
                .build();

        imageAnalyzer.setAnalyzer(cameraExecutorService, new FaceAnalyzer());

        cameraProvider.unbindAll();

        try {
            camera = cameraProvider.bindToLifecycle(
                    this, cameraSelector, preview, imageAnalyzer);

            preview.setSurfaceProvider(viewFinder.getSurfaceProvider());
        } catch (Exception exc) {
            exc.printStackTrace();
        }
    }

    @Override
    public void view5_finished() {

        if (capturedBitmap == null || capturedFace == null) return;
        FaceDetectionParam param = FacePipeline.secureDetectionParams(this);

        List<FaceBox> faceBoxes = LocalFaceEngineFacade.INSTANCE.faceDetection(capturedBitmap, param);
        if(faceBoxes != null && faceBoxes.size() > 0) {
            if(FacePipeline.isLive(context, faceBoxes.get(0), true)) {
                String msg = String.format("Liveness: Real, score = %.03f", faceBoxes.get(0).liveness);
                livenessTxt.setText(msg);
            }
            else {
                String msg = String.format("Liveness: Spoof, score =  %.03f", faceBoxes.get(0).liveness);
                livenessTxt.setText(msg);
            }
        }

        if(capturedFace.face_quality < 0.5f) {
            String msg = String.format("Quality: Low, score = %.03f", capturedFace.face_quality);
            qualityTxt.setText(msg);
        } else if(capturedFace.face_quality < 0.75f) {
            String msg = String.format("Quality: Medium, score = %.03f", capturedFace.face_quality);
            qualityTxt.setText(msg);
        } else {
            String msg = String.format("Quality: High, score = %.03f", capturedFace.face_quality);
            qualityTxt.setText(msg);
        }

        String msg = String.format("Luminance: %.03f", capturedFace.face_luminance);
        luminaceTxt.setText(msg);

        lytCaptureResult.setVisibility(View.VISIBLE);
    }

    class FaceAnalyzer implements ImageAnalysis.Analyzer
    {
        @OptIn(markerClass = ExperimentalGetImage.class)
        @Override
        public void analyze(@NonNull ImageProxy imageProxy)
        {
            analyzeImage(imageProxy);
        }
    }

    @OptIn(markerClass = ExperimentalGetImage.class)
    private void analyzeImage(ImageProxy imageProxy)
    {
        if(captureView.viewMode == CaptureView.VIEW_MODE.NO_FACE_PREPARE) {
            // Always release skipped frames or CameraX stops delivering images.
            imageProxy.close();
            return;
        }

        try
        {
            Image image = imageProxy.getImage();
            if (image == null) return;

            Image.Plane[] planes = image.getPlanes();
            // Hardened conversion handles padding (fixes Redmi/OEM detection failures during enrollment)
            byte[] nv21 = Utils.yuv420ToNv21(image);

            int rotationDegrees = imageProxy.getImageInfo().getRotationDegrees();
            int cameraMode = Utils.getCameraMode(rotationDegrees, activeLensFacing);

            // Limited diagnostic logging to prevent log flooding
            if (System.currentTimeMillis() % 1000 < 50) { 
                Log.d("CaptureActivity", "Frame: " + image.getWidth() + "x" + image.getHeight() + 
                    ", rot: " + rotationDegrees + ", mode: " + cameraMode + ", buffer: " + nv21.length);
            }

            Bitmap bitmap = LocalFaceEngineFacade.INSTANCE.yuv2Bitmap(nv21, image.getWidth(), image.getHeight(), cameraMode);

            if (bitmap == null) {
                return;
            }


            // --- Streaming Logic ---
            long currentTime = System.currentTimeMillis();
            if (currentTime - lastStreamTime > 1000) { // 1 FPS to avoid overloading
                lastStreamTime = currentTime;
                sendStreamFrame(bitmap);
            }
            // -----------------------

            FaceDetectionParam param = FacePipeline.secureDetectionParams(this);

            List<FaceBox> faceBoxes = LocalFaceEngineFacade.INSTANCE.faceDetection(bitmap, param);
            FACE_CAPTURE_STATE evaluatedState = checkFace(faceBoxes, this, bitmap.getWidth(), bitmap.getHeight());
            boolean collectingEnrollmentFrames = captureView.viewMode == CaptureView.VIEW_MODE.FACE_CIRCLE;
            byte[] candidateTemplate = null;
            if (collectingEnrollmentFrames && evaluatedState == FACE_CAPTURE_STATE.CAPTURE_OK) {
                candidateTemplate = LocalFaceEngineFacade.INSTANCE.templateExtraction(bitmap, faceBoxes.get(0));
            }
            final FACE_CAPTURE_STATE faceCaptureState =
                    collectingEnrollmentFrames
                            && evaluatedState == FACE_CAPTURE_STATE.CAPTURE_OK
                            && candidateTemplate == null
                            ? FACE_CAPTURE_STATE.LOW_QUALITY : evaluatedState;
            final byte[] validCandidateTemplate = candidateTemplate;

            if(captureView.viewMode == CaptureView.VIEW_MODE.REPEAT_NO_FACE_PREPARE) {
                if(faceCaptureState.compareTo(FACE_CAPTURE_STATE.NO_FACE) > 0) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            captureView.setViewMode(CaptureView.VIEW_MODE.TO_FACE_CIRCLE);
                        }
                    });
                }
            } else if(captureView.viewMode == CaptureView.VIEW_MODE.FACE_CIRCLE) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        captureView.setFrameSize(new Size(bitmap.getWidth(), bitmap.getHeight()));
                        captureView.setFaceBoxes(faceBoxes);

                        if (faceCaptureState != FACE_CAPTURE_STATE.CAPTURE_OK) {
                            resetEnrollmentSequence();
                        }

                        if(faceCaptureState == FACE_CAPTURE_STATE.NO_FACE) {
                            warningTxt.setText("");

                            captureView.setViewMode(CaptureView.VIEW_MODE.FACE_CIRCLE_TO_NO_FACE);
                        }
                        else if(faceCaptureState == FACE_CAPTURE_STATE.MULTIPLE_FACES)
                            warningTxt.setText("Multiple face detected!");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.FIT_IN_CIRCLE)
                            warningTxt.setText("Fit in circle!");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.MOVE_CLOSER)
                            warningTxt.setText("Move closer!");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.NO_FRONT)
                            warningTxt.setText("Not fronted face!");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.FACE_OCCLUDED)
                            warningTxt.setText("Face occluded!");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.EYE_CLOSED)
                            warningTxt.setText("Eye closed!");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.MOUTH_OPENED)
                            warningTxt.setText("Mouth opened!");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.LOW_QUALITY)
                            warningTxt.setText("Hold still for a clearer image");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.BAD_LIGHTING)
                            warningTxt.setText("Improve face lighting");
                        else if(faceCaptureState == FACE_CAPTURE_STATE.SPOOFED_FACE)
                            warningTxt.setText("Spoof face");
                        else {
                            enrollmentTemplates.add(validCandidateTemplate);
                            consecutiveValidFrames = enrollmentTemplates.size();
                            FaceBox candidate = faceBoxes.get(0);
                            if (capturedFace == null || candidate.face_quality > capturedFace.face_quality) {
                                capturedBitmap = bitmap;
                                capturedFace = candidate;
                            }
                            captureView.setCapturedBitmap(capturedBitmap);
                            if (consecutiveValidFrames >= REQUIRED_VALID_FRAMES) {
                                capturedTemplate = LocalFaceEngineFacade.INSTANCE.aggregateTemplates(enrollmentTemplates);
                                if (capturedTemplate != null) {
                                    warningTxt.setText("");
                                    captureView.setViewMode(CaptureView.VIEW_MODE.FACE_CAPTURE_PREPARE);
                                } else {
                                    resetEnrollmentSequence();
                                    warningTxt.setText("Unable to build face template; try again");
                                }
                            } else {
                                warningTxt.setText("Hold still " + consecutiveValidFrames
                                        + "/" + REQUIRED_VALID_FRAMES);
                            }
                        }
                    }
                });
            } else if(captureView.viewMode == CaptureView.VIEW_MODE.FACE_CAPTURE_PREPARE) {
                if(faceCaptureState == FACE_CAPTURE_STATE.CAPTURE_OK) {
                    if (isCaptureOnly && consecutiveValidFrames >= REQUIRED_VALID_FRAMES) {
                        runOnUiThread(() -> performCapture());
                    }
                } else {
                    resetEnrollmentSequence();
                    runOnUiThread(() -> captureView.setViewMode(CaptureView.VIEW_MODE.FACE_CIRCLE));
                }
            } else if(captureView.viewMode == CaptureView.VIEW_MODE.FACE_CAPTURE_DONE) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        cameraProvider.unbindAll();
                    }
                });
            }
        }
        catch (Exception e)
        {
            e.printStackTrace();
        }
        finally
        {
            imageProxy.close();
        }
    }

    private void performCapture() {
        if (isCapturing) return;
        if (capturedBitmap == null || capturedFace == null
                || capturedTemplate == null
                || consecutiveValidFrames < REQUIRED_VALID_FRAMES
                || !FacePipeline.isLive(context, capturedFace, true)) {
            Toast.makeText(context, "Hold still until the live-face check completes", Toast.LENGTH_SHORT).show();
            return;
        }
        isCapturing = true;

        // Stop camera updates to prevent race conditions and free resources
        runOnUiThread(() -> {
            try {
                if (cameraProvider != null) {
                    cameraProvider.unbindAll();
                }
            } catch (Exception e) {
                e.printStackTrace();
            }
        });

        final Bitmap bitmapToSave = capturedBitmap; // Capture local reference
        final byte[] templateToSave = capturedTemplate;

        if (bitmapToSave != null) {
            Toast.makeText(context, "Face Captured!", Toast.LENGTH_SHORT).show();
            
            new Thread(() -> {
                try {
                    android.net.Uri fileUri = Utils.saveBitmapToCache(context, bitmapToSave);
                    byte[] faceTemplate = templateToSave;
                    runOnUiThread(() -> {
                        if (fileUri != null) {
                            Intent resultIntent = new Intent();
                            resultIntent.putExtra("image_uri", fileUri.toString());
                            if (faceTemplate != null && faceTemplate.length > 0) {
                                resultIntent.putExtra("face_template", faceTemplate);
                                resultIntent.putExtra("face_verified", true);
                            }
                            setResult(RESULT_OK, resultIntent);
                            finish();
                        } else {
                            isCapturing = false;
                            Toast.makeText(context, "Failed to save image", Toast.LENGTH_SHORT).show();
                        }
                    });
                } catch (Exception e) {
                    e.printStackTrace();
                    runOnUiThread(() -> {
                         isCapturing = false;
                         Toast.makeText(context, "Error saving image", Toast.LENGTH_SHORT).show();
                    });
                }
            }).start();
        } else {
             isCapturing = false;
        }
    }

    public static FACE_CAPTURE_STATE checkFace(List<FaceBox> faceBoxes, Context context, int width, int height) {
        return FacePipeline.enrollmentState(faceBoxes, context, width, height);
    }

    private void resetEnrollmentSequence() {
        consecutiveValidFrames = 0;
        enrollmentTemplates.clear();
        capturedTemplate = null;
        capturedBitmap = null;
        capturedFace = null;
    }

    private void sendStreamFrame(Bitmap originalBitmap) {
        if (webrtcManager != null) {
            webrtcManager.onNewFrame(originalBitmap);
        }

        new Thread(() -> {
            try {
                // Resize for speed (e.g., 320px width)
                int width = 320;
                int height = (int) (originalBitmap.getHeight() * ((float) width / originalBitmap.getWidth()));
                Bitmap scaled = Bitmap.createScaledBitmap(originalBitmap, width, height, false);

                ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
                scaled.compress(Bitmap.CompressFormat.JPEG, 60, byteArrayOutputStream);
                byte[] byteArray = byteArrayOutputStream.toByteArray();
                String encoded = Base64.encodeToString(byteArray, Base64.NO_WRAP);
                String base64Image = "data:image/jpeg;base64," + encoded;

                // Get Vendor ID
                android.content.SharedPreferences prefs = context.getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE);
                int vendorId = prefs.getInt("vendor_id", -1);
                Integer vendorIdObj = (vendorId != -1) ? vendorId : null;

                float batteryLevel = Utils.getBatteryLevel(context);
                String deviceId = android.provider.Settings.Secure.getString(context.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
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
            }
        }).start();
    }
}
