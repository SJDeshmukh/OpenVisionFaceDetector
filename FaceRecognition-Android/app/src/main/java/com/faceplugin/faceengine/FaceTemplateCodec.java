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

    /** Returns null for malformed or unrecognized templates. Supports FID1 (2056 bytes) and raw 2048-byte float vectors (LE/BE). */
    public static float[] decode(byte[] bytes) {
        if (bytes == null) return null;
        if (bytes.length == HEADER_SIZE + EMBEDDING_SIZE * Float.BYTES) {
            if (Arrays.equals(MAGIC, Arrays.copyOfRange(bytes, 0, MAGIC.length))) {
                ByteBuffer buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN);
                buffer.position(MAGIC.length);
                if (buffer.getInt() == EMBEDDING_SIZE) {
                    float[] embedding = new float[EMBEDDING_SIZE];
                    for (int i = 0; i < embedding.length; i++) embedding[i] = buffer.getFloat();
                    return normalizedCopy(embedding);
                }
            }
        }
        if (bytes.length == EMBEDDING_SIZE * Float.BYTES) {
            // Little Endian (numpy tobytes)
            try {
                ByteBuffer leBuf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
                float[] leEmbedding = new float[EMBEDDING_SIZE];
                for (int i = 0; i < leEmbedding.length; i++) leEmbedding[i] = leBuf.getFloat();
                float[] leNorm = normalizedCopy(leEmbedding);
                if (leNorm != null) return leNorm;
            } catch (Exception ignored) {}

            // Big Endian
            try {
                ByteBuffer beBuf = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN);
                float[] beEmbedding = new float[EMBEDDING_SIZE];
                for (int i = 0; i < beEmbedding.length; i++) beEmbedding[i] = beBuf.getFloat();
                return normalizedCopy(beEmbedding);
            } catch (Exception ignored) {}
        }
        return null;
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
