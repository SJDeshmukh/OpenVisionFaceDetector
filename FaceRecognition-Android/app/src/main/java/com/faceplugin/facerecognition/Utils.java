package com.faceplugin.facerecognition;

import android.content.Context;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.net.Uri;
import android.provider.MediaStore;

import com.ocp.facesdk.FaceBox;

import java.io.IOException;
import java.io.InputStream;

import android.media.Image;
import java.nio.ByteBuffer;
import androidx.camera.core.CameraSelector;

public class Utils {

    public static byte[] yuv420ToNv21(Image image) {
        Image.Plane[] planes = image.getPlanes();
        ByteBuffer yBuffer = planes[0].getBuffer();
        ByteBuffer uBuffer = planes[1].getBuffer();
        ByteBuffer vBuffer = planes[2].getBuffer();

        int ySize = yBuffer.remaining();
        int uSize = uBuffer.remaining();
        int vSize = vBuffer.remaining();

        byte[] nv21 = new byte[ySize + (ySize / 2)];

        // Full Y plane
        yBuffer.get(nv21, 0, ySize);

        // Interleave V and U (NV21: YYYY... VUVU...)
        int pos = ySize;
        int rowStride = planes[1].getRowStride();
        int pixelStride = planes[1].getPixelStride();
        int width = image.getWidth();
        int height = image.getHeight();

        for (int row = 0; row < height / 2; row++) {
            for (int col = 0; col < width / 2; col++) {
                int vuIdx = row * rowStride + col * pixelStride;
                nv21[pos++] = vBuffer.get(vuIdx);
                nv21[pos++] = uBuffer.get(vuIdx);
            }
        }

        return nv21;
    }

    public static int getCameraMode(int rotationDegrees, int lensFacing) {
        boolean isFront = lensFacing == CameraSelector.LENS_FACING_FRONT;
        
        // standard CameraX rotationDegrees is the clockwise rotation needed to make the image upright.
        // FaceSDK modes:
        // 0-3: Back Camera (no mirror), rotations 0, 90, 180, 270
        // 4-7: Front Camera (mirrored), rotations 0, 90, 180, 270
        
        int mode;
        switch (rotationDegrees) {
            case 0: mode = 0; break;
            case 90: mode = 1; break;
            case 180: mode = 2; break;
            case 270: mode = 3; break;
            default: mode = 0; break;
        }
        
        if (isFront) {
            return mode + 4;
        }
        return mode;
    }

    /**
     * Recommends a preview resolution based on the display aspect ratio.
     * Hardcoded 720x1280 can fail or stretch on some devices.
     */
    public static android.util.Size getOptimalResolution(Context context) {
        // Default fallback
        int targetWidth = 720;
        int targetHeight = 1280;
        
        try {
            android.util.DisplayMetrics metrics = context.getResources().getDisplayMetrics();
            float aspectRatio = (float) metrics.heightPixels / (float) metrics.widthPixels;
            
            // If aspect ratio is significantly different from 16:9, adjust
            if (Math.abs(aspectRatio - (16f/9f)) > 0.1) {
                // Keep width at 720 and adjust height to maintain aspect ratio
                targetHeight = (int) (targetWidth * aspectRatio);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        
        return new android.util.Size(targetWidth, targetHeight);
    }


    public static Bitmap cropFace(Bitmap src, FaceBox faceBox) {
        int centerX = (faceBox.x1 + faceBox.x2) / 2;
        int centerY = (faceBox.y1 + faceBox.y2) / 2;
        int cropWidth = (int)((faceBox.x2 - faceBox.x1) * 1.4f);

        int cropX1 = centerX - cropWidth / 2;
        int cropY1 = centerY - cropWidth / 2;
        int cropX2 = centerX + cropWidth / 2;
        int cropY2 = centerY + cropWidth / 2;
        if(cropX1 < 0) cropX1 = 0;
        if(cropX2 >= src.getWidth()) cropX2 = src.getWidth() - 1;
        if(cropY1 < 0) cropY1 = 0;
        if(cropY2 >= src.getHeight()) cropY2 = src.getHeight() - 1;


        int cropScaleWidth = 200;
        int cropScaleHeight = 200;
        float scaleWidth = ((float) cropScaleWidth) / (cropX2 - cropX1 + 1);
        float scaleHeight = ((float) cropScaleHeight) / (cropY2 - cropY1 + 1);

        final Matrix m = new Matrix();

        m.setScale(1.0f, 1.0f);
        m.postScale(scaleWidth, scaleHeight);
        final Bitmap cropped = Bitmap.createBitmap(src, cropX1, cropY1, (cropX2 - cropX1 + 1), (cropY2 - cropY1 + 1), m,
                true /* filter */);
        return cropped;
    }

    public static int getOrientation(Context context, Uri photoUri) {
        try (InputStream input = context.getContentResolver().openInputStream(photoUri)) {
            if (input == null) return 0;
            
            android.media.ExifInterface exif = new android.media.ExifInterface(input);
            int orientation = exif.getAttributeInt(android.media.ExifInterface.TAG_ORIENTATION, android.media.ExifInterface.ORIENTATION_NORMAL);
            
            switch (orientation) {
                case android.media.ExifInterface.ORIENTATION_ROTATE_90: return 90;
                case android.media.ExifInterface.ORIENTATION_ROTATE_180: return 180;
                case android.media.ExifInterface.ORIENTATION_ROTATE_270: return 270;
                default: return 0;
            }
        } catch (IOException e) {
            e.printStackTrace();
            return 0;
        }
    }

    public static Bitmap getCorrectlyOrientedImage(Context context, Uri photoUri) throws IOException {
        InputStream is = context.getContentResolver().openInputStream(photoUri);
        BitmapFactory.Options dbo = new BitmapFactory.Options();
        dbo.inJustDecodeBounds = true;
        BitmapFactory.decodeStream(is, null, dbo);
        is.close();

        int orientation = getOrientation(context, photoUri);

        Bitmap srcBitmap;
        is = context.getContentResolver().openInputStream(photoUri);
        srcBitmap = BitmapFactory.decodeStream(is);
        is.close();

        if (srcBitmap == null) return null;

        if (orientation > 0) {
            Matrix matrix = new Matrix();
            matrix.postRotate(orientation);
            srcBitmap = Bitmap.createBitmap(srcBitmap, 0, 0, srcBitmap.getWidth(),
                    srcBitmap.getHeight(), matrix, true);
        }

        return srcBitmap;
    }

    public static String bitmapToBase64(Bitmap bitmap) {
        if (bitmap == null) return null;
        java.io.ByteArrayOutputStream byteArrayOutputStream = null;
        try {
            byteArrayOutputStream = new java.io.ByteArrayOutputStream();
            bitmap.compress(Bitmap.CompressFormat.JPEG, 80, byteArrayOutputStream);
            byte[] byteArray = byteArrayOutputStream.toByteArray();
            return android.util.Base64.encodeToString(byteArray, android.util.Base64.NO_WRAP);
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        } finally {
            if (byteArrayOutputStream != null) {
                try {
                    byteArrayOutputStream.close();
                } catch (IOException e) {
                    e.printStackTrace();
                }
            }
        }
    }

    public static Bitmap resizeBitmap(Bitmap image, int maxWidth) {
        if (image == null) return null;
        if (maxWidth <= 0) return image;
        
        int width = image.getWidth();
        int height = image.getHeight();
        
        if (width <= maxWidth) return image;
        
        float ratio = (float) width / height;
        int newHeight = (int) (maxWidth / ratio);
        
        try {
            return Bitmap.createScaledBitmap(image, maxWidth, newHeight, false);
        } catch (OutOfMemoryError e) {
            // If OOM, return original or null
            return image;
        }
    }

    public static Uri saveBitmapToCache(Context context, Bitmap bitmap) {
        try {
            java.io.File cachePath = new java.io.File(context.getCacheDir(), "images");
            if (!cachePath.exists()) {
                cachePath.mkdirs();
            }
            java.io.File file = new java.io.File(cachePath, "temp_face.jpg");
            java.io.FileOutputStream stream = new java.io.FileOutputStream(file);
            bitmap.compress(Bitmap.CompressFormat.JPEG, 100, stream);
            stream.close();
            return androidx.core.content.FileProvider.getUriForFile(context, context.getPackageName() + ".provider", file);
        } catch (Exception e) {
            e.printStackTrace();
        }
        return null;
    }

    public static float getBatteryLevel(Context context) {
        try {
            android.content.Intent bat = context.registerReceiver(null, new android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED));
            if (bat == null) return -1f;
            int level = bat.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1);
            int scale = bat.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, -1);
            if (level == -1 || scale == -1) return -1f;
            return ((float) level / (float) scale) * 100.0f;
        } catch (Exception e) {
            return -1f;
        }
    }
}
