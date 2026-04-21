import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

import cv2
try:
    import gradio as gr  # optional; not required in production
except Exception:
    gr = None
import numpy as np

import json
import time
import urllib.request
import urllib.parse
import base64

def is_bulk_attendance_allowed() -> bool:
    """Checks if ANY active vendor has bulk_image_attendance enabled."""
    try:
        # Use existing backend utils if possible
        # We need to find the project root to import backend modules
        root = os.path.dirname(_BASE_DIR)
        if root not in sys.path:
            sys.path.append(root)
        
        from backend.utils import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        # Check if ANY vendor has the feature in subscriptions
        c.execute("SELECT features FROM subscriptions")
        rows = c.fetchall()
        conn.close()
        
        for row in rows:
            try:
                features = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                if 'bulk_image_attendance' in features:
                    return True
            except:
                continue
    except Exception as e:
        # If DB fails or not initialized, assume False to save resources
        print(f"[MFD] Feature check failed: {e}", flush=True)
        return False
    return False

def _extract_structural_vector(lmks):
    if lmks is None or len(lmks) != 68:
        return np.array([], dtype=np.float32)
    left_eye_center = np.mean(lmks[36:42], axis=0)
    right_eye_center = np.mean(lmks[42:48], axis=0)
    interocular_dist = np.linalg.norm(left_eye_center - right_eye_center)
    if interocular_dist < 1e-5: return np.array([], dtype=np.float32)
    
    nose = lmks[33]
    vec = []
    for i in range(68):
        if i == 33: continue 
        d = np.linalg.norm(lmks[i] - nose) / interocular_dist
        vec.append(d)
        
    v = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm > 1e-5:
        v = v / norm
    return v

_mesh_engine = None
def get_realtime_engine():
    global _mesh_engine
    try:
        from backend.utils import LOW_RAM_MODE
        if LOW_RAM_MODE:
            print("[3D_ENGINE] Bypassing 3D engine in LOW_RAM_MODE to save memory.", flush=True)
            return None
    except Exception: pass
    
    if not is_bulk_attendance_allowed():
        print("[3D_ENGINE] Bulk attendance feature not enabled for any vendor. Skipping model load.", flush=True)
        return None
    if _mesh_engine is not None:
        return _mesh_engine
    
    # Try to find standalone_live_mesh
    mesh_dir = os.path.join(os.path.dirname(_BASE_DIR), "backend", "standalone_live_mesh")
    if not os.path.isdir(mesh_dir):
        # Maybe it's in the current dir?
        mesh_dir = os.path.join(_BASE_DIR, "standalone_live_mesh")
        
    if os.path.isdir(mesh_dir):
        if mesh_dir not in sys.path:
            sys.path.append(mesh_dir)
        try:
            from standalone_live_mesh.inference import get_realtime_engine as _get
            _mesh_engine = _get()
            return _mesh_engine
        except Exception as e:
            print(f"[3D_ENGINE] Error loading mesh engine: {e}", flush=True)
    return None

def init_third_party_paths(base_dir: str):
    tp = os.path.join(base_dir, "third_party")
    # Priority paths for libraries - DISABLED to favor pip installed versions
    # subs = ["BasicSR", "facexlib", "Real-ESRGAN", "GFPGAN"]
    # for sub in subs:
    #     p = os.path.join(tp, sub)
    #     if os.path.isdir(p) and p not in sys.path:
    #         sys.path.insert(0, p)
    
    # Try to verify imports early
    try:
        import basicsr
        import facexlib
    except Exception:
        pass

# Initialize immediately (LIGHTWEIGHT ONLY)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# init_third_party_paths(_BASE_DIR) # DEFERRED to save memory

# PATCH: RealESRGAN missing version fix (DEFERRED)

class GFPGANManager:
    def __init__(self, base_dir: str):
        self._base = os.path.abspath(base_dir)
        self._restorer = None
        self._weights_dir = os.path.join(self._base, "models", "gfpgan")
        self._last_used = 0
        os.makedirs(self._weights_dir, exist_ok=True)

    def _get_device(self) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def _ensure_weights(self) -> str:
        # Check v1.4 first, then v1.3
        # Ensure file exists and is reasonably large (> 10MB)
        p14 = os.path.join(self._weights_dir, "GFPGANv1.4.pth")
        p13 = os.path.join(self._weights_dir, "GFPGANv1.3.pth")
        
        if os.path.exists(p14) and os.path.getsize(p14) > 10 * 1024 * 1024:
            return p14
        if os.path.exists(p13) and os.path.getsize(p13) > 10 * 1024 * 1024:
            return p13
            
        urls = [
            ("GFPGANv1.4.pth", "https://github.com/TencentARC/GFPGAN/releases/download/v1.4.0/GFPGANv1.4.pth"),
            ("GFPGANv1.3.pth", "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.3.pth"),
        ]
        import urllib.request
        for fname, url in urls:
            try:
                dst = os.path.join(self._weights_dir, fname)
                print(f"[GFPGAN] Downloading {fname}...", flush=True)
                urllib.request.urlretrieve(url, dst)
                if os.path.exists(dst) and os.path.getsize(dst) > 10 * 1024 * 1024:
                    return dst
            except Exception as e:
                print(f"[GFPGAN] Download failed for {fname}: {e}", flush=True)
                continue
        return ""

    def load(self, upscale: int = 2):
        if not is_bulk_attendance_allowed():
            print("[GFPGAN] Bulk attendance feature not enabled for any vendor. Skipping model load.", flush=True)
            return None
        init_third_party_paths(_BASE_DIR)
        self._last_used = time.time()
        # Reload if scale factor changed
        if self._restorer is not None:
            if getattr(self._restorer, 'upscale', 2) == upscale:
                return self._restorer
            else:
                print(f"[GFPGAN] Reloading restorer with new upscale factor {upscale}...", flush=True)
                self._restorer = None

        model_path = self._ensure_weights()
        if not model_path:
            return None
        import torch
        # Robust weight loading
        try:
            dev = self._get_device()
            # Try to load without patching first
            from gfpgan import GFPGANer
            self._restorer = GFPGANer(model_path=model_path, upscale=upscale, arch="clean", channel_multiplier=2, bg_upsampler=None, device=dev)
        except Exception as e:
            print(f"[GFPGAN] Direct load failed, trying patched load: {e}", flush=True)
            _orig_load = torch.load
            def _patched_load(*args, **kwargs):
                kwargs["weights_only"] = False # Force false
                kwargs.setdefault("map_location", self._get_device())
                return _orig_load(*args, **kwargs)
            torch.load = _patched_load
            try:
                from gfpgan import GFPGANer
                self._restorer = GFPGANer(model_path=model_path, upscale=upscale, arch="clean", channel_multiplier=2, bg_upsampler=None)
            except Exception as e2:
                print(f"[GFPGAN] Patched load also failed: {e2}", flush=True)
                self._restorer = None
            finally:
                torch.load = _orig_load
        
        if self._restorer:
            self._restorer.upscale = upscale
            print(f"[GFPGAN] Loaded model: {model_path} on {self._get_device()} with upscale={upscale}", flush=True)
        return self._restorer

    def enhance_crop(self, crop_rgb: np.ndarray, upscale: int = 2, whole: bool = False, fidelity: float = 0.4, landmarks: np.ndarray = None) -> np.ndarray:
        if crop_rgb is None or crop_rgb.size == 0:
            return crop_rgb
        
        # Dual-Stage Strategy: If crop is low-res, use RealESRGAN first to provide a cleaner "pixel-hint"
        processed_input = crop_rgb
        h_c, w_c = crop_rgb.shape[:2]
        if min(h_c, w_c) < 128:
            try:
                # Use global RealESRGAN if available
                from .app import get_realesrgan_manager
                re_mgr = get_realesrgan_manager()
                if re_mgr:
                    # Upscale at least to 256 for GFPGAN to see better features
                    processed_input = re_mgr.upscale(crop_rgb, scale=2)
                    print(f"[GFPGAN] Pre-upscaled small crop ({w_c}x{h_c}) with RealESRGAN.", flush=True)
            except Exception:
                pass

        try:
            restorer = self.load(upscale=upscale)
        except Exception:
            return crop_rgb
        if restorer is None:
            return crop_rgb
        
        bgr = cv2.cvtColor(processed_input, cv2.COLOR_RGB2BGR)
        try:
            # We ALWAYS use paste_back=True now for spatial alignment
            _, _, restored_img = restorer.enhance(bgr, has_aligned=False, only_center_face=True, paste_back=True)
            
            if restored_img is not None:
                out_rgb = cv2.cvtColor(restored_img, cv2.COLOR_BGR2RGB)
            else:
                out_rgb = processed_input

            # Final Blending with Fidelity and Optional Landmark-Guided Masking
            # This ensures the AI doesn't "hallucinate" a new head shape/jawline
            if fidelity < 1.0:
                # Ensure sizes match before blending
                if out_rgb.shape != crop_rgb.shape:
                    orig_upscaled = cv2.resize(crop_rgb, (out_rgb.shape[1], out_rgb.shape[0]), interpolation=cv2.INTER_LANCZOS4)
                else:
                    orig_upscaled = crop_rgb
                
                # Masking logic
                mask = None
                if landmarks is not None and landmarks.size > 0:
                    try:
                        # Create a convex hull mask from landmarks to protect the jawline/edges
                        # We use the landmarks to find the "inner face" area
                        mask = np.zeros(out_rgb.shape[:2], dtype=np.float32)
                        
                        # Use landmarks (3D) projected to 2D
                        pts = landmarks[:, :2].astype(np.int32)
                        
                        # Scale points if out_rgb was resized
                        h_orig, w_orig = crop_rgb.shape[:2]
                        h_new, w_new = out_rgb.shape[:2]
                        if h_orig != h_new or w_orig != w_new:
                            pts[:, 0] = pts[:, 0] * w_new / w_orig
                            pts[:, 1] = pts[:, 1] * h_new / h_orig
                            
                        cv2.fillConvexPoly(mask, pts, 1.0)
                        # Expand the mask slightly to include hair/edges
                        kernel_size = max(3, int(min(h_new, w_new) // 15)) | 1
                        mask = cv2.dilate(mask, np.ones((kernel_size, kernel_size), np.uint8), iterations=2)
                        # Blur the mask more aggressively for a smoother, more natural transition
                        mask = cv2.GaussianBlur(mask, (31, 31), 15)
                        # Expand dimensions for broadcasting
                        mask = mask[:, :, np.newaxis]
                    except Exception as e:
                        print(f"[GFPGAN] Mask generation error: {e}", flush=True)
                        mask = None

                if mask is not None:
                    # Blend: Result = (Fidelity-Based Blend within Mask) + (Original outside Mask)
                    # This sharpens features (eyes/nose/mouth) but keeps original skin/jawline
                    blend = out_rgb.astype(np.float32) * fidelity + orig_upscaled.astype(np.float32) * (1.0 - fidelity)
                    out_rgb = (blend * mask + orig_upscaled.astype(np.float32) * (1.0 - mask)).astype(np.uint8)
                else:
                    # Standard global blend
                    out_rgb = cv2.addWeighted(out_rgb, fidelity, orig_upscaled, 1.0 - fidelity, 0)
            
            return out_rgb

        except Exception as e:
            print(f"[GFPGAN] Enhance error: {e}", flush=True)
            pass
        return crop_rgb

class RealESRGANManager:
    def __init__(self, base_dir: str):
        self._base = os.path.abspath(base_dir)
        self._weights_dir = os.path.join(self._base, "models", "realesrgan")
        os.makedirs(self._weights_dir, exist_ok=True)
        self._upsampler = None
        self._last_used = 0

    def _ensure_weights(self) -> str:
        dst = os.path.join(self._weights_dir, "RealESRGAN_x2plus.pth")
        if os.path.exists(dst) and os.path.getsize(dst) > 5 * 1024 * 1024:
            return dst
        url = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
        try:
            import urllib.request
            print(f"[RealESRGAN] Downloading RealESRGAN_x2plus.pth...", flush=True)
            urllib.request.urlretrieve(url, dst)
            if os.path.exists(dst) and os.path.getsize(dst) > 5 * 1024 * 1024:
                return dst
        except Exception as e:
            print(f"[RealESRGAN] Download failed: {e}", flush=True)
            return ""
        return ""

    def load(self, upscale: int = 2):
        if not is_bulk_attendance_allowed():
            print("[RealESRGAN] Bulk attendance feature not enabled for any vendor. Skipping model load.", flush=True)
            return None
        init_third_party_paths(_BASE_DIR)
        # PATCH: RealESRGAN missing version fix
        try:
            import realesrgan
            if not hasattr(realesrgan, '__version__'):
                realesrgan.__version__ = '0.2.5.0'
        except Exception:
            pass
        if self._upsampler is not None:
            return self._upsampler
        model_path = self._ensure_weights()
        if not model_path: return None
        try:
            import torch
            _orig_load = torch.load
            # RealESRGAN architecture fixes
            def _patched_load(*args, **kwargs):
                kwargs["weights_only"] = False
                kwargs.setdefault("map_location", "cpu")
                return _orig_load(*args, **kwargs)
            torch.load = _patched_load
            
            try:
                from realesrgan import RealESRGANer
                from basicsr.archs.rrdbnet_arch import RRDBNet
                device = "cuda" if torch.cuda.is_available() else ("mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu")
                # x2plus model uses RRDBNet with 23 blocks
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2)
                tile_val = int(os.environ.get("REAL_ESRGAN_TILE", "800"))
                tile_pad_val = int(os.environ.get("REAL_ESRGAN_TILE_PAD", "10"))
                self._upsampler = RealESRGANer(
                    scale=2,
                    model_path=model_path,
                    model=model,
                    tile=tile_val,
                    tile_pad=tile_pad_val,
                    pre_pad=0,
                    half=False,
                    device=device
                )
                print(f"[RealESRGAN] Loaded model: {model_path} on {device} (tile={tile_val})", flush=True)
            finally:
                torch.load = _orig_load
            return self._upsampler
        except Exception as e:
            print(f"[RealESRGAN] Load error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return None

    def upscale(self, rgb: np.ndarray, scale: int = 2) -> np.ndarray:
        if rgb is None or rgb.size == 0: return rgb
        self._last_used = time.time()
        try:
            if scale <= 1: return rgb
            upsampler = self.load()
            if upsampler is None:
                print("[RealESRGAN] Upsampler not available, returning original.", flush=True)
                return rgb
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            # Clip scale to what's reasonable (model is x2, but RealESRGANer can do outscale)
            out, _ = upsampler.enhance(bgr, outscale=scale)
            return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        except Exception as e:
            print(f"[RealESRGAN] Enhance error: {e}", flush=True)
            return rgb

_realesrgan_manager = None
def get_realesrgan_manager():
    global _realesrgan_manager
    from utils import LOW_RAM_MODE
    if LOW_RAM_MODE: _check_and_unload_models()
    if _realesrgan_manager is None:
        _realesrgan_manager = RealESRGANManager(base_dir=os.path.dirname(__file__))
    return _realesrgan_manager

class CodeFormerManager:
    def __init__(self):
        self._available = None
        self._model = None

    def _check_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import codeformer
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def refine_crop(self, crop_rgb: np.ndarray, fidelity: float = 0.5, upscale: int = 1) -> np.ndarray:
        if crop_rgb is None or crop_rgb.size == 0:
            return crop_rgb
        if not self._check_available():
            return crop_rgb
        try:
            from PIL import Image
            from codeformer.app import inference_app
            pil = Image.fromarray(crop_rgb)
            out = inference_app(
                image=pil,
                background_enhance=True,
                face_upsample=True,
                upscale=max(1, int(upscale)),
                codeformer_fidelity=float(fidelity),
            )
            if out is None:
                return crop_rgb
            if hasattr(out, "convert"):
                out = np.array(out.convert("RGB"))
            elif isinstance(out, np.ndarray):
                if out.ndim == 3 and out.shape[2] == 3:
                    pass
                else:
                    return crop_rgb
            else:
                return crop_rgb
            return out
        except Exception:
            return crop_rgb

class FaceEmbedder:
    def __init__(self):
        self._model = None
        self._available = None
        self._mode = "arcface"
        self._device = "cpu"
        self._last_used = 0

    def _check_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import torch  # noqa
            from facexlib.recognition import arcface_arch  # noqa
            from facexlib.utils import load_file_from_url  # noqa
            self._available = True
        except Exception as e:
            print(f"FaceEmbedder failed to load facexlib reqs: {e}")
            self._available = False
        return self._available

    def _load(self):
        if not is_bulk_attendance_allowed():
            print("[FaceEmbedder] Bulk attendance feature not enabled for any vendor. Skipping model load.", flush=True)
            return None
        init_third_party_paths(_BASE_DIR)
        if self._model is not None:
            return self._model
        if not self._check_available():
            return None
        try:
            import torch
            if torch.cuda.is_available():
                self._device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available() and torch.backends.mps.is_built():
                self._device = "mps"
            else:
                self._device = "cpu"
        except Exception:
            self._device = "cpu"
            
        import torch
        from facexlib.recognition.arcface_arch import Backbone
        from facexlib.utils import load_file_from_url
        try:
            m = Backbone(num_layers=50, drop_ratio=0.6, mode='ir_se')
            url = 'https://github.com/xinntao/facexlib/releases/download/v0.1.0/recognition_arcface_ir_se50.pth'
            model_path = load_file_from_url(url=url, model_dir='facexlib/weights', progress=True, file_name=None, save_dir=None)
            
            # Use weights_only=False to bypass PyTorch 2.0+ warnings on older weights
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                state = torch.load(model_path, map_location=self._device, weights_only=False)
                
            m.load_state_dict(state, strict=True)
            m = m.to(self._device).eval()
            self._model = m
            print(f"ArcFace model loaded on {self._device}")
        except Exception as e:
            print(f"Error loading ArcFace model weights: {e}")
            self._model = None
            
        return self._model

    def embed(self, crop_rgb: np.ndarray) -> np.ndarray:
        result = self.embed_batch([crop_rgb])
        return result[0] if result else np.zeros((0,), dtype=np.float32)

    def embed_batch(self, crops: list) -> list:
        """Run all face crops through ArcFace in a single forward pass."""
        if not crops:
            return []
        self._last_used = time.time()
        m = self._load()
        if m is None:
            return [np.zeros((0,), dtype=np.float32)] * len(crops)
        try:
            import torch
            import torchvision.transforms as T
            t = T.Compose([
                T.ToTensor(),
                T.Resize((112, 112)),
                T.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
            ])
            tensors, valid_idx = [], []
            for i, crop in enumerate(crops):
                if crop is not None and crop.size > 0:
                    tensors.append(t(crop))
                    valid_idx.append(i)
            if not tensors:
                return [np.zeros((0,), dtype=np.float32)] * len(crops)
            batch = torch.stack(tensors).to(self._device)
            with torch.no_grad():
                feats = m(batch)
                feats = torch.nn.functional.normalize(feats, dim=1)
            feats_np = feats.cpu().numpy().astype(np.float32)
            results = [np.zeros((0,), dtype=np.float32)] * len(crops)
            for out_i, orig_i in enumerate(valid_idx):
                results[orig_i] = feats_np[out_i]
            return results
        except Exception as e:
            print(f"[EMBEDDER] embed_batch error: {e}", flush=True)
            return [np.zeros((0,), dtype=np.float32)] * len(crops)

class FaceDetector:
    def __init__(self, sdk_dir: str):
        self._sdk_dir = os.path.abspath(sdk_dir)
        self._predictor = None
        self._detect_module = None
        self._load_detector()

    def _load_detector(self):
        cwd = os.getcwd()
        try:
            os.chdir(self._sdk_dir)
            if self._sdk_dir not in sys.path:
                sys.path.insert(0, self._sdk_dir)
            from face_detect import detect_imgs as detect_module
            self._detect_module = detect_module
        finally:
            os.chdir(cwd)

    def detect(self, bgr_image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        cwd = os.getcwd()
        try:
            os.chdir(self._sdk_dir)
            boxes, probs = self._detect_module.get_face_boundingbox(bgr_image)
            if boxes is None:
                return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32)
            boxes_np = boxes.detach().cpu().numpy() if hasattr(boxes, "detach") else np.asarray(boxes)
            probs_np = probs.detach().cpu().numpy() if hasattr(probs, "detach") else np.asarray(probs)
            return boxes_np, probs_np
        finally:
            os.chdir(cwd)


# Global instances for lazy loading
_detector = None
_gfpgan_manager = None
_codeformer_manager = None
_embedder = None
_retina_det = None

# Per-model locks — GPU models (GFPGAN, ArcFace, RealESRGAN) are not re-entrant;
# the 3D engine is CPU-only so it gets its own lock and can overlap with GPU work.
_gfpgan_lock = threading.Lock()
_embedder_lock = threading.Lock()
_realesrgan_lock = threading.Lock()
_3d_engine_lock = threading.Lock()

# Active detection counter for GC gating
_active_detections = 0
_active_detections_lock = threading.Lock()

# Unload TTL (seconds of idle before models are released)
_UNLOAD_TTL = 300

# Background GC thread — checks every 60 s, only unloads when fully idle
_gc_thread_started = False

def _start_model_gc_thread():
    global _gc_thread_started
    if _gc_thread_started:
        return
    _gc_thread_started = True

    def _gc_loop():
        while True:
            time.sleep(60)
            with _active_detections_lock:
                idle = (_active_detections == 0)
            if idle:
                _check_and_unload_models()

    t = threading.Thread(target=_gc_loop, daemon=True, name="mfd-model-gc")
    t.start()

def _check_and_unload_models():
    """Release memory by unloading models that haven't been used recently."""
    global _gfpgan_manager, _embedder, _realesrgan_manager, _mesh_engine
    now = time.time()
    
    # Check GFPGAN
    if _gfpgan_manager and _gfpgan_manager._restorer and (now - _gfpgan_manager._last_used > _UNLOAD_TTL):
        _gfpgan_manager._restorer = None
        print("[MEM] Unloaded GFPGAN model to free RAM")
        
    # Check Embedder
    if _embedder and _embedder._model and (now - _embedder._last_used > _UNLOAD_TTL):
        _embedder._model = None
        print("[MEM] Unloaded FaceEmbedder model to free RAM")

    # Check RealESRGAN
    if _realesrgan_manager and _realesrgan_manager._upsampler and (now - _realesrgan_manager._last_used > _UNLOAD_TTL):
        _realesrgan_manager._upsampler = None
        print("[MEM] Unloaded RealESRGAN model to free RAM")
        
    # Periodic GC if anything was unloaded
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

def get_detector():
    global _detector
    if _detector is None:
        _detector = FaceDetector(sdk_dir=os.path.join(os.path.dirname(__file__), "sdk_src"))
    return _detector

def get_gfpgan_manager():
    global _gfpgan_manager
    from utils import LOW_RAM_MODE
    if LOW_RAM_MODE: _check_and_unload_models()
    if _gfpgan_manager is None:
        _gfpgan_manager = GFPGANManager(base_dir=os.path.dirname(__file__))
    return _gfpgan_manager

def get_codeformer_manager():
    global _codeformer_manager
    if _codeformer_manager is None:
        _codeformer_manager = CodeFormerManager()
    return _codeformer_manager

def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = FaceEmbedder()
    return _embedder

def get_retina_det():
    global _retina_det
    if _retina_det is None:
        try:
            from facexlib.detection import init_detection_model
            _retina_det = init_detection_model('retinaface_resnet50', half=False)
        except Exception:
            _retina_det = False # Use False as a "tried but failed" marker
    return _retina_det if _retina_det is not False else None

def _load_image(image_input):
    if isinstance(image_input, np.ndarray):
        return image_input
    if isinstance(image_input, str):
        try:
            with open(image_input, "rb") as f:
                data = f.read()
            arr = np.frombuffer(data, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is None:
                return None
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        except Exception:
            return None
    return None

def _detect_boxes_with_downscale(bgr_image: np.ndarray, max_side: int = 1280):
    h, w = bgr_image.shape[:2]
    scale = 1.0
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
        bgr_small = cv2.resize(bgr_image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        bgr_small = bgr_image
    rd = get_retina_det()
    if rd is not None:
        try:
            rlt = rd.detect_faces(bgr_small, conf_threshold=0.5)
            if rlt is not None and len(rlt) > 0:
                boxes_s = rlt[:, 0:4].astype(np.float32)
                scores = rlt[:, 4].astype(np.float32)
            else:
                boxes_s, scores = np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32)
        except Exception:
            boxes_s, scores = get_detector().detect(bgr_small)
    else:
        boxes_s, scores = get_detector().detect(bgr_small)
    if scale != 1.0 and len(boxes_s) > 0:
        boxes_s = (boxes_s.astype(np.float32) / scale).astype(np.float32)
    return boxes_s, scores

def _compute_portrait_box(x1, y1, x2, y2, w, h, scale: float = 3.0, margin: float = 0.5):
    face_w = max(1, x2 - x1)
    face_h = max(1, y2 - y1)
    cx = (x1 + x2) // 2
    top = max(0, int(y1 - margin * face_h))
    bottom = int(y1 + scale * face_h)
    left = max(0, int(cx - (0.5 + margin) * face_w))
    right = int(cx + (0.5 + margin) * face_w)
    x1n, y1n, x2n, y2n = _clip_box(left, top, right, bottom, w, h)
    return x1n, y1n, x2n, y2n

def _compute_centered_box(x1, y1, x2, y2, w, h, scale: float = 1.2):
    """Computes a balanced square-ish box centered on the face box."""
    face_w = max(1, x2 - x1)
    face_h = max(1, y2 - y1)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    side = int(max(face_w, face_h) * scale)
    
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    right = left + side
    bottom = top + side
    
    x1n, y1n, x2n, y2n = _clip_box(left, top, right, bottom, w, h)
    return x1n, y1n, x2n, y2n

def _clip_box(x1, y1, x2, y2, w, h):
    return int(max(0, x1)), int(max(0, y1)), int(min(w - 1, x2)), int(min(h - 1, y2))


def _unsharp_mask(img: np.ndarray, strength: float = 0.6, kernel: int = 5, sigma: float = 1.5):
    blur = cv2.GaussianBlur(img, (kernel | 1, kernel | 1), sigma)
    return cv2.addWeighted(img, 1 + strength, blur, -strength, 0)


def _clahe_luminance(img: np.ndarray, clip_limit: float = 2.0, tile_grid_size: int = 8):
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_grid_size, tile_grid_size))
    l2 = clahe.apply(l)
    lab2 = cv2.merge([l2, a, b])
    return cv2.cvtColor(lab2, cv2.COLOR_LAB2RGB)


def _gamma(img: np.ndarray, gamma: float = 1.0):
    if gamma <= 0:
        return img
    inv = 1.0 / gamma
    table = np.array([(i / 255.0) ** inv * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(img, table)


def enhance_face_crop(crop: np.ndarray, level: float = 0.5) -> np.ndarray:
    if crop.size == 0:
        return crop
    h, w = crop.shape[:2]
    # Simple high-quality resize if needed, but the primary enhancement happens via GFPGAN
    target_min = 256
    if min(h, w) < target_min:
        scale = target_min / float(min(h, w))
        crop = cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    
    # Minimal clean enhancement
    crop = _clahe_luminance(crop, clip_limit=1.5, tile_grid_size=8)
    crop = _unsharp_mask(crop, strength=0.4 + 0.2 * level, kernel=3, sigma=1.0)
    return crop

def enhance_whole_image(rgb: np.ndarray, level: float = 0.4) -> np.ndarray:
    if rgb is None or rgb.size == 0:
        return rgb
    denoise_h = max(1, int(5 * level))
    out = cv2.fastNlMeansDenoisingColored(rgb, None, denoise_h, denoise_h, 7, 21)
    out = _clahe_luminance(out, clip_limit=2.0 + 2.0 * level, tile_grid_size=8)
    out = _unsharp_mask(out, strength=0.3 + 0.5 * level, kernel=5, sigma=1.2)
    out = _gamma(out, gamma=1.0 - 0.15 * level)
    return out


def restore_from_reference(target_crop: np.ndarray, ref_image: np.ndarray, fidelity: float = 1.0) -> np.ndarray:
    if target_crop is None or ref_image is None or target_crop.size == 0 or ref_image.size == 0:
        return target_crop
    engine = get_realtime_engine()
    if engine is None:
        return target_crop
    t_lmks_list = engine.extract_landmarks(target_crop)
    r_lmks_list = engine.extract_landmarks(ref_image)
    if not t_lmks_list or not r_lmks_list:
        return target_crop
    t_pts = t_lmks_list[0][:, :2].astype(np.float32)
    r_pts = r_lmks_list[0][:, :2].astype(np.float32)
    matrix, inliers = cv2.estimateAffinePartial2D(r_pts, t_pts)
    if matrix is None:
        return target_crop
    th, tw = target_crop.shape[:2]
    warped_ref = cv2.warpAffine(ref_image, matrix, (tw, th), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros((th, tw), dtype=np.float32)
    hull = cv2.convexHull(t_pts.astype(np.int32))
    cv2.fillConvexPoly(mask, hull, 1.0)
    k_size = max(31, int(min(th, tw) // 8)) | 1
    mask = cv2.GaussianBlur(mask, (k_size, k_size), k_size // 2)
    mask = np.clip(mask * 1.5, 0, 1)
    mask = mask[:, :, np.newaxis]
    combined = warped_ref.astype(np.float32) * mask + target_crop.astype(np.float32) * (1.0 - mask)
    combined = np.clip(combined, 0, 255).astype(np.uint8)
    gfp_mgr = get_gfpgan_manager()
    if gfp_mgr:
        restored = gfp_mgr.enhance_crop(combined, fidelity=max(0.7, fidelity), landmarks=t_lmks_list[0])
        return restored
    return combined

# ArcFace IR-SE50 standard 5-point template for 112×112 output.
# Source: InsightFace / facexlib training convention.
_ARCFACE_TEMPLATE = np.array([
    [38.2946, 51.6963],  # left eye centre
    [73.5318, 51.5014],  # right eye centre
    [56.0252, 71.7366],  # nose tip
    [41.5493, 92.3655],  # left mouth corner
    [70.7299, 92.2041],  # right mouth corner
], dtype=np.float32)

def _align_to_arcface_112(crop_rgb: np.ndarray, lmks_68) -> np.ndarray:
    """Affine-warp a face crop to the ArcFace 112×112 canonical template.

    Uses 5 key points derived from 68-point 3DDFA landmarks (local crop coords).
    Falls back to plain resize if alignment fails.
    """
    if crop_rgb is None or crop_rgb.size == 0:
        return crop_rgb
    try:
        pts = np.asarray(lmks_68, dtype=np.float32)
        if pts.ndim != 2 or pts.shape[0] < 68:
            raise ValueError("need 68-pt landmarks")
        xy = pts[:, :2]  # drop z
        src = np.array([
            xy[36:42].mean(axis=0),   # left eye
            xy[42:48].mean(axis=0),   # right eye
            xy[30],                   # nose tip
            xy[48],                   # left mouth corner
            xy[54],                   # right mouth corner
        ], dtype=np.float32)
        M, _ = cv2.estimateAffinePartial2D(src, _ARCFACE_TEMPLATE, method=cv2.LMEDS)
        if M is None:
            raise ValueError("affine estimation failed")
        return cv2.warpAffine(crop_rgb, M, (112, 112),
                              flags=cv2.INTER_LANCZOS4,
                              borderMode=cv2.BORDER_REFLECT)
    except Exception:
        return cv2.resize(crop_rgb, (112, 112), interpolation=cv2.INTER_LANCZOS4)


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = FaceEmbedder()
    return _embedder

def _extract_3d_for_face(engine, rgb, bx1, by1, bx2, by2, img_w, img_h):
    """Extract 3D landmarks for one face crop (CPU-only, no lock needed). Returns (lmks_global, struct_vec, lmks_local_emb)."""
    try:
        c3x1, c3y1, c3x2, c3y2 = _compute_portrait_box(bx1, by1, bx2, by2, img_w, img_h, scale=1.5, margin=0.2)
        face_for_3d = rgb[c3y1:c3y2, c3x1:c3x2]
        if face_for_3d.size == 0:
            return [], [], None
        # 3DDFA is CPU-only and stateless per-call — no lock needed
        lmks_list = engine.extract_landmarks(face_for_3d)
        if not lmks_list:
            return [], [], None
        lmks_item = lmks_list[0]
        lmks_global = lmks_item.copy()
        lmks_global[:, 0] += c3x1
        lmks_global[:, 1] += c3y1
        sv = _extract_structural_vector(lmks_item)
        f1x1, f1y1, f1x2, f1y2 = _compute_centered_box(bx1, by1, bx2, by2, img_w, img_h, scale=1.2)
        lmks_local_emb = lmks_global.copy()
        lmks_local_emb[:, 0] -= f1x1
        lmks_local_emb[:, 1] -= f1y1
        return lmks_global.tolist(), (sv.tolist() if sv.size > 0 else []), lmks_local_emb
    except Exception:
        return [], [], None



def detect_faces(image_input, enhancer: str = "GFPGAN", enhance_level: float = 0.5, gfpgan_upscale: int = 2, codeformer_w: float = 0.5, compute_embeddings: bool = False, crop_mode: str = "Face", portrait_scale: float = 3.0, preclean_whole: bool = False, preclean_level: float = 0.4, det_max_side: int = 1280):
    import pandas as pd
    import gc

    print(f"[MFD] detect_faces called: enhancer={enhancer!r} compute_embeddings={compute_embeddings} det_max_side={det_max_side}", flush=True)

    _start_model_gc_thread()

    global _active_detections
    with _active_detections_lock:
        _active_detections += 1

    try:
        rgb = _load_image(image_input)
        if rgb is None:
            return None, [], pd.DataFrame([]), pd.DataFrame([])
        rgb_for_det = enhance_whole_image(rgb, level=float(preclean_level)) if preclean_whole else rgb
        bgr = cv2.cvtColor(rgb_for_det, cv2.COLOR_RGB2BGR)

        try:
            from backend.utils import LOW_RAM_MODE
            if LOW_RAM_MODE and det_max_side > 640:
                det_max_side = 640
        except Exception:
            pass

        boxes, scores = _detect_boxes_with_downscale(bgr, max_side=int(det_max_side))

        h, w = rgb.shape[:2]
        engine = get_realtime_engine()
        n = len(boxes)

        # ── Phase 1: Build per-face crops + annots (cheap, serial) ─────────
        anns: List[Tuple[List[int], str]] = []
        face_meta = []   # (i, bx1,by1,bx2,by2, display_crop, emb_crop)
        landmarks_3d_list = [[] for _ in range(n)]
        struct_vec_list   = [[] for _ in range(n)]
        embeds_rows: List[dict] = []

        for i in range(n):
            bx1, by1, bx2, by2 = [int(v) for v in boxes[i].tolist()]
            x1, y1, x2, y2 = _clip_box(bx1, by1, bx2, by2, w, h)
            s = float(scores[i])
            if crop_mode == "Portrait":
                px1, py1, px2, py2 = _compute_portrait_box(x1, y1, x2, y2, w, h, scale=float(portrait_scale), margin=0.5)
                ann_box = [px1, py1, px2, py2]
                display_crop = rgb_for_det[py1:py2, px1:px2]
            else:
                ann_box = [x1, y1, x2, y2]
                display_crop = rgb_for_det[y1:y2, x1:x2]
            anns.append((ann_box, f"{s:.2f}"))
            # Tight 1.2× crop for ArcFace (consistent across all resolutions)
            f1x1, f1y1, f1x2, f1y2 = _compute_centered_box(bx1, by1, bx2, by2, w, h, scale=1.2)
            emb_crop = rgb[f1y1:f1y2, f1x1:f1x2]
            face_meta.append((i, bx1, by1, bx2, by2, display_crop, emb_crop))

        # ── Phase 2a: 3D landmarks for ALL faces in parallel (CPU-only) ─────
        if engine is not None and n > 0:
            with ThreadPoolExecutor(max_workers=min(n, os.cpu_count() or 4)) as pool3d:
                fut_map = {
                    pool3d.submit(_extract_3d_for_face, engine, rgb, bx1, by1, bx2, by2, w, h): i
                    for i, bx1, by1, bx2, by2, _, _ in face_meta
                }
                lmks_local_emb_map = {}
                for fut in as_completed(fut_map):
                    i = fut_map[fut]
                    try:
                        lg, sv, lmks_local = fut.result()
                        landmarks_3d_list[i] = lg
                        struct_vec_list[i]   = sv
                        lmks_local_emb_map[i] = lmks_local
                    except Exception:
                        lmks_local_emb_map[i] = None
        else:
            lmks_local_emb_map = {i: None for i in range(n)}

        # ── Phase 2b: Display crop enhancement (GFPGAN/RealESRGAN, if not fast) ─
        crops_out = []
        for i, bx1, by1, bx2, by2, display_crop, emb_crop in face_meta:
            if display_crop.size == 0:
                crops_out.append(display_crop)
                continue
            temp = display_crop
            if enhancer != "None" and min(display_crop.shape[:2]) > 0:
                short_side = min(display_crop.shape[:2])
                if short_side < 256:
                    calc_scale = min(2, max(int(gfpgan_upscale), max(2, int(np.ceil(256 / short_side)))))
                    with _realesrgan_lock:
                        temp = get_realesrgan_manager().upscale(display_crop, scale=calc_scale)
                elif gfpgan_upscale > 1:
                    with _realesrgan_lock:
                        temp = get_realesrgan_manager().upscale(display_crop, scale=int(gfpgan_upscale))
            if enhancer == "None":
                out_crop = temp
            elif enhancer == "OpenCV":
                out_crop = enhance_face_crop(temp, level=enhance_level)
            elif enhancer in ("GFPGAN", "GFPGAN+CodeFormer"):
                with _gfpgan_lock:
                    out_crop = get_gfpgan_manager().enhance_crop(temp, upscale=1, whole=(crop_mode == "Portrait"), fidelity=0.4)
                if enhancer == "GFPGAN+CodeFormer":
                    out_crop = get_codeformer_manager().refine_crop(out_crop, fidelity=codeformer_w, upscale=1)
            else:
                out_crop = temp
            crops_out.append(out_crop)

        crops = [c for c in crops_out if c is not None and c.size > 0]

        # ── Phase 3: Batch ArcFace — ONE forward pass for all N faces ────────
        if compute_embeddings and n > 0:
            emb_crops = []
            for i, bx1, by1, bx2, by2, _, emb_crop in face_meta:
                lmks_local = lmks_local_emb_map.get(i)
                if enhancer != "None" and emb_crop.size > 0:
                    with _gfpgan_lock:
                        emb_crop = get_gfpgan_manager().enhance_crop(
                            emb_crop, upscale=1, whole=False, fidelity=0.4, landmarks=lmks_local
                        )
                # Align to ArcFace canonical 112×112 template using 3DDFA landmarks.
                # This corrects for head tilt and pose variation before embedding.
                if lmks_local is not None:
                    emb_crop = _align_to_arcface_112(emb_crop, lmks_local)
                emb_crops.append(emb_crop)

            with _embedder_lock:
                all_embs = get_embedder().embed_batch(emb_crops)

            for i, emb in enumerate(all_embs):
                if emb is not None and emb.size > 0:
                    embeds_rows.append({
                        "index": i,
                        "len": int(emb.size),
                        "norm": float(np.linalg.norm(emb)),
                        "first5": list(map(float, emb[:5])) if emb.size >= 5 else []
                    })

        df = pd.DataFrame([
            {"x1": int(b[0]), "y1": int(b[1]), "x2": int(b[2]), "y2": int(b[3]), "score": float(scores[i])}
            for i, b in enumerate(boxes)
        ])
        df_emb = pd.DataFrame(embeds_rows)

        if len(landmarks_3d_list) == len(df):
            df['landmarks_3d'] = landmarks_3d_list
            df['struct_vec'] = struct_vec_list

        annotated = (rgb, anns)

        gc.collect()

    finally:
        with _active_detections_lock:
            _active_detections -= 1
    
    return annotated, crops, df, df_emb

# Start GC thread as soon as this module is imported
_start_model_gc_thread()

def detect_faces_ui6(image_input, enhancer, enhance_level, gfpgan_upscale, codeformer_w, compute_embeddings):
    return detect_faces(
        image_input=image_input,
        enhancer=enhancer,
        enhance_level=enhance_level,
        gfpgan_upscale=gfpgan_upscale,
        codeformer_w=codeformer_w,
        compute_embeddings=compute_embeddings,
        crop_mode="Portrait",
        portrait_scale=3.0,
        preclean_whole=False,
        preclean_level=0.4,
    )

if __name__ == "__main__" and os.getenv("ENABLE_GRADIO_UI", "0").strip().lower() in ("1", "true", "yes") and gr is not None:
    with gr.Blocks(title="Face Detection (Faceplugin SDK)") as demo:
        gr.Markdown("Face detection: upload an image to get detected face cards and boxes. Choose enhancement.")
        with gr.Row():
            with gr.Column(scale=1):
                inp = gr.Image(label="Upload Image", type="filepath")
                enhancer = gr.Radio(choices=["GFPGAN", "GFPGAN+CodeFormer", "OpenCV", "None"], value="GFPGAN", label="Enhancer")
                enhance_lvl = gr.Slider(label="OpenCV strength", minimum=0.0, maximum=1.0, value=0.5, step=0.05)
                gfp_up = gr.Slider(label="GFPGAN upscale", minimum=1, maximum=4, value=2, step=1)
                cf_w = gr.Slider(label="CodeFormer fidelity (w)", minimum=0.0, maximum=1.0, value=0.5, step=0.05)
                do_embed = gr.Checkbox(label="Compute embeddings", value=False)
                crop_mode = gr.Radio(choices=["Face", "Portrait"], value="Face", label="Crop mode")
                portrait_scale = gr.Slider(label="Portrait scale (face heights)", minimum=2.0, maximum=4.0, value=3.0, step=0.1)
                preclean = gr.Checkbox(label="Pre-clean whole image", value=False)
                preclean_lvl = gr.Slider(label="Pre-clean strength", minimum=0.0, maximum=1.0, value=0.4, step=0.05)
                run_btn = gr.Button("Detect Faces", variant="primary")
            with gr.Column(scale=1):
                annotated = gr.AnnotatedImage(label="Detected Faces")
        with gr.Row():
            gallery = gr.Gallery(label="Face Cards", allow_preview=True, columns=4, height=300)
        with gr.Row():
            table = gr.Dataframe(headers=["x1", "y1", "x2", "y2", "score"], interactive=False)
        with gr.Row():
            embeds = gr.Dataframe(headers=["index", "len", "norm", "first5"], interactive=False)

        run_btn.click(fn=lambda a,b,c,d,e,f,g,h: detect_faces(a,b,c,d,e,f,crop_mode="Portrait",portrait_scale=3.0,preclean_whole=g,preclean_level=h),
                      inputs=[inp, enhancer, enhance_lvl, gfp_up, cf_w, do_embed, preclean, preclean_lvl],
                      outputs=[annotated, gallery, table, embeds])
        inp.change(fn=lambda a,b,c,d,e,f,g,h: detect_faces(a,b,c,d,e,f,crop_mode="Portrait",portrait_scale=3.0,preclean_whole=g,preclean_level=h),
                   inputs=[inp, enhancer, enhance_lvl, gfp_up, cf_w, do_embed, preclean, preclean_lvl],
                   outputs=[annotated, gallery, table, embeds])

        gr.Markdown("Chunks: browse recent analysis snapshots from the backend")
        API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:5001")

        def _http_json(url: str):
            try:
                with urllib.request.urlopen(url, timeout=5) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception:
                return {}

        def list_chunks():
            data = _http_json(f"{API_BASE}/chunks")
            items = data.get("items", [])
            rows = []
            choices = []
            labels = []
            for it in items:
                cid = it.get("id", "")
                ts = float(it.get("ts", 0.0))
                tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                names = ", ".join(sorted(set(it.get("names", []))))
                rows.append([cid, tstr, int(it.get("count", 0)), names])
                choices.append(cid)
                labels.append(f"{tstr} ({cid[:6]})")
            df = pd.DataFrame(rows, columns=["id", "time", "count", "names"])
            return df, gr.Dropdown(choices=choices, value=(choices[0] if choices else None), label="Chunk ID"), gr.Dropdown.update(choices=choices)

        def load_chunk(cid: str):
            if not cid:
                return [], None
            q = urllib.parse.urlencode({"id": cid})
            data = _http_json(f"{API_BASE}/chunk_images?{q}")
            return data.get("items", []), data.get("image", None)

        with gr.Tab("Registered Users"):
            with gr.Row():
                load_users_btn = gr.Button("Load Users")
                user_select = gr.Dropdown(choices=[], label="User")
            with gr.Row():
                refresh_user_chunks_btn = gr.Button("Refresh User Chunks")
            with gr.Row():
                user_chunks_table = gr.Dataframe(headers=["id", "time", "count", "names"], interactive=False)
            with gr.Row():
                user_chunk_select = gr.Dropdown(choices=[], label="Chunk ID")
            with gr.Row():
                user_chunk_image = gr.Image(label="Annotated Image")
            with gr.Row():
                user_chunk_gallery = gr.Gallery(label="Chunk Photos", columns=4, height=300)

            def list_users():
                data = _http_json(f"{API_BASE}/labels")
                items = data.get("items", [])
                names = [it.get("name", "") for it in items if it.get("name", "")]
                return gr.Dropdown.update(choices=names, value=(names[0] if names else None))

            def list_user_chunks(username: str):
                data = _http_json(f"{API_BASE}/chunks")
                items = data.get("items", [])
                filt = []
                choices = []
                for it in items:
                    if username in it.get("names", []):
                        cid = it.get("id", "")
                        ts = float(it.get("ts", 0.0))
                        tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                        names = ", ".join(sorted(set(it.get("names", []))))
                        filt.append([cid, tstr, int(it.get("count", 0)), names])
                        choices.append(cid)
                df = pd.DataFrame(filt, columns=["id", "time", "count", "names"])
                return df, gr.Dropdown.update(choices=choices, value=(choices[0] if choices else None))

            def load_user_chunk(username: str, cid: str):
                if not cid:
                    return [], None
                q = urllib.parse.urlencode({"id": cid})
                data = _http_json(f"{API_BASE}/chunk_images?{q}")
                items = data.get("items", [])
                names = data.get("names", [])
                imgs = [img for img, nm in zip(items, names) if nm == username] if items and names else items
                return imgs, data.get("image", None)

            load_users_btn.click(fn=list_users, inputs=[], outputs=[user_select])
            refresh_user_chunks_btn.click(fn=list_user_chunks, inputs=[user_select], outputs=[user_chunks_table, user_chunk_select])
            user_chunk_select.change(fn=lambda u, c: load_user_chunk(u, c), inputs=[user_select, user_chunk_select], outputs=[user_chunk_gallery, user_chunk_image])

    port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    demo.launch(server_name="0.0.0.0", server_port=port, share=True)
