package com.faceplugin.faceengine;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

public class FaceTemplateCodecTest {
    @Test
    public void roundTripNormalizesEmbedding() {
        float[] embedding = new float[FaceTemplateCodec.EMBEDDING_SIZE];
        for (int i = 0; i < embedding.length; i++) embedding[i] = i + 1f;

        byte[] encoded = FaceTemplateCodec.encode(embedding);
        float[] decoded = FaceTemplateCodec.decode(encoded);

        assertEquals(2056, encoded.length);
        assertNotNull(decoded);
        double norm = 0.0;
        for (float value : decoded) norm += value * value;
        assertEquals(1.0, Math.sqrt(norm), 1e-5);
    }

    @Test
    public void rejectsLegacyMalformedAndNonFiniteTemplates() {
        assertNull(FaceTemplateCodec.decode(new byte[2048]));
        assertNull(FaceTemplateCodec.decode(new byte[2056]));

        float[] invalid = new float[FaceTemplateCodec.EMBEDDING_SIZE];
        invalid[0] = Float.NaN;
        try {
            FaceTemplateCodec.encode(invalid);
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError("Non-finite embedding accepted");
    }
}
