import os
import sys
import base64
import json
import numpy as np

# Add backend to path
sys.path.insert(0, os.path.join(os.getcwd(), 'backend'))

# Set DB path correctly
os.environ['DB_PATH'] = os.path.join(os.getcwd(), 'backend', 'faces.db')

from services.face_service import _detect_faces_from_bytes

def test_identification(image_path, vendor_id=1):
    print(f"\n[TEST] Testing identification with {image_path}...")
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found at {image_path}")
        return

    with open(image_path, 'rb') as f:
        img_bytes = f.read()
    
    params = {'fast': 'true'}
    try:
        faces, annotated_b64 = _detect_faces_from_bytes(img_bytes, params, vendor_id)
        print(f"\n[TEST] Result: {len(faces)} faces identified.")
        for i, f in enumerate(faces):
            sugg = f.get('suggestions', [])
            score = f.get('score', 0.0)
            print(f"Face {i}: Score={score:.3f}, Suggestions={len(sugg)}")
            if sugg:
                for idx, s in enumerate(sugg[:1]):
                    print(f"  Top Suggestion: {s.get('name')} (Sim: {s.get('similarity', 0.0):.3f})")
    except Exception as e:
        print(f"\n[TEST] Error during identification: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Path to an actual image from the find_by_name results
    # Use one from backend/audit_images/
    test_img = "/Users/hashteelab/Documents/trae_projects/face_detection/backend/audit_images/1773123157555_15a849b7_webcam-1773123157442.jpg"
    
    # Run test
    test_identification(test_img)
