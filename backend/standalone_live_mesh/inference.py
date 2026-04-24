import time
import threading
import os
import sys
import numpy as np
from PIL import Image
import cv2

# Serialize concurrent Celery-thread calls: self.recon_model.input_img is shared state
_inference_lock = threading.Lock()

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
                self.backbone = "mbnetv3"
                self.useTex = False
                self.extractTex = False
                self.ldm68 = True
                self.ldm106 = False
                self.ldm106_2d = False
                self.ldm134 = False
                self.seg = False
                self.seg_visible = False
        
        from model.recon import face_model
        from util.preprocess import load_lm3d

        self.args = Args()
        self.recon_model = face_model(self.args)
        self._mtcnn = None  # lazy-loaded on first use to avoid Metal GPU deadlock
        self.lm3d_std = load_lm3d()
        print("[inference] RealTimeEngine ready.", flush=True)

    def _get_mtcnn(self):
        # MTCNN uses TensorFlow Metal, which deadlocks when PyTorch MPS models are already
        # loaded in the same process. Lazy-load with TF forced to CPU to avoid the hang.
        if self._mtcnn is None:
            import tensorflow as tf
            tf.config.set_visible_devices([], 'GPU')
            from mtcnn import MTCNN
            self._mtcnn = MTCNN()
        return self._mtcnn

    def process_frame(self, frame_np: np.ndarray) -> np.ndarray:
        # frame_np: RGB (H, W, 3)
        img_pil = Image.fromarray(frame_np)

        # Detection
        facial_landmarks = self._get_mtcnn().detect_faces(frame_np)
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

    def extract_landmarks_for_crop(self, face_rgb: np.ndarray) -> list:
        """
        Extracts 3D landmarks for a single face crop without re-detecting.
        Used for maximum speed when the face location is already known.
        """
        if face_rgb is None or face_rgb.size == 0:
            return []
            
        try:
            from util.preprocess import align_img
            img_pil = Image.fromarray(face_rgb)
            H, W = face_rgb.shape[:2]
            
            # Since it's a crop of the face, we assume the face is centered.
            # We use dummy 5-point landmarks for alignment (corners + center)
            # as a fallback if MTCNN is skipped.
            # But better: just use a standard alignment for the crop.
            landmarks = np.array([
                [W*0.3, H*0.35], [W*0.7, H*0.35], # eyes
                [W*0.5, H*0.55], # nose
                [W*0.35, H*0.75], [W*0.65, H*0.75] # mouth
            ]).astype(np.float32)
            
            # Match 3DDFA-V3 Coordinate System (Y is inverted internally)
            landmarks_inv = landmarks.copy()
            landmarks_inv[:, -1] = H - 1 - landmarks_inv[:, -1]
            
            trans_params, im, _, _ = align_img(img_pil, landmarks_inv, self.lm3d_std)
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
                return [lmks_mapped]
        except Exception as e:
            print(f"[inference] extract_landmarks_for_crop error: {e}")
            
        return []

    def extract_landmarks_batch(self, face_crops: list, face_keypoints: list = None) -> list:
        """
        Batch processing of 3D landmarks for N faces.
        Preprocessing (PIL/numpy) runs in parallel threads (GIL released by numpy/PIL),
        then a single batched model forward pass executes for all faces at once.
        """
        if not face_crops:
            return []

        from util.preprocess import align_img
        import torch
        from concurrent.futures import ThreadPoolExecutor

        lm3d_std = self.lm3d_std  # captured once for thread closures

        def _preprocess_one(args):
            i, crop = args
            if crop is None or crop.size == 0:
                return None
            try:
                H, W = crop.shape[:2]
                img_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                img_pil = Image.fromarray(img_rgb)
                if face_keypoints is not None and i < len(face_keypoints) and face_keypoints[i] is not None:
                    landmarks = face_keypoints[i].astype(np.float32)
                else:
                    landmarks = np.array([
                        [W * 0.3, H * 0.35], [W * 0.7, H * 0.35],
                        [W * 0.5, H * 0.55],
                        [W * 0.35, H * 0.75], [W * 0.65, H * 0.75]
                    ]).astype(np.float32)
                landmarks_inv = landmarks.copy()
                landmarks_inv[:, -1] = H - 1 - landmarks_inv[:, -1]
                trans_params, im, _, _ = align_img(img_pil, landmarks_inv, lm3d_std)
                s = float(trans_params[2])
                if s > 50.0 or s < 0.01:
                    print(f"[inference] Warning: scale s={s} out of range, skipping face {i}.", flush=True)
                    return None
                t = torch.tensor(np.array(im) / 255., dtype=torch.float32).permute(2, 0, 1)
                return (i, trans_params, t)
            except Exception:
                import traceback
                print(f"[inference] Preprocessing error:\n{traceback.format_exc()}", flush=True)
                return None

        # Parallel preprocessing: PIL decode + align_img release GIL => real CPU overlap
        _t_pp = time.time()
        n_workers = min(len(face_crops), 2)
        with ThreadPoolExecutor(max_workers=n_workers) as _pool:
            prep_results = list(_pool.map(_preprocess_one, enumerate(face_crops)))
        print(f"[TIMING] 3D preprocess: {time.time()-_t_pp:.3f}s for {len(face_crops)} crops (workers={n_workers})", flush=True)

        tensors = []
        metadata = []  # (trans_params, original_crop_index)
        for r in prep_results:
            if r is not None:
                i, trans_params, t = r
                tensors.append(t)
                metadata.append((trans_params, i))

        if not tensors:
            return [[] for _ in range(len(face_crops))]

        # Single batched forward pass — model called once for all faces
        # Lock required: concurrent threads share recon_model.input_img (mutable state)
        _t_fwd = time.time()
        with _inference_lock:
            batch_tensor = torch.stack(tensors).to(self.args.device)
            self.recon_model.input_img = batch_tensor
            results = self.recon_model.forward(render=False)
        print(f"[TIMING] 3D forward pass: {time.time()-_t_fwd:.3f}s for {len(tensors)} tensors", flush=True)

        all_landmarks = [[] for _ in range(len(face_crops))]
        valid_idx = 0

        if "ldm68" in results:
            ldm68_batch = results["ldm68"]  # (B, 68, 3)
            for meta_idx in range(len(metadata)):
                if valid_idx >= len(ldm68_batch):
                    break
                lmks = ldm68_batch[valid_idx]
                if hasattr(lmks, "cpu"):
                    lmks = lmks.cpu().numpy()
                trans_params, crop_i = metadata[meta_idx]
                lmks_to_map = lmks.copy()
                lmks_to_map[:, 1] = 224 - 1 - lmks_to_map[:, 1]
                lmks_mapped = back_resize_ldms(lmks_to_map.astype(np.float32), trans_params)
                all_landmarks[crop_i] = lmks_mapped
                valid_idx += 1

        # Diagnostic: confirm Z-depth is present
        for _lm in all_landmarks:
            if isinstance(_lm, np.ndarray) and _lm.ndim == 2 and _lm.shape[0] > 0:
                if _lm.shape[1] >= 3:
                    print(f"[3DDFA] Landmark 3D detected: shape={_lm.shape}, Z-range=[{_lm[:,2].min():.2f}, {_lm[:,2].max():.2f}]", flush=True)
                else:
                    print(f"[3DDFA] Landmark 2D fallback: shape={_lm.shape}", flush=True)
                break

        return all_landmarks

    def extract_landmarks(self, frame_np: np.ndarray) -> list:
        # Legacy support for full-frame landmark extraction
        # (This still uses detection because it doesn't know where faces are)
        img_pil = Image.fromarray(frame_np)
        facial_landmarks = self._get_mtcnn().detect_faces(frame_np)
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
                break 
                
        return results_list

def get_realtime_engine(device="cpu"):
    global _REALTIME_ENGINE
    if _REALTIME_ENGINE is None:
        _REALTIME_ENGINE = RealTimeEngine(device=device)
    return _REALTIME_ENGINE

def process_webcam_frame(frame: np.ndarray) -> np.ndarray:
    try:
        engine = get_realtime_engine()
        return engine.process_frame(frame)
    except Exception as e:
        print(f"[inference] Real-time error: {e}")
        return frame
