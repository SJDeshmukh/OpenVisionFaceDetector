package com.faceplugin.faceengine;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

/** Versioned, model-specific serialization for normalized 512-D embeddings. */
public final class FaceTemplateCodec {
    public static final int EMBEDDING_SIZE = 512;
    private static final byte[] MAGIC = new byte[]{'F', 'I', 'D', '1'};
    private static final int HEADER_SIZE = 8;

    private FaceTemplateCodec() {}

    public static byte[] encode(float[] embedding) {
        float[] normalized = normalizedCopy(embedding);
        if (normalized == null || normalized.length != EMBEDDING_SIZE) {
            throw new IllegalArgumentException("Expected a finite, non-zero 512-D embedding");
        }
        ByteBuffer buffer = ByteBuffer.allocate(HEADER_SIZE + EMBEDDING_SIZE * Float.BYTES)
                .order(ByteOrder.BIG_ENDIAN);
        buffer.put(MAGIC);
        buffer.putInt(EMBEDDING_SIZE);
        for (float value : normalized) buffer.putFloat(value);
        return buffer.array();
    }

    /** Returns null for malformed or pre-FID1 templates. */
    public static float[] decode(byte[] bytes) {
        if (bytes == null || bytes.length != HEADER_SIZE + EMBEDDING_SIZE * Float.BYTES) return null;
        if (!Arrays.equals(MAGIC, Arrays.copyOfRange(bytes, 0, MAGIC.length))) return null;
        ByteBuffer buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN);
        buffer.position(MAGIC.length);
        if (buffer.getInt() != EMBEDDING_SIZE) return null;
        float[] embedding = new float[EMBEDDING_SIZE];
        for (int i = 0; i < embedding.length; i++) embedding[i] = buffer.getFloat();
        return normalizedCopy(embedding);
    }

    private static float[] normalizedCopy(float[] embedding) {
        if (embedding == null || embedding.length == 0) return null;
        double squaredNorm = 0.0;
        for (float value : embedding) {
            if (!Float.isFinite(value)) return null;
            squaredNorm += (double) value * value;
        }
        double norm = Math.sqrt(squaredNorm);
        if (!Double.isFinite(norm) || norm < 1e-8) return null;
        float[] result = new float[embedding.length];
        for (int i = 0; i < embedding.length; i++) result[i] = (float) (embedding[i] / norm);
        return result;
    }
}
