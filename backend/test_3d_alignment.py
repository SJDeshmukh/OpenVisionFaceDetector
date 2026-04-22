
import sys
import os
import cv2
import numpy as np
from PIL import Image

# Add necessary paths
sys.path.append(os.path.join(os.getcwd(), 'standalone_live_mesh'))
sys.path.append(os.path.join(os.getcwd(), 'standalone_live_mesh/3DDFA-V3'))

# Mocking the imports as they would be in the actual app
from util.preprocess import POS, resize_n_crop_img, load_lm3d

def test_alignment():
    print("Testing 3D Alignment Logic...")
    
    # Load standard 3D landmarks
    try:
        lm3d_std = load_lm3d()
        print(f"lm3d_std shape: {lm3d_std.shape}")
    except Exception as e:
        print(f"Error loading lm3d_std: {e}")
        return

    # Create dummy landmarks (e.g. for a 224x224 crop)
    # Standard 5-points: [Left Eye, Right Eye, Nose, Left Mouth, Right Mouth]
    W, H = 224, 224
    landmarks = np.array([
        [W*0.3, H*0.3], [W*0.7, H*0.3],
        [W*0.5, H*0.5],
        [W*0.35, H*0.7], [W*0.65, H*0.7]
    ], dtype=np.float32)
    
    print(f"Input landmarks:\n{landmarks}")

    # 1. Test WITHOUT y-inversion (common in many aligners)
    t1, s1 = POS(landmarks.transpose(), lm3d_std.transpose())
    RESCALE_FACTOR = 1000.0/224.0
    sf1 = RESCALE_FACTOR / s1
    print(f"\n[Scenario 1: No Inversion]")
    print(f"s from POS: {s1}")
    print(f"final scale s: {sf1}")

    # 2. Test WITH y-inversion (what we had in inference.py)
    landmarks_inv = landmarks.copy()
    landmarks_inv[:, 1] = H - 1 - landmarks_inv[:, 1]
    t2, s2 = POS(landmarks_inv.transpose(), lm3d_std.transpose())
    sf2 = RESCALE_FACTOR / s2
    print(f"\n[Scenario 2: With Y-Inversion]")
    print(f"s from POS: {s2}")
    print(f"final scale s: {sf2}")

    # 3. Check what happens if points are very close (the 'Crazy scale' case)
    landmarks_bad = np.array([[100, 100]] * 5, dtype=np.float32)
    t3, s3 = POS(landmarks_bad.transpose(), lm3d_std.transpose())
    sf3 = RESCALE_FACTOR / s3 if s3 != 0 else float('inf')
    print(f"\n[Scenario 3: Corrupt Points (Same Location)]")
    print(f"s from POS: {s3}")
    print(f"final scale s: {sf3}")

if __name__ == "__main__":
    test_alignment()
