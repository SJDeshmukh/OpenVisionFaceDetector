import cv2
import sys
import os

_mesh_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standalone_live_mesh")
if _mesh_dir not in sys.path:
    sys.path.append(_mesh_dir)

from standalone_live_mesh.inference import get_realtime_engine

engine = get_realtime_engine()
if engine is None:
    print("Engine failed to initialize.")
    sys.exit(1)

img = cv2.imread("standalone_live_mesh/3DDFA-V3/examples/1.jpg")
if img is not None:
    print(f"Testing on 1.jpg")
    try:
        lmks = engine.extract_landmarks(img)
        print(f"lmks length: {len(lmks)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
