import sys
import os
import cv2
import numpy as np
import base64
import torch

# Add paths to sys.path to allow imports
sys.path.append('/Users/hashteelab/Documents/trae_projects/face_detection/backend')
sys.path.append('/Users/hashteelab/Documents/trae_projects/face_detection')

from multiple_face_detection import app as mfd_app
from services.face_service import _normalize_vec, _detect_faces_from_bytes

def run_test():
    image_path = '/Users/hashteelab/Documents/trae_projects/face_detection/backend/audit_images/1773122150163_cbecfe41_student2.png'
    if not os.path.exists(image_path):
        print(f"Error: Test image not found at {image_path}")
        return

    print(f"--- Loading Test Image: {os.path.basename(image_path)} ---")
    img_bgr = cv2.imread(image_path)
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    # --- SIMULATE DETECTION PATH (services/face_service.py) ---
    print("\n[PATH 1] Simulating Detection Flow (face_service.py)...")
    # Params matching UI behavior
    params = {
        'enhancer': 'GFPGAN',
        'crop_mode': 'Portrait',
        'portrait_scale': 3.0,
        'gfpgan_upscale': 2,
        'preclean_whole': True,
        'preclean_level': 0.4
    }
    faces_det, _ = _detect_faces_from_bytes(img_bytes, params, vendor_id=None)
    
    if not faces_det:
        print("Error: No faces detected in detection flow!")
        return
    
    face1 = faces_det[0]
    emb_det_b64 = face1['emb_vec']
    emb_det = np.frombuffer(base64.b64decode(emb_det_b64), dtype=np.float32)
    print(f"Detection Embedding Vector (first 5): {emb_det[:5]}")

    # --- SIMULATE DIRECT BACKEND EMBEDDING (Used by faces.py and face_service.py) ---
    print("\n[PATH 2] Simulating Backend Embedding extraction (as in faces.py)...")
    from multiple_face_detection.app import _compute_centered_box
    
    # 1. Detect faces to get bounding boxes
    annotated, crops, df, _ = mfd_app.detect_faces(
        image_input=img_rgb,
        enhancer='GFPGAN',
        enhance_level=0.5,
        gfpgan_upscale=2,
        compute_embeddings=False,
        crop_mode='Portrait'
    )
    
    if df is None or len(df) == 0:
        print("Error: No faces detected in detect_faces!")
        return
    
    row = df.iloc[0]
    bx1, by1, bx2, by2 = int(row['x1']), int(row['y1']), int(row['x2']), int(row['y2'])
    iw, ih = img_rgb.shape[1], img_rgb.shape[0]
    
    # 2. Extract 1.2x Pure Face (exactly as in faces.py / face_service.py now)
    cx1, cy1, cx2, cy2 = _compute_centered_box(bx1, by1, bx2, by2, iw, ih, scale=1.2)
    pure_face = img_rgb[cy1:cy2, cx1:cx2]
    
    # 3. Enhance (exactly as in faces.py / face_service.py)
    lmks_local = None
    engine = mfd_app.get_realtime_engine()
    if engine:
        c3x1, c3y1, c3x2, c3y2 = mfd_app._compute_portrait_box(bx1, by1, bx2, by2, iw, ih, scale=1.5, margin=0.2)
        face_for_3d = img_rgb[c3y1:c3y2, c3x1:c3x2]
        if face_for_3d.size > 0:
            lmks_res = engine.extract_landmarks(face_for_3d)
            if lmks_res:
                lmks_item = lmks_res[0]
                lmks_global = lmks_item.copy()
                lmks_global[:, 0] += c3x1
                lmks_global[:, 1] += c3y1
                lmks_local = lmks_global.copy()
                lmks_local[:, 0] -= cx1
                lmks_local[:, 1] -= cy1

    pure_face_enh = mfd_app.get_gfpgan_manager().enhance_crop(pure_face, fidelity=0.9, upscale=2, landmarks=lmks_local)
    
    # MANDATORY: Resize to 512px minimum for consistent embedding extraction across all resolutions
    if min(pure_face_enh.shape[:2]) < 512:
        scale_f = 512.0 / min(pure_face_enh.shape[:2])
        pure_face_enh = cv2.resize(pure_face_enh, (int(pure_face_enh.shape[1] * scale_f), int(pure_face_enh.shape[0] * scale_f)), interpolation=cv2.INTER_LANCZOS4)
    
    # 4. Embed
    emb_backend = mfd_app.get_embedder().embed(pure_face_enh)
    emb_backend = _normalize_vec(emb_backend)
    print(f"Backend Simulation Embedding Vector (first 5): {emb_backend[:5]}")

    # --- COMPARE ---
    dot_product = np.dot(emb_det, emb_backend)
    print(f"\n--- Results ---")
    print(f"Cosine Similarity (Detection Path vs Backend Path): {dot_product:.4f}")
    
    if dot_product > 0.99:
        print("SUCCESS: Embeddings are perfectly consistent!")
    elif dot_product > 0.95:
        print("SUCCESS: Embeddings are highly consistent (>0.95)!")
    else:
        print("FAILURE: Embeddings are inconsistent!")

if __name__ == "__main__":
    run_test()
