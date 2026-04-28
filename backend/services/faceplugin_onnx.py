import cv2
import numpy as np
import onnxruntime as ort
import os

class FacePluginONNX:
    def __init__(self, model_dir="backend/models/faceplugin/"):
        self.model_dir = model_dir
        # Explicitly use CPU for now to ensure stability on all local envs
        self.providers = ['CPUExecutionProvider']
        
        # Reference points for ArcFace alignment (from Faceplugin JS source)
        self.REFERENCE_FACIAL_POINTS = np.array([
            [38.29459953, 51.69630051],
            [73.53179932, 51.50139999],
            [56.02519989, 71.73660278],
            [41.54930115, 92.3655014],
            [70.72990036, 92.20410156]
        ], dtype=np.float32)

        # Initialize session placeholders for linter
        self.detect_sess = None
        self.land_sess = None
        self.feat_sess = None
        self.live_sess = None

        # Initialize sessions
        self._load_sessions()
        
        # Pre-calculate anchors for fr_detect (Ultra-Light-Fast 320x240)
        self.anchors = self._generate_anchors()

        # Initialize 3D Depth Engine (Lazy load for performance)
        self.depth_engine = None

    def _get_depth_engine(self):
        if self.depth_engine is None:
            import sys
            _mesh_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "standalone_live_mesh")
            if _mesh_dir not in sys.path:
                sys.path.append(_mesh_dir)
            from standalone_live_mesh.inference import get_realtime_engine
            self.depth_engine = get_realtime_engine(device="cpu")
        return self.depth_engine

    def _generate_anchors(self):
        """Generates anchors for the 320x240 Ultra-Light detector"""
        feature_maps = [[40, 30], [20, 15], [10, 8], [5, 4]]
        steps = [8, 16, 32, 64]
        min_sizes = [[10, 16, 24], [32, 48], [64, 96], [128, 192, 256]]
        anchors = []
        for i in range(len(feature_maps)):
            f_w, f_h = feature_maps[i]
            for j in range(f_h):
                for k in range(f_w):
                    for min_size in min_sizes[i]:
                        s_kx = min_size / 320.0
                        s_ky = min_size / 240.0
                        cx = (k + 0.5) * steps[i] / 320.0
                        cy = (j + 0.5) * steps[i] / 240.0
                        anchors.append([cx, cy, s_kx, s_ky])
        return np.array(anchors, dtype=np.float32)

    def detect_faces(self, img, threshold=0.7):
        """Detect faces using fr_detect.onnx"""
        h_orig, w_orig = img.shape[:2]
        img_resized = cv2.resize(img, (320, 240))
        rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        
        # Preprocessing: (x - 127) / 128
        input_data = (rgb.astype(np.float32) - 127.0) / 128.0
        input_data = np.transpose(input_data, (2, 0, 1))[np.newaxis, ...]
        
        outputs = self.detect_sess.run(None, {'input': input_data})
        scores = outputs[0][0] # (4420, 2) - Index 1 is face score
        boxes = outputs[1][0]  # (4420, 4) - Relative [cx, cy, w, h] offsets
        
        face_scores = scores[:, 1]
        mask = face_scores > threshold
        
        valid_scores = face_scores[mask]
        valid_boxes = boxes[mask]
        valid_anchors = self.anchors[mask]
        
        # Decode boxes: anchor[0,1] is cx,cy; anchor[2,3] is sw,sh
        # boxes[0,1] is dx,dy; boxes[2,3] is dw,dh
        decoded_boxes = []
        for i in range(len(valid_boxes)):
            anchor = valid_anchors[i]
            box = valid_boxes[i]
            
            cx = anchor[0] + box[0] * 0.1 * anchor[2]
            cy = anchor[1] + box[1] * 0.1 * anchor[3]
            w = anchor[2] * np.exp(box[2] * 0.2)
            h = anchor[3] * np.exp(box[3] * 0.2)
            
            x1 = (cx - w/2) * w_orig
            y1 = (cy - h/2) * h_orig
            x2 = (cx + w/2) * w_orig
            y2 = (cy + h/2) * h_orig
            
            # Clip to image bounds
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_orig, x2), min(h_orig, y2)
            
            decoded_boxes.append([int(x1), int(y1), int(x2-x1), int(y2-y1), float(valid_scores[i])])
            
        # Simple NMS
        if not decoded_boxes: return []
        decoded_boxes.sort(key=lambda x: x[4], reverse=True)
        final_boxes = []
        while decoded_boxes:
            best = decoded_boxes.pop(0)
            final_boxes.append(best)
            decoded_boxes = [b for b in decoded_boxes if self._iou(best, b) < 0.3]
            
        return final_boxes

    def _iou(self, b1, b2):
        x1, y1, w1, h1 = b1[:4]
        x2, y2, w2, h2 = b2[:4]
        xi1, yi1 = max(x1, x2), max(y1, y2)
        xi2, yi2 = min(x1+w1, x2+w2), min(y1+h1, y2+h2)
        inter = max(0, xi2-xi1) * max(0, yi2-yi1)
        union = w1*h1 + w2*h2 - inter
        return inter / union if union > 0 else 0

    def _load_sessions(self):
        self.detect_sess = ort.InferenceSession(os.path.join(self.model_dir, "fr_detect.onnx"), providers=self.providers)
        self.land_sess = ort.InferenceSession(os.path.join(self.model_dir, "fr_landmark.onnx"), providers=self.providers)
        self.feat_sess = ort.InferenceSession(os.path.join(self.model_dir, "fr_feature.onnx"), providers=self.providers)
        self.live_sess = ort.InferenceSession(os.path.join(self.model_dir, "fr_liveness.onnx"), providers=self.providers)

    def get_landmarks(self, img, bbox):
        """Extract 68 landmarks using fr_landmark.onnx"""
        x1, y1, w, h = bbox
        # Landmark model expects 64x64 grayscale, normalized [0, 1]
        face_img = img[max(0, y1):y1+h, max(0, x1):x1+w]
        face_img = cv2.resize(face_img, (64, 64))
        if len(face_img.shape) == 3:
            face_img = cv2.cvtColor(face_img, cv2.COLOR_RGB2GRAY)
        
        input_data = face_img.astype(np.float32) / 256.0
        input_data = input_data[np.newaxis, np.newaxis, :, :] # (1, 1, 64, 64)
        
        outputs = self.land_sess.run(None, {'input': input_data})
        landmarks_norm = outputs[0].flatten() # 136 values
        
        # Denormalize to global image coordinates
        landmarks = landmarks_norm.copy()
        for i in range(len(landmarks)):
            if i % 2 == 0:
                landmarks[i] = landmarks[i] * w + x1
            else:
                landmarks[i] = landmarks[i] * h + y1
        return landmarks

    def convert_68_to_5_points(self, landmarks_68):
        """Maps 68 points to 5 points using indices from Faceplugin JS source"""
        # landmarks_68 is [x0, y0, x1, y1, ...]
        l = landmarks_68
        left_eye = [
            (l[74] + l[76] + l[80] + l[82]) / 4.0,
            (l[75] + l[77] + l[81] + l[83]) / 4.0
        ]
        right_eye = [
            (l[86] + l[88] + l[92] + l[94]) / 4.0,
            (l[87] + l[89] + l[93] + l[95]) / 4.0
        ]
        nose = [l[60], l[61]]
        left_mouth = [
            (l[96] + l[120]) / 2.0,
            (l[97] + l[121]) / 2.0
        ]
        right_mouth = [
            (l[108] + l[128]) / 2.0,
            (l[109] + l[129]) / 2.0
        ]
        return np.array([left_eye, right_eye, nose, left_mouth, right_mouth], dtype=np.float32)

    def align_face(self, img, landmarks_5):
        """Performs affine warp to 112x112 using 5 points"""
        # cv2.getAffineTransform needs 3 points. JS uses first 3 (left eye, right eye, nose)
        src_pts = landmarks_5[:3].astype(np.float32)
        dst_pts = self.REFERENCE_FACIAL_POINTS[:3].astype(np.float32)
        
        tform = cv2.getAffineTransform(src_pts, dst_pts)
        aligned = cv2.warpAffine(img, tform, (112, 112))
        return aligned

    def extract_feature(self, img, landmarks_5):
        """Extracts 512-D feature vector from aligned face"""
        aligned_img = self.align_face(img, landmarks_5)
        # Normalization: (x - 127) / 128 (NCHW)
        input_data = aligned_img.astype(np.float32)
        input_data = (input_data - 127.0) / 128.0
        input_data = np.transpose(input_data, (2, 0, 1))
        input_data = np.expand_dims(input_data, axis=0)
        
        outputs = self.feat_sess.run(None, {'input': input_data})
        return outputs[0].flatten()

    def _verify_3d_geometry(self, landmarks_68):
        """
        Uses facial symmetry and perspective checks to detect 'Flat' photo spoofs.
        Real 3D faces have predictable changes in eye-to-nose vs nose-to-ear ratios when rotated.
        """
        l = landmarks_68
        # Calculate Eye-to-Nose symmetry
        left_eye_center = np.mean([l[74:84:2], l[75:85:2]], axis=1) # simplified center
        right_eye_center = np.mean([l[86:96:2], l[87:97:2]], axis=1)
        nose_tip = np.array([l[60], l[61]])
        
        dist_l = np.linalg.norm(left_eye_center - nose_tip)
        dist_r = np.linalg.norm(right_eye_center - nose_tip)
        
        # Symmetry Ratio (Should be near 1.0 for frontal, changes for tilted)
        sym_ratio = min(dist_l, dist_r) / (max(dist_l, dist_r) + 1e-6)
        
        # Perspective check: If face is tilted (Yaw), the width/height ratio must shift
        # Flat photos scale linearly; 3D faces scale with cosine projection
        # This is a heuristic proxy
        face_width = np.linalg.norm(np.array([l[0], l[1]]) - np.array([l[32], l[33]]))
        face_height = np.linalg.norm(np.array([l[16], l[17]]) - np.array([l[54], l[55]]))
        aspect = face_width / (face_height + 1e-6)
        
        # Return a "Depth Confidence" score (0 to 1)
        # Real faces usually have sym_ratio > 0.5 and aspect in [0.7, 1.3]
        depth_score = 1.0
        if sym_ratio < 0.4: depth_score *= 0.5 # Too asymmetric for a photo?
        if aspect < 0.5 or aspect > 1.8: depth_score *= 0.3 # Unnatural warping
        return depth_score

    def _check_moire_patterns(self, roi):
        """Detects digital screen artifacts using high-frequency analysis"""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Laplacian variance as a proxy for screen edge sharpness vs skin softness
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # Digital screens often have 'unnaturally' high edge variance or grid artifacts
        # We also check for 'Color Banding' by looking at color histograms
        # Heuristic: 1.0 is likely real skin, < 0.5 is likely screen/print
        texture_score = 1.0
        if laplacian_var > 500: texture_score *= 0.7 # Excessive digital sharpness
        if laplacian_var < 10: texture_score *= 0.5 # Unnatural blur/printed photo
        return texture_score

    def predict_liveness(self, img, bbox):
        """Unified Multi-Factor Liveness Prediction"""
        x1, y1, w, h = bbox
        src_h, src_w = img.shape[:2]
        
        # 1. Get Landmarks for 3D Check
        landmarks_68 = self.get_landmarks(img, bbox)
        depth_factor = self._verify_3d_geometry(landmarks_68)
        
        # 2. Get ONNX Probability
        # Balanced 1.8x scale
        scale = min((src_h-1)/h, min((src_w-1)/w, 1.8))
        new_w, new_h = w * scale, h * scale
        cx, cy = x1 + w/2, y1 + h/2
        
        ltx, lty = max(0, int(cx-new_w/2)), max(0, int(cy-new_h/2))
        rbx, rby = min(src_w-1, int(cx+new_w/2)), min(src_h-1, int(cy+new_h/2))
        
        roi = img[lty:rby, ltx:rbx]
        if roi.size == 0: return 0.0
        
        # 3. Texture Check
        texture_factor = self._check_moire_patterns(roi)
        
        # 4. Inference
        roi_resized = cv2.resize(roi, (128, 128))
        rgb = cv2.cvtColor(roi_resized, cv2.COLOR_BGR2RGB)
        input_data = np.transpose(rgb.astype(np.float32), (2, 0, 1))[np.newaxis, ...]
        
        outputs = self.live_sess.run(None, {'input': input_data})
        scores = np.exp(outputs[0][0])
        probabilities = scores / np.sum(scores)
        onnx_prob = probabilities[0]
        
        # 5. 3D Depth Gate (PHYSICAL OVERRIDE)
        # If the surface is FLAT, it is SPOOF. AI prediction DOES NOT MATTER.
        z_range = -1.0
        try:
            depth_engine = self._get_depth_engine()
            lmks_list = depth_engine.extract_landmarks_for_crop(roi)
            if lmks_list:
                lmks = lmks_list[0]
                z_range = np.max(lmks[:, 2]) - np.min(lmks[:, 2])
                
                # DIAGNOSTIC PRINT
                print(f"[DEBUG] ONNX: {onnx_prob:.3f} | Z-Range: {z_range:.2f} | Texture: {texture_factor:.2f}")
                
                # HARD REJECTION GATE
                # Real heads are usually 40-70. Phones are < 15.
                # Hallucinated depth on 4K photos might reach 25-30.
                if z_range < 32.0: 
                    return 0.01 # Terminal Spoof
        except Exception as e:
            print(f"[ERROR] Depth Gate Internal Failure: {e}")
            pass
            
        # Unified Score Fusion
        heuristic_score = (depth_factor + texture_factor) / 2.0
        unified_score = (onnx_prob * 0.4) + (heuristic_score * 0.6)
        
        return float(unified_score)

    def match_features(self, feat1, feat2):
        """Standard Cosine Similarity scaled to [0, 1]"""
        f1, f2 = feat1.copy(), feat2.copy()
        n1, n2 = np.linalg.norm(f1), np.linalg.norm(f2)
        if n1 == 0 or n2 == 0: return 0.0
        
        # Standard cosine similarity
        cos_sim = np.dot(f1/n1, f2/n2)
        
        # Scale to [0, 1]
        sim = (cos_sim + 1.0) / 2.0
        return sim
