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
import android.util.Size;

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
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;
import com.ocp.facesdk.FaceBox;
import com.ocp.facesdk.FaceDetectionParam;
import com.ocp.facesdk.FaceSDK;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import android.util.Base64;
import java.io.ByteArrayOutputStream;
import com.faceplugin.facerecognition.api.StreamRequest;

import com.faceplugin.facerecognition.api.GreetingResponse;
import com.faceplugin.facerecognition.api.GreetingService;
import com.faceplugin.facerecognition.api.PersonEventRequest;
import com.faceplugin.facerecognition.api.RetrofitClient;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;
import android.widget.Toast;
import android.util.Log;

import android.speech.tts.TextToSpeech;
import java.util.Locale;
import java.util.Date;
import java.text.SimpleDateFormat;

import android.media.AudioManager;
import android.media.ToneGenerator;
import android.provider.Settings;
import io.socket.client.IO;
import io.socket.client.Socket;
import org.json.JSONObject;
import java.net.URISyntaxException;

public class CameraActivity extends AppCompatActivity implements TextToSpeech.OnInitListener {

    public static String BASE_URL = "http://192.168.1.102:5001"; // Default
    private Socket mSocket;
    {
        try {
            // Need to get this from preferences ideally
            mSocket = IO.socket(BASE_URL);
        } catch (URISyntaxException e) {
            e.printStackTrace();
        }
    }

    static String TAG = CameraActivity.class.getSimpleName();
    static int PREVIEW_WIDTH = 720;
    static int PREVIEW_HEIGHT = 1280;

    private long lastApiCallTime = 0;
    private long lastStreamTime = 0;
    private String lastPersonName = "";
    
    private TextToSpeech tts;

    private ExecutorService cameraExecutorService;
    private PreviewView viewFinder;
    private Preview preview        = null;
    private ImageAnalysis imageAnalyzer  = null;
    private Camera camera         = null;
    private CameraSelector        cameraSelector = null;
    private ProcessCameraProvider cameraProvider = null;

    private FaceView faceView;

    private Context context;

    private Boolean recognized = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_camera);

        // --- Socket.IO Init ---
        android.content.SharedPreferences sharedPref = getSharedPreferences("app_prefs", Context.MODE_PRIVATE);
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

        context = this;

        viewFinder = findViewById(R.id.preview);
        faceView = findViewById(R.id.faceView);
        cameraExecutorService = Executors.newFixedThreadPool(1);

        tts = new TextToSpeech(this, this);

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_DENIED) {

            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.CAMERA}, 1);
        } else {
            viewFinder.post(() ->
            {
                setUpCamera();
            });
        }
    }

    @Override
    public void onResume() {
        super.onResume();

        recognized = false;
    }

    @Override
    public void onPause() {
        super.onPause();

        faceView.setFaceBoxes(null);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }
        if (tts != null) {
            tts.stop();
            tts.shutdown();
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
        ListenableFuture<ProcessCameraProvider> cameraProviderFuture = ProcessCameraProvider.getInstance(CameraActivity.this);
        cameraProviderFuture.addListener(() -> {

            // CameraProvider
            try {
                cameraProvider = cameraProviderFuture.get();
            } catch (ExecutionException e) {
            } catch (InterruptedException e) {
            }

            // Build and bind the camera use cases
            bindCameraUseCases();

        }, ContextCompat.getMainExecutor(CameraActivity.this));
    }

    @SuppressLint({"RestrictedApi", "UnsafeExperimentalUsageError", "UnsafeOptInUsageError"})
    private void bindCameraUseCases()
    {
        int rotation = viewFinder.getDisplay().getRotation();

        cameraSelector = new CameraSelector.Builder().requireLensFacing(SettingsActivity.getCameraLens(this)).build();

        preview = new Preview.Builder()
                .setTargetResolution(new Size(PREVIEW_WIDTH, PREVIEW_HEIGHT))
                .setTargetRotation(rotation)
                .build();

        imageAnalyzer = new ImageAnalysis.Builder()
                .setBackpressureStrategy(STRATEGY_KEEP_ONLY_LATEST)
                .setTargetResolution(new Size(PREVIEW_WIDTH, PREVIEW_HEIGHT))
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
        }
    }

    private void sendPersonEvent(boolean detected, boolean recognized, String personId, String name, float confidence, Bitmap image) {
        GreetingService service = RetrofitClient.getService();
        
        // Resize image to max 320px width to ensure successful upload and save bandwidth
        Bitmap resizedBitmap = Utils.resizeBitmap(image, 320);
        String imageBase64 = Utils.bitmapToBase64(resizedBitmap);

        // Generate timestamp from mobile
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US);
        String timestamp = sdf.format(new Date());
        
        // Use constructor with is_attendance=true explicitly and include timestamp
        PersonEventRequest request = new PersonEventRequest(detected, recognized, personId, name, confidence, imageBase64, true, timestamp);
        
        service.sendPersonEvent(request).enqueue(new Callback<GreetingResponse>() {
            @Override
            public void onResponse(Call<GreetingResponse> call, Response<GreetingResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    GreetingResponse greeting = response.body();
                    if (greeting.isSpeak()) {
                        runOnUiThread(() -> {
                            Toast.makeText(CameraActivity.this, greeting.getText(), Toast.LENGTH_LONG).show();
                        });
                        
                        // TTS commented out
                        /*
                        if (tts != null) {
                            tts.speak(greeting.getText(), TextToSpeech.QUEUE_FLUSH, null, null);
                        }
                        */

                        // Play Sound
                        playAttendanceSound(greeting.getStatus());
                    }
                }
            }

            @Override
            public void onFailure(Call<GreetingResponse> call, Throwable t) {
                // Log error or ignore
                Log.e(TAG, "API Error", t);
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

    class FaceAnalyzer implements ImageAnalysis.Analyzer
    {
        @OptIn(markerClass = ExperimentalGetImage.class)
        @Override
        public void analyze(@NonNull ImageProxy imageProxy)
        {
            analyzeImage(imageProxy);
        }
    }

    private void sendStreamFrame(Bitmap originalBitmap) {
        if (mSocket == null || !mSocket.connected()) return;

        new Thread(() -> {
            try {
                // Resize to reduce bandwidth
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
    private void analyzeImage(ImageProxy imageProxy)
    {
        if(recognized == true) {
            imageProxy.close();
            return;
        }

        try
        {
            Image image = imageProxy.getImage();

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
            if(SettingsActivity.getCameraLens(context) == CameraSelector.LENS_FACING_BACK) {
                cameraMode = 6;
            }
            Bitmap bitmap  = FaceSDK.yuv2Bitmap(nv21, image.getWidth(), image.getHeight(), cameraMode);

            // --- Streaming Logic ---
            long now = System.currentTimeMillis();
            if (now - lastStreamTime > 500) { // 2 FPS
                lastStreamTime = now;
                sendStreamFrame(bitmap);
            }
            // -----------------------

            FaceDetectionParam faceDetectionParam = new FaceDetectionParam();
            faceDetectionParam.check_liveness = true;
            faceDetectionParam.check_liveness_level = SettingsActivity.getLivenessLevel(this);
            List<FaceBox> faceBoxes = FaceSDK.faceDetection(bitmap, faceDetectionParam);

            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    faceView.setFrameSize(new Size(bitmap.getWidth(), bitmap.getHeight()));
                    faceView.setFaceBoxes(faceBoxes);
                }
            });

            if(faceBoxes.size() > 0) {
                FaceBox faceBox = faceBoxes.get(0);
                if(faceBox.liveness > SettingsActivity.getLivenessThreshold(context)) {
                    byte[] templates = FaceSDK.templateExtraction(bitmap, faceBox);

                    float maxSimiarlity = 0;
                    Person maximiarlityPerson = null;
                    for(Person person : DBManager.personList) {
                        float similarity = FaceSDK.similarityCalculation(templates, person.templates);
                        if(similarity > maxSimiarlity) {
                            maxSimiarlity = similarity;
                            maximiarlityPerson = person;
                        }
                    }

                    boolean isRecognized = maxSimiarlity > SettingsActivity.getIdentifyThreshold(this);
                    String personName = isRecognized ? maximiarlityPerson.name : null;

                    // Update UI with recognized name
                    runOnUiThread(() -> {
                        faceView.setRecognizedName(personName);
                    });
                    
                    long currentTime = System.currentTimeMillis();
                    boolean isSamePerson = (personName != null && personName.equals(lastPersonName)) || (personName == null && lastPersonName == null);
                    
                    if (!isSamePerson || (currentTime - lastApiCallTime > 5000)) {
                        sendPersonEvent(true, isRecognized, personName, personName, maxSimiarlity, bitmap);
                        lastApiCallTime = currentTime;
                        lastPersonName = personName;
                    }
                }
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
}
