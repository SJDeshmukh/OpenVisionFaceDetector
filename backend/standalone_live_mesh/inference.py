import os
import sys
import numpy as np
from PIL import Image
import cv2

# Add 3DDFA-V3 to path for internal imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.join(BASE_DIR, "3DDFA-V3")
if REPO_DIR not in sys.path:
    sys.path.append(REPO_DIR)

from util.io import back_resize_ldms

_REALTIME_ENGINE = None

class RealTimeEngine:
    def __init__(self, device="cpu"):
        import torch
        print("[inference] Initializing RealTimeEngine...")
        class Args:
            def __init__(self):
                self.device = device
                self.backbone = "resnet50"
                self.useTex = False
                self.extractTex = False
                self.ldm68 = True
                self.ldm106 = False
                self.ldm106_2d = False
                self.ldm134 = False
                self.seg = False
                self.seg_visible = False
        
        from model.recon import face_model
        from mtcnn import MTCNN
        from util.preprocess import load_lm3d
        
        self.args = Args()
        self.recon_model = face_model(self.args)
        self.mtcnn = MTCNN()
        self.lm3d_std = load_lm3d()
        print("[inference] RealTimeEngine ready.")

    def process_frame(self, frame_np: np.ndarray) -> np.ndarray:
        # frame_np: RGB (H, W, 3)
        img_pil = Image.fromarray(frame_np)
        
        # Detection
        facial_landmarks = self.mtcnn.detect_faces(frame_np)
        if not facial_landmarks:
            return frame_np
            
        from util.preprocess import align_img
        H = frame_np.shape[0]
        out_frame = frame_np.copy()
        
        for face in facial_landmarks:
            if face['confidence'] < 0.6: continue
            
            landmarks = []
            keys = ['left_eye', 'right_eye', 'nose', 'mouth_left', 'mouth_right']
            for k in keys:
                pos = face['keypoints'][k]
                landmarks.append([pos[0], pos[1]])
            landmarks = np.array(landmarks).astype(np.float32)
            landmarks[:, -1] = H - 1 - landmarks[:, -1]
            
            trans_params, im, _, _ = align_img(img_pil, landmarks, self.lm3d_std)
        import torch
        im_tensor = torch.tensor(np.array(im)/255., dtype=torch.float32).permute(2, 0, 1).unsqueeze(0)
            
            self.recon_model.input_img = im_tensor.to(self.args.device)
            results = self.recon_model.forward()
            
            if "ldm68" in results:
                lmks = results["ldm68"][0]
                out_frame = self._draw_mesh_on_frame(out_frame, lmks, trans_params)
                
        return out_frame

    def _draw_mesh_on_frame(self, out_frame, lmks, trans_params):
        # We draw directly on out_frame (which is RGB)
        # Green is (0, 255, 0)
        
        # Mapping back using the helper from 3DDFA code
        lmks_to_map = lmks.copy()
        lmks_to_map[:, 1] = 224 - 1 - lmks_to_map[:, 1]
        
        # Ensure types are numpy floats
        tp = np.array(trans_params, dtype=np.float32)
        lmks_mapped = back_resize_ldms(lmks_to_map.astype(np.float32), tp)
        
        # Draw 68 landmarks
        for i, pt in enumerate(lmks_mapped):
            x, y = int(pt[0]), int(pt[1])
            # Draw point
            cv2.circle(out_frame, (x, y), 2, (0, 255, 0), -1)
            
        # Draw basic mesh topology lines
        def draw_poly(indices):
            pts = lmks_mapped[indices].astype(np.int32)
            cv2.polylines(out_frame, [pts], False, (0, 255, 0), 1)

        draw_poly(range(0, 17))
        draw_poly(range(17, 22))
        draw_poly(range(22, 27))
        draw_poly(range(27, 31))
        draw_poly(range(31, 36))
        draw_poly(list(range(36, 42)) + [36])
        draw_poly(list(range(42, 48)) + [42])
        draw_poly(list(range(48, 60)) + [48])
        draw_poly(list(range(60, 68)) + [60])
        
        return out_frame

    def extract_landmarks(self, frame_np: np.ndarray) -> list:
        img_pil = Image.fromarray(frame_np)
        facial_landmarks = self.mtcnn.detect_faces(frame_np)
        if not facial_landmarks:
            return []
            
        from util.preprocess import align_img
        H = frame_np.shape[0]
        results_list = []
        
        for face in facial_landmarks:
            if face['confidence'] < 0.4: continue
            
            landmarks = []
            keys = ['left_eye', 'right_eye', 'nose', 'mouth_left', 'mouth_right']
            for k in keys:
                pos = face['keypoints'][k]
                landmarks.append([pos[0], pos[1]])
            landmarks = np.array(landmarks).astype(np.float32)
            landmarks[:, -1] = H - 1 - landmarks[:, -1]
            
            trans_params, im, _, _ = align_img(img_pil, landmarks, self.lm3d_std)
            import torch
            im_tensor = torch.tensor(np.array(im)/255., dtype=torch.float32).permute(2, 0, 1).unsqueeze(0)
            
            self.recon_model.input_img = im_tensor.to(self.args.device)
            results = self.recon_model.forward()
            
            if "ldm68" in results:
                lmks = results["ldm68"][0]
                lmks_to_map = lmks.copy()
                lmks_to_map[:, 1] = 224 - 1 - lmks_to_map[:, 1]
                tp = np.array(trans_params, dtype=np.float32)
                lmks_mapped = back_resize_ldms(lmks_to_map.astype(np.float32), tp)
                results_list.append(lmks_mapped)
                # If we are in extract_landmarks for a face crop, we usually only want the primary face
                break 
                
        return results_list

def get_realtime_engine():
    global _REALTIME_ENGINE
    if _REALTIME_ENGINE is None:
        _REALTIME_ENGINE = RealTimeEngine(device="cpu")
    return _REALTIME_ENGINE

def process_webcam_frame(frame: np.ndarray) -> np.ndarray:
    try:
        engine = get_realtime_engine()
        return engine.process_frame(frame)
    except Exception as e:
        print(f"[inference] Real-time error: {e}")
        return frame
