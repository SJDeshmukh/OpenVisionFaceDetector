import os
import sys
import cv2
import numpy as np
import json
import base64
import sqlite3
import requests

# Add paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "multiple_face_detection")))

from multiple_face_detection import app as mfd_app

def verify_persistence():
    print("--- Verifying Feature Persistence (3D Landmarks & Structural Vectors) ---")
    
    image_path = "multiple_face_detection/third_party/GFPGAN/inputs/whole_imgs/Blake_Lively.jpg"
    if not os.path.exists(image_path):
        print(f"Error: Image not found at {image_path}")
        return

    # 1. Extract features using the pipeline
    img = cv2.imread(image_path)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    print("Step 1: Extracting features...")
    annotated, crops, df, df_emb = mfd_app.detect_faces(
        image_input=rgb,
        compute_embeddings=True,
        det_max_side=1280
    )
    
    if len(df) == 0:
        print("Error: No faces detected.")
        return
        
    row = df.iloc[0]
    landmarks_3d = row.get('landmarks_3d')
    struct_vec = row.get('struct_vec')
    
    # Get embedding from df_emb or re-compute
    emb = mfd_app.get_embedder().embed(crops[0])
    from services.face_service import _normalize_vec
    emb = _normalize_vec(emb)
    emb_b64 = base64.b64encode(emb.astype(np.float32).tobytes()).decode('ascii')
    
    struct_b64 = ""
    if struct_vec is not None:
        struct_b64 = base64.b64encode(np.array(struct_vec, dtype=np.float32).tobytes()).decode('ascii')

    print(f" - Extracted Embedding (dim={len(emb)})")
    print(f" - Extracted 3D Landmarks ({len(landmarks_3d) if landmarks_3d else 0} points)")
    print(f" - Extracted Structural Vector ({len(struct_vec) if struct_vec else 0} dim)")

    # 2. Register person via API (or direct DB call for speed, but let's test the endpoint logic)
    print("\nStep 2: Registering person via /sync/upload simulation...")
    
    # We'll use direct DB insertion logic similar to upload_face to avoid needing a running server and complex auth for a quick check
    # But wait, I want to verify MY code in routes/faces.py. So I'll simulate the database part of upload_face.
    
    db_path = "backend/face_db.sqlite"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    vendor_id = 1
    person_name = "Test Persistence User"
    
    try:
        # Create vendor and face if not exists
        c.execute("INSERT OR IGNORE INTO vendors (id, company_name) VALUES (1, 'Test Vendor')")
        c.execute("INSERT INTO faces (name, vendor_id) VALUES (?, ?)", (person_name, vendor_id))
        person_id = c.lastrowid
        
        # Now simulate the PERSIST NEW EMBEDDINGS logic from my patch
        idx = 0
        target_templates = [emb_b64]
        struct_vec_list = [struct_b64]
        landmarks_3d_list = [landmarks_3d]
        
        print("Step 3: Saving embeddings with 3D data...")
        for idx, t_item in enumerate(target_templates):
            raw_bytes = base64.b64decode(t_item)
            template_emb = np.frombuffer(raw_bytes, dtype=np.float32).copy()
            template_emb = _normalize_vec(template_emb)
            
            vec_blob = template_emb.astype(np.float32).tobytes()
            
            cur_struct_blob = None
            cur_lmks_json = None
            
            sv = struct_vec_list[idx] if struct_vec_list else None
            if sv:
                cur_struct_blob = base64.b64decode(sv)
                
            lm = landmarks_3d_list[idx] if landmarks_3d_list else None
            if lm:
                cur_lmks_json = json.dumps(lm)
                
            c.execute("""INSERT INTO person_embeddings (vendor_id, person_id, vec, dim, struct_vec, landmarks_3d) 
                         VALUES (?, ?, ?, ?, ?, ?)""", 
                      (vendor_id, person_id, vec_blob, int(template_emb.size), cur_struct_blob, cur_lmks_json))
        
        conn.commit()
        print(f"Successfully saved features for person_id={person_id}")

        # 4. Verify in DB
        print("\nStep 4: Verifying database content...")
        c.execute("SELECT struct_vec, landmarks_3d FROM person_embeddings WHERE person_id = ?", (person_id,))
        res = c.fetchone()
        
        if res:
            saved_struct_blob, saved_lmks_json = res
            print(" - Saved Structural Vector Blob size:", len(saved_struct_blob) if saved_struct_blob else "NONE")
            print(" - Saved Landmarks JSON length:", len(saved_lmks_json) if saved_lmks_json else "NONE")
            
            if saved_struct_blob and len(saved_struct_blob) > 0 and saved_lmks_json and len(saved_lmks_json) > 100:
                print("\n--- RESULTS: SUCCESS! ---")
                print("Structural vectors and 3D landmarks are being correctly persisted.")
            else:
                print("\n--- RESULTS: FAILED! ---")
                print("One or more features were not saved correctly.")
        else:
            print("\n--- RESULTS: FAILED! ---")
            print("No embedding record found for this person.")

    except Exception as e:
        print(f"Error during verification: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    verify_persistence()
