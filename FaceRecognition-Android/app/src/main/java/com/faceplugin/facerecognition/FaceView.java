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

    private Size frameSize;

    private List<FaceBox> faceBoxes;
    private String recognizedName = null;
    private List<String> recognizedNames;

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
