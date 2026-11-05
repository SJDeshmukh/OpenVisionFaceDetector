package com.faceplugin.facerecognition;

import com.faceplugin.faceengine.FaceTemplateCodec;

/** Exact cosine matching against the in-memory employee gallery. */
final class FaceGalleryMatcher {
    static final class Match {
        final Person person;
        final float similarity;

        Match(Person person, float similarity) {
            this.person = person;
            this.similarity = similarity;
        }
    }

    private FaceGalleryMatcher() {}

    static Match bestMatch(byte[] queryTemplate, Person[] people) {
        float[] query = FaceTemplateCodec.decode(queryTemplate);
        if (query == null || people == null || people.length == 0) return null;

        Person bestPerson = null;
        float bestSimilarity = 0f;
        for (Person person : people) {
            if (person == null) continue;
            float[] candidate = person.embeddingForMatching();
            if (candidate == null || candidate.length != query.length) continue;

            float similarity = dot(query, candidate);
            if (similarity > bestSimilarity) {
                bestSimilarity = similarity;
                bestPerson = person;
            }
        }
        return bestPerson == null ? null : new Match(bestPerson, bestSimilarity);
    }

    private static float dot(float[] first, float[] second) {
        double similarity = 0d;
        for (int i = 0; i < first.length; i++) {
            similarity += (double) first[i] * second[i];
        }
        if (!Double.isFinite(similarity)) return 0f;
        return (float) Math.max(0d, Math.min(1d, similarity));
    }
}
