package com.faceplugin.facerecognition;

import com.faceplugin.faceengine.FaceTemplateCodec;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

public class FaceGalleryMatcherTest {
    @Test
    public void selectsHighestCosineSimilarity() {
        float[] query = unitVector(0);
        Person exact = new Person("1", "Exact", FaceTemplateCodec.encode(unitVector(0)), "", "", "", "");
        Person different = new Person("2", "Different", FaceTemplateCodec.encode(unitVector(1)), "", "", "", "");

        FaceGalleryMatcher.Match match = FaceGalleryMatcher.bestMatch(
                FaceTemplateCodec.encode(query), new Person[]{different, exact});

        assertNotNull(match);
        assertEquals(exact, match.person);
        assertEquals(1f, match.similarity, 0.0001f);
    }

    @Test
    public void updatedTemplateIsUsedImmediately() {
        Person person = new Person("1", "Employee", FaceTemplateCodec.encode(unitVector(1)), "", "", "", "");
        person.setTemplates(FaceTemplateCodec.encode(unitVector(0)));

        FaceGalleryMatcher.Match match = FaceGalleryMatcher.bestMatch(
                FaceTemplateCodec.encode(unitVector(0)), new Person[]{person});

        assertNotNull(match);
        assertEquals(1f, match.similarity, 0.0001f);
    }

    @Test
    public void malformedGalleryTemplatesAreIgnored() {
        Person malformed = new Person("1", "Bad", new byte[]{1, 2, 3}, "", "", "", "");
        assertNull(FaceGalleryMatcher.bestMatch(
                FaceTemplateCodec.encode(unitVector(0)), new Person[]{malformed}));
    }

    private static float[] unitVector(int index) {
        float[] result = new float[FaceTemplateCodec.EMBEDDING_SIZE];
        result[index] = 1f;
        return result;
    }
}
