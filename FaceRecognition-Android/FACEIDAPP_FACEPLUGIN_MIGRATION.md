# FaceIDApp engine integration

The Android app no longer links to or calls the FacePlugin AAR. The face
pipeline is implemented in this repository with the source and model contracts
from `/home/expenzinglogonuser/Documents/baidu/FaceIDApp`.

## Runtime pipeline

| Stage | Local implementation |
|---|---|
| Detection and five landmarks | SCRFD-500M, 640 x 640 ONNX input |
| Passive anti-spoofing | MiniFASNet V1SE and V2 softmax ensemble |
| Screen-replay check | Windowed 2-D FFT Moire analysis |
| Alignment and recognition | Five-point ArcFace alignment and 512-D MobileFaceNet embedding |
| Matching | Cosine similarity, starting threshold 0.62 |
| Enrollment | Seven live, valid frames averaged and L2-normalized |

`LocalFaceEngineFacade` is the application-facing boundary. It delegates to
`LocalFaceEngine`, which owns the four ONNX sessions. `FacePipeline` applies
the shared liveness and quality policy before any template is extracted.

The model contracts and inference logic under `com.example.faceid.ml` come from
FaceIDApp, with explicit recycling added for continuous-camera bitmap
intermediates. These model assets are copied byte-for-byte:

- `scrfd_500m.onnx`
- `minifasnet_v1se.onnx`
- `minifasnet_v2.onnx`
- `mobilefacenet_arcface.onnx`

## Template compatibility

New templates are versioned (`FID1`) 512-float embeddings. Earlier FacePlugin
templates are intentionally rejected by local similarity calculation because
the two models do not share an embedding space. Existing people therefore need
one face re-enrollment after upgrading; silently comparing the old blobs would
produce unreliable matches.

The server continues to store the Android template as an opaque Base64 value.
Normal Android enrollment and recognition stay local. Server-generated ArcFace
embeddings are a separate gallery and must not be mixed with this mobile model.

The existing SQLite/cloud person schema is retained because it is part of this
app's synchronization architecture. FaceIDApp's standalone Room repository was
not copied: replacing the data layer would disconnect existing person, tenant,
attendance, and sync records. The detection, liveness, alignment, enrollment,
and matching logic has been replaced.

## Legacy application identifier

The Android `applicationId` still contains `com.faceplugin...`. It is only the
published app identity used by Android/Firebase and is not an SDK dependency.
Changing it would install a different application and break upgrade continuity.

The old AAR files and their Gradle dependency have been removed, so their code,
native libraries, and model assets are not packaged in the APK.

## Validation before release

The imported ONNX contracts and SHA-256 hashes were checked against FaceIDApp.
Run a device matrix smoke test before release: registration to 7/7, genuine and
impostor matching, print attack, phone replay, camera rotation/mirroring, and
background/foreground recovery. The 0.62 recognition and 0.90 CNN-liveness
thresholds are conservative starting points and should be calibrated with
representative production data.
