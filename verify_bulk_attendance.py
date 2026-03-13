import os
import sys
import cv2
import numpy as np
import pandas as pd
import json

# Add backend and multiple_face_detection to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "multiple_face_detection")))

from multiple_face_detection import app as mfd_app

def verify_full_pipeline(image_path):
    print(f"--- Starting E2E Verification for: {image_path} ---")
    
    if not os.path.exists(image_path):
        print(f"Error: Image not found at {image_path}")
        return

    # Load image
    img = cv2.imread(image_path)
    if img is None:
        print("Error: Could not decode image.")
        return
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    print("--- Running detect_faces (Full Pipeline) ---")
    try:
        # We simulate the exact call used in bulk/real-time processing
        annotated, crops, df, df_emb = mfd_app.detect_faces(
            image_input=rgb,
            enhancer="GFPGAN",
            enhance_level=0.5,
            gfpgan_upscale=2,
            codeformer_w=0.5,
            compute_embeddings=True,
            crop_mode="Face",
            portrait_scale=3.0,
            preclean_whole=True,
            preclean_level=0.4,
            det_max_side=1280
        )
        
        print(f"Detection results: Found {len(df)} faces.")
        
        if len(df) > 0:
            for i, row in df.iterrows():
                print(f"\nFace {i}:")
                print(f" - BBox: [{row['x1']}, {row['y1']}, {row['x2']}, {row['y2']}]")
                print(f" - Score: {row['score']:.4f}")
                
                # Check for 3D landmarks
                if 'landmarks_3d' in row and len(row['landmarks_3d']) > 0:
                    print(f" - 3D Landmarks: Extracted {len(row['landmarks_3d'])} points.")
                else:
                    print(" - 3D Landmarks: MISSING!")
                
                # Check for structural vector
                if 'struct_vec' in row and len(row['struct_vec']) > 0:
                    print(f" - Structural Vector: Extracted (dim={len(row['struct_vec'])})")
                else:
                    print(" - Structural Vector: MISSING!")

            # Check embeddings
            if not df_emb.empty:
                print(f"\nEmbeddings: Generated {len(df_emb)} rows.")
                for i, row in df_emb.iterrows():
                    print(f" - Embedding {i}: Norm={row['norm']:.4f}, Dim={row['len']}")
            else:
                print("\nEmbeddings: MISSING!")
                
            print("\n--- PASSED: Basic Pipeline Check ---")
        else:
            print("\n--- FAILED: No faces detected ---")
            
    except Exception as e:
        print(f"\n--- CRITICAL ERROR during pipeline execution: ---")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_img = "multiple_face_detection/third_party/GFPGAN/inputs/whole_imgs/Blake_Lively.jpg"
    verify_full_pipeline(test_img)
