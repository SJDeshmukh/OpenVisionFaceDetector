import numpy as np
import cv2
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils import get_face_augmentations

def test_augmentation_utility():
    print("Testing expanded get_face_augmentations utility...")
    
    # Create a dummy RGB image (100x100)
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:, :50, 0] = 255 # Left side is Red
    
    augs = get_face_augmentations(img)
    
    # [original, flip, brightness_up, brightness_down, rotate_left, rotate_right]
    if len(augs) != 6:
        print(f"FAILED: Expected 6 augmentations, got {len(augs)}")
        return False
        
    print(f"SUCCESS: Generated {len(augs)} augmentations.")
    
    # Verify basics
    if not np.array_equal(augs[0], img):
        print("FAILED: First augmentation is not the original image")
        return False
        
    if np.array_equal(augs[1], img):
        print("FAILED: Flipped image is identical to original")
        return False
        
    print("SUCCESS: get_face_augmentations works correctly for all 6 versions!")
    return True

if __name__ == "__main__":
    test_augmentation_utility()
