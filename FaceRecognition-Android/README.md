# Face Recognition Android

This app uses the in-repository, fully on-device pipeline ported from
`/home/expenzinglogonuser/Documents/baidu/FaceIDApp`. It does **not** link to or
invoke the former FacePlugin AAR.

```text
Camera frame
  -> SCRFD-500M detection + five landmarks
  -> quality/size/lighting policy
  -> MiniFASNet V1SE + V2 CNN ensemble
  -> Moire FFT screen-replay gate
  -> five-point ArcFace alignment
  -> MobileFaceNet 512-D normalized embedding
  -> cosine matching
```

Enrollment accepts seven consecutive valid, live frames and stores their
averaged, re-normalized embedding. Identification requires liveness before
feature extraction and three fresh consecutive matches before attendance or
verification side effects are allowed.

The four ONNX files are in `app/src/main/assets/models`; Gradle uses
`onnxruntime-android:1.18.0` and does not reference an AAR in `app/libs`.

## Build

Open the project in Android Studio with Android SDK 34 and JDK 17, then build
the desired `tapinx` or `attendx` flavor.

Before release, test on representative physical devices with genuine users,
impostors, printed photos, phone/tablet replay, all supported rotations, and
front/back cameras. Defaults (`0.62` recognition, `0.90` CNN liveness) must be
calibrated against production data rather than treated as universal values.

## Upgrade note

New embeddings use the model-specific `FID1` format. Templates made by the old
FacePlugin model are rejected because embeddings from different model spaces
cannot be compared safely. Existing users must re-enrol once after upgrading.

See [FACEIDAPP_FACEPLUGIN_MIGRATION.md](FACEIDAPP_FACEPLUGIN_MIGRATION.md) for
the integration details.

## Model licensing

Read [MODEL_LICENSES.md](MODEL_LICENSES.md) before distribution. In particular,
the bundled InsightFace pretrained weights are restricted to non-commercial
research unless you obtain an appropriate commercial license.
