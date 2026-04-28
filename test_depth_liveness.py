import cv2
import numpy as np
import sys
import os
import torch

# Add mesh engine to path
_mesh_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend/standalone_live_mesh")
if _mesh_dir not in sys.path:
    sys.path.append(_mesh_dir)

from standalone_live_mesh.inference import get_realtime_engine

class DepthLivenessTester:
    def __init__(self):
        print("Initializing 3D Depth Engine (3DDFA-V3)...")
        # Force CPU if no CUDA/MPS to ensure stability during test
        self.engine = get_realtime_engine(device="cpu")
        print("Engine Ready.")

    def run(self):
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Could not open webcam.")
            return

        print("\n--- 3D Depth Liveness Test ---")
        print("Look for 'Z-Range' on the screen.")
        print("Real Head: High Z-Range (e.g. 40-100)")
        print("Phone/Photo: Low Z-Range (e.g. 0-10)")
        print("Press 'q' to quit.")

        while True:
            ret, frame = cap.read()
            if not ret: break

            # Convert BGR to RGB for the engine
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Simple detection fallback (using Haar for test)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            faces = face_cascade.detectMultiScale(gray, 1.1, 5)

            for (x, y, w, h) in faces:
                # Crop face
                face_crop = frame[y:y+h, x:x+w]
                if face_crop.size == 0: continue
                
                # Extract 3D landmarks
                # We need to pass the whole frame or handle the crop
                lmks_list = self.engine.extract_landmarks_for_crop(face_crop)
                
                if lmks_list:
                    lmks = lmks_list[0] # (68, 3)
                    
                    # Calculate Z-Range (The 'Depth' of the face)
                    z_values = lmks[:, 2]
                    z_min, z_max = np.min(z_values), np.max(z_values)
                    z_range = z_max - z_min
                    
                    # Heuristic classification
                    is_3d = z_range > 30 
                    color = (0, 255, 0) if is_3d else (0, 0, 255)
                    label = "3D FACE" if is_3d else "FLAT SPOOF"

                    cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                    cv2.putText(frame, f"{label}", (x, y-40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    cv2.putText(frame, f"Z-Range: {z_range:.2f}", (x, y-15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

                    # Project 3D landmarks for visualization
                    for pt in lmks:
                        px, py = int(x + pt[0]), int(y + pt[1])
                        # Use Z to color the point (Depth Heatmap)
                        rel_z = (pt[2] - z_min) / (z_range + 1e-6)
                        z_color = (0, int(255 * rel_z), int(255 * (1-rel_z)))
                        cv2.circle(frame, (px, py), 1, z_color, -1)

            cv2.imshow('3D Depth Debugger', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    tester = DepthLivenessTester()
    tester.run()
