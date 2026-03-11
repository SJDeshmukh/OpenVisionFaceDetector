/* eslint-disable no-undef */
/**
 * AI Web Worker for Client-Side Face Detection and Recognition.
 * Uses MediaPipe for detection and ONNX Runtime Web for ArcFace embeddings.
 */

// Import scripts if not using ES modules in worker, 
// but since we use 'type: module' in ModelManager, we use imports.
import { FaceDetector, FilesetResolver } from 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.3/vision_bundle.mjs';
// Prefer local ORT distribution to avoid CORS/CDN blockers in dev
import * as ort from '/libs/ort.wasm.mjs';

console.log('[AI Worker] Worker script loaded.');

let faceDetector = null;
let recognitionSession = null;

// Configure ONNX to use local WASM path; disable proxy/threading for broader compatibility
try {
    if (ort && ort.env && ort.env.wasm) {
        ort.env.wasm.wasmPaths = '/libs/';
        ort.env.wasm.proxy = false;
        // numThreads>1 requires crossOriginIsolated; force 1 in dev
        ort.env.wasm.numThreads = 1;
    }
} catch (e) {
    // Leave defaults; server fallback will handle if ORT fails
}

/**
 * Initialize MediaPipe Face Detection
 */
async function initFaceDetection() {
    const vision = await FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.3/wasm"
    );

    faceDetector = await FaceDetector.createFromOptions(vision, {
        baseOptions: {
            modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
            delegate: "GPU"
        },
        runningMode: "IMAGE"
    });
    console.log('[AI Worker] Face Detector initialized.');
}

/**
 * Initialize ONNX Recognition (ArcFace)
 */
async function initRecognition() {
    try {
        // Prefer local model; fallback to a public ArcFace ONNX if missing
        const candidates = [
            '/models/mobilefacenet_arcface.onnx',
            '/models/arcface_ir_se50.onnx',
            'https://github.com/onnx/models/raw/main/vision/body_analysis/arcface/model/arcfaceresnet100-8.onnx'
        ];
        let modelUrl = candidates[0];
        try {
            // Probe local model existence from worker scope
            const r = await fetch(modelUrl, { method: 'HEAD' });
            if (!r.ok) {
                modelUrl = candidates[1];
            }
        } catch (_) {
            modelUrl = candidates[1];
        }

        const providers = ['wasm'];
        try {
            if (typeof navigator !== 'undefined' && navigator.gpu) {
                providers.unshift('webgpu');
            }
        } catch (_) { }
        recognitionSession = await ort.InferenceSession.create(modelUrl, { executionProviders: providers, graphOptimizationLevel: 'all' });
        console.log('[AI Worker] Recognition Session initialized with: ' + modelUrl);
    } catch (e) {
        console.error('[AI Worker] Failed to init recognition:', e);
    }
}

self.onmessage = async (e) => {
    const { type, payload } = e.data;

    if (type === 'INIT') {
        // Initialize subsystems; detection is fast, recognition deferred to first use
        try { await initFaceDetection(); } catch (e) { console.warn('[AI Worker] Detection init skipped:', e); }
        try { self.postMessage({ type: 'READY' }); } catch (_) { }
        return;
    }

    if (type === 'PROCESS_IMAGE') {
        if (!faceDetector) {
            self.postMessage({ type: 'ERROR', error: 'Detector not ready' });
            return;
        }

        try {
            const { imageBitmap, originalFileId } = payload;

            // Lazy load recognition model
            if (!recognitionSession) {
                console.log('[AI Worker] Lazy initializing recognition...');
                await initRecognition();
            }

            const width = imageBitmap.width;
            const height = imageBitmap.height;

            // 1. Perform Detection
            const detectionResult = await faceDetector.detect(imageBitmap);

            const faces = [];

            // Offscreen canvas for cropping
            const canvas = new OffscreenCanvas(width, height);
            const ctx = canvas.getContext('2d');
            ctx.drawImage(imageBitmap, 0, 0);

            for (const detection of detectionResult.detections) {
                const box = detection.boundingBox;

                // Extract Face Crop for Recognition
                let embedding = null;
                let faceBase64 = null;

                if (recognitionSession) {
                    // Prepare 112x112 crop for ArcFace
                    const faceCanvas = new OffscreenCanvas(112, 112);
                    const fCtx = faceCanvas.getContext('2d');

                    // Draw with slight padding to match backend Face Crop logic if needed
                    // For now, simple crop
                    fCtx.drawImage(imageBitmap, box.originX, box.originY, box.width, box.height, 0, 0, 112, 112);

                    const faceData = fCtx.getImageData(0, 0, 112, 112).data;
                    const float32Data = new Float32Array(3 * 112 * 112);

                    // Preprocessing: ArcFace usually expects (val - 127.5) / 127.5 to match [0, 1] -> [-1, 1]
                    // Backend uses (val/255.0 - 0.5) / 0.5 which is exactly (val - 127.5) / 127.5
                    for (let i = 0; i < 112 * 112; i++) {
                        float32Data[i] = (faceData[i * 4 + 0] - 127.5) / 127.5; // R
                        float32Data[112 * 112 + i] = (faceData[i * 4 + 1] - 127.5) / 127.5; // G
                        float32Data[2 * 112 * 112 + i] = (faceData[i * 4 + 2] - 127.5) / 127.5; // B
                    }

                    const tensor = new ort.Tensor('float32', float32Data, [1, 3, 112, 112]);
                    const output = await recognitionSession.run({ [recognitionSession.inputNames[0]]: tensor });

                    // L2 Normalization (often required for cosine similarity)
                    const rawEmb = output[recognitionSession.outputNames[0]].data;
                    let norm = 0;
                    for (let i = 0; i < rawEmb.length; i++) norm += rawEmb[i] * rawEmb[i];
                    norm = Math.sqrt(norm);
                    embedding = Array.from(rawEmb).map(v => v / (norm || 1));

                    // Also get a small thumbnail for the UI
                    const thumbBlob = await faceCanvas.convertToBlob({ type: 'image/jpeg', quality: 0.7 });
                    faceBase64 = await new Promise(r => {
                        const reader = new FileReader();
                        reader.onloadend = () => r(reader.result);
                        reader.readAsDataURL(thumbBlob);
                    });
                }

                faces.push({
                    box: [box.originX, box.originY, box.originX + box.width, box.originY + box.height],
                    score: detection.categories[0].score,
                    embedding: embedding,
                    thumbnail: faceBase64
                });
            }

            self.postMessage({
                type: 'RESULTS',
                payload: {
                    faces,
                    originalFileId
                }
            });

        } catch (err) {
            console.error('[AI Worker] PROCESS_IMAGE failed:', err);
            self.postMessage({ type: 'ERROR', error: err.message });
        }
    }
};
