package com.faceplugin.facerecognition;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.util.AttributeSet;
import android.util.Size;
import android.view.View;

import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import com.ocp.facesdk.FaceBox;

import java.util.ArrayList;
import java.util.List;

public class FaceView extends View {

    private Context context;
    private Paint realPaint;
    private Paint spoofPaint;
    private Paint successPaint;
    private Paint meshGlowPaint;
    private Paint meshPaint;
    private Paint meshPointPaint;

    private Size frameSize;

    private List<FaceBox> faceBoxes;
    private String recognizedName = null;
    private List<String> recognizedNames;

    private static final int[] LANDMARK_EDGES_68 = new int[] {
            0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16,
            17, 18, 18, 19, 19, 20, 20, 21,
            22, 23, 23, 24, 24, 25, 25, 26,
            27, 28, 28, 29, 29, 30,
            31, 32, 32, 33, 33, 34, 34, 35,
            30, 31, 30, 35,
            36, 37, 37, 38, 38, 39, 39, 40, 40, 41, 41, 36,
            42, 43, 43, 44, 44, 45, 45, 46, 46, 47, 47, 42,
            48, 49, 49, 50, 50, 51, 51, 52, 52, 53, 53, 54, 54, 55, 55, 56, 56, 57, 57, 58, 58, 59, 59, 48,
            60, 61, 61, 62, 62, 63, 63, 64, 64, 65, 65, 66, 66, 67, 67, 60,
            48, 60, 54, 64
    };

    private final float[] meshLineBuffer = new float[(LANDMARK_EDGES_68.length / 2) * 4];

    public FaceView(Context context) {
        this(context, null);

        this.context = context;
        init();
    }

    public FaceView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        this.context = context;

        init();
    }

    public void init() {
        setLayerType(View.LAYER_TYPE_SOFTWARE, null);

        realPaint = new Paint();
        realPaint.setStyle(Paint.Style.STROKE);
        realPaint.setStrokeWidth(3);
        realPaint.setColor(Color.WHITE);
        realPaint.setAntiAlias(true);
        realPaint.setTextSize(50);

        spoofPaint = new Paint();
        spoofPaint.setStyle(Paint.Style.STROKE);
        spoofPaint.setStrokeWidth(3);
        spoofPaint.setColor(ContextCompat.getColor(context, R.color.ai_error_red));
        spoofPaint.setAntiAlias(true);
        spoofPaint.setTextSize(50);

        successPaint = new Paint();
        successPaint.setStyle(Paint.Style.STROKE);
        successPaint.setStrokeWidth(6);
        successPaint.setColor(Color.WHITE);
        successPaint.setAntiAlias(true);

        float density = getResources().getDisplayMetrics().density;
        int meshColor = Color.rgb(34, 211, 238);

        meshGlowPaint = new Paint();
        meshGlowPaint.setStyle(Paint.Style.STROKE);
        meshGlowPaint.setStrokeWidth(6f * density);
        meshGlowPaint.setColor(meshColor);
        meshGlowPaint.setAlpha(70);
        meshGlowPaint.setAntiAlias(true);

        meshPaint = new Paint();
        meshPaint.setStyle(Paint.Style.STROKE);
        meshPaint.setStrokeWidth(2f * density);
        meshPaint.setColor(meshColor);
        meshPaint.setAlpha(210);
        meshPaint.setAntiAlias(true);

        meshPointPaint = new Paint();
        meshPointPaint.setStyle(Paint.Style.FILL);
        meshPointPaint.setColor(meshColor);
        meshPointPaint.setAlpha(230);
        meshPointPaint.setAntiAlias(true);
    }

    public void setFrameSize(Size frameSize)
    {
        this.frameSize = frameSize;
    }

    public void setFaceBoxes(List<FaceBox> faceBoxes)
    {
        this.faceBoxes = faceBoxes;
        invalidate();
    }

    public void setRecognizedName(String name) {
        this.recognizedName = name;
        this.recognizedNames = null;
        invalidate();
    }

    public void setRecognizedNames(List<String> names) {
        if (names == null) {
            this.recognizedNames = null;
        } else {
            this.recognizedNames = new ArrayList<>(names);
        }
        invalidate();
    }

    private boolean successAnimating = false;
    private long successAnimationStart = 0L;
    private static final long SUCCESS_ANIMATION_DURATION_MS = 500L;

    public void startSuccessCircleAnimation() {
        successAnimating = true;
        successAnimationStart = System.currentTimeMillis();
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);

        if (frameSize != null &&  faceBoxes != null) {
            float x_scale = this.frameSize.getWidth() / (float)canvas.getWidth();
            float y_scale = this.frameSize.getHeight() / (float)canvas.getHeight();

            for (int i = 0; i < faceBoxes.size(); i++) {
                FaceBox faceBox = faceBoxes.get(i);

                if (faceBox.liveness < SettingsActivity.getLivenessThreshold(context))
                {
                    spoofPaint.setStrokeWidth(3);
                    spoofPaint.setStyle(Paint.Style.FILL_AND_STROKE);
                    canvas.drawText("SPOOF " + faceBox.liveness, (faceBox.x1 / x_scale) + 10, (faceBox.y1 / y_scale) - 30, spoofPaint);

                    spoofPaint.setStrokeWidth(5);
                    spoofPaint.setStyle(Paint.Style.STROKE);
                    canvas.drawRect(new Rect((int)(faceBox.x1 / x_scale), (int)(faceBox.y1 / y_scale),
                            (int)(faceBox.x2 / x_scale), (int)(faceBox.y2 / y_scale)), spoofPaint);
                }
                else
                {
                    String nameForBox = recognizedName;
                    if (recognizedNames != null && i < recognizedNames.size()) {
                        nameForBox = recognizedNames.get(i);
                    }
                    boolean isUnknown = nameForBox != null && nameForBox.equalsIgnoreCase("Unknown");

                    realPaint.setStrokeWidth(3);
                    realPaint.setStyle(Paint.Style.FILL_AND_STROKE);

                    if (!isUnknown && nameForBox != null && !nameForBox.isEmpty()) {
                        String statusText = "ID: " + nameForBox;
                        canvas.drawText(statusText, (faceBox.x1 / x_scale) + 10, (faceBox.y1 / y_scale) - 30, realPaint);
                    }

                    realPaint.setStyle(Paint.Style.STROKE);
                    realPaint.setStrokeWidth(5);

                    Rect rect = new Rect(
                            (int) (faceBox.x1 / x_scale),
                            (int) (faceBox.y1 / y_scale),
                            (int) (faceBox.x2 / x_scale),
                            (int) (faceBox.y2 / y_scale)
                    );

                    if (isUnknown) {
                        float cornerLength = 40f * getResources().getDisplayMetrics().density;

                        float left = rect.left;
                        float top = rect.top;
                        float right = rect.right;
                        float bottom = rect.bottom;

                        canvas.drawLine(left, top, left + cornerLength, top, realPaint);
                        canvas.drawLine(left, top, left, top + cornerLength, realPaint);

                        canvas.drawLine(right - cornerLength, top, right, top, realPaint);
                        canvas.drawLine(right, top, right, top + cornerLength, realPaint);

                        canvas.drawLine(left, bottom - cornerLength, left, bottom, realPaint);
                        canvas.drawLine(left, bottom, left + cornerLength, bottom, realPaint);

                        canvas.drawLine(right - cornerLength, bottom, right, bottom, realPaint);
                        canvas.drawLine(right, bottom - cornerLength, right, bottom, realPaint);
                    } else {
                        canvas.drawRect(rect, realPaint);
                    }

                    if (faceBox.landmarks_68 != null && faceBox.landmarks_68.length >= 136) {
                        int edgeCount = LANDMARK_EDGES_68.length / 2;
                        for (int e = 0; e < edgeCount; e++) {
                            int a = LANDMARK_EDGES_68[e * 2];
                            int b = LANDMARK_EDGES_68[e * 2 + 1];
                            float ax = faceBox.landmarks_68[a * 2] / x_scale;
                            float ay = faceBox.landmarks_68[a * 2 + 1] / y_scale;
                            float bx = faceBox.landmarks_68[b * 2] / x_scale;
                            float by = faceBox.landmarks_68[b * 2 + 1] / y_scale;

                            int o = e * 4;
                            meshLineBuffer[o] = ax;
                            meshLineBuffer[o + 1] = ay;
                            meshLineBuffer[o + 2] = bx;
                            meshLineBuffer[o + 3] = by;
                        }

                        canvas.drawLines(meshLineBuffer, 0, edgeCount * 4, meshGlowPaint);
                        canvas.drawLines(meshLineBuffer, 0, edgeCount * 4, meshPaint);

                        float r = 1.8f * getResources().getDisplayMetrics().density;
                        for (int p = 0; p < 68; p++) {
                            float px = faceBox.landmarks_68[p * 2] / x_scale;
                            float py = faceBox.landmarks_68[p * 2 + 1] / y_scale;
                            canvas.drawCircle(px, py, r, meshPointPaint);
                        }
                    }
                }
            }

            if (successAnimating && faceBoxes.size() > 0) {
                long elapsed = System.currentTimeMillis() - successAnimationStart;
                float progress = elapsed / (float) SUCCESS_ANIMATION_DURATION_MS;
                if (progress >= 1f) {
                    successAnimating = false;
                } else {
                    FaceBox faceBox = faceBoxes.get(0);
                    float cx = (float) ((faceBox.x1 / x_scale) + (faceBox.x2 / x_scale)) / 2f;
                    float cy = (float) ((faceBox.y1 / y_scale) + (faceBox.y2 / y_scale)) / 2f;
                    float width = (float) ((faceBox.x2 - faceBox.x1) / x_scale);
                    float height = (float) ((faceBox.y2 - faceBox.y1) / y_scale);
                    float maxRadius = Math.max(width, height) / 2f + 20f;
                    float radius = maxRadius * (1f - progress);

                    canvas.drawCircle(cx, cy, radius, successPaint);
                    postInvalidateOnAnimation();
                }
            }
        }
    }
}
