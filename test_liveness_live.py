import cv2
import numpy as np
from backend.services.faceplugin_onnx import FacePluginONNX
import os

class LiveLivenessTester:
    def __init__(self):
        print("Initializing CONSENSUS Liveness Engine...")
        self.engine = FacePluginONNX()
        self.history = [] # Stores raw scores
        self.window_size = 20 # 20 frames Consensus (approx 0.6s to 1s)
        self.liveness_state = "SPOOF"

    def run(self):
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Could not open webcam.")
            return

        print("\n--- Live Liveness Test (CONSENSUS MODE) ---")
        print("Logic: 75% Majority Rule over 20 frames.")
        print("Press 'q' to quit.")

        while True:
            ret, frame = cap.read()
            if not ret: break

            # 1. Detect faces using ONNX
            faces = self.engine.detect_faces(frame, threshold=0.6)

            if not faces:
                # self.history = [] # Reset on lack of face for fresh start
                pass
            else:
                for face in faces:
                    x, y, w, h, det_score = face
                    bbox = (x, y, w, h)
                    
                    # 2. Get Score
                    score = self.engine.predict_liveness(frame, bbox)
                    self.history.append(score)
                    if len(self.history) > self.window_size:
                        self.history.pop(0)

                    # 3. CONSENSUS LOGIC (Majority Voting)
                    # Count how many frames are "Real-like" (>0.6)
                    real_votes = sum(1 for s in self.history if s > 0.6)
                    real_ratio = real_votes / len(self.history)
                    
                    # Decision Rule: 
                    # A face is ONLY REAL if more than 75% of recent frames are REAL.
                    # This completely skips the "Small time real" glitches on phones.
                    if real_ratio > 0.75:
                        self.liveness_state = "REAL"
                    elif real_ratio < 0.2: # High confidence spoof
                        self.liveness_state = "SPOOF"
                    
                    color = (0, 255, 0) if self.liveness_state == "REAL" else (0, 0, 255)
                    cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                    
                    # UI Overlay
                    cv2.putText(frame, f"{self.liveness_state}", (x, y-50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    cv2.putText(frame, f"Real Ratio: {real_ratio:.2f}", (x, y-30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    cv2.putText(frame, f"Consensus ({len(self.history)}/{self.window_size})", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

            cv2.imshow('Consensus Liveness Debugger', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    tester = LiveLivenessTester()
    tester.run()
