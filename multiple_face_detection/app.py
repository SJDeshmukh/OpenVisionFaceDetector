import os
import sys
from typing import List, Tuple

import cv2
import gradio as gr
import numpy as np
import pandas as pd
import json
import time
import urllib.request
import urllib.parse

class GFPGANManager:
    def __init__(self, base_dir: str):
        self._base = os.path.abspath(base_dir)
        self._init_paths()
        self._restorer = None
        self._weights_dir = os.path.join(self._base, "models", "gfpgan")
        os.makedirs(self._weights_dir, exist_ok=True)

    def _get_device(self) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() and torch.backends.mps.is_built():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def _init_paths(self):
        tp = os.path.join(self._base, "third_party")
        for sub in ["BasicSR", "facexlib", "Real-ESRGAN", "GFPGAN"]:
            p = os.path.join(tp, sub)
            if os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)
        try:
            import basicsr  # noqa
            import facexlib  # noqa
        except Exception:
            pass

    def _ensure_weights(self) -> str:
        p14 = os.path.join(self._weights_dir, "GFPGANv1.4.pth")
        p13 = os.path.join(self._weights_dir, "GFPGANv1.3.pth")
        if os.path.exists(p14):
            return p14
        if os.path.exists(p13):
            return p13
        urls = [
            ("GFPGANv1.4.pth", "https://github.com/TencentARC/GFPGAN/releases/download/v1.4.0/GFPGANv1.4.pth"),
            ("GFPGANv1.3.pth", "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.3.pth"),
        ]
        import urllib.request
        for fname, url in urls:
            try:
                dst = os.path.join(self._weights_dir, fname)
                urllib.request.urlretrieve(url, dst)
                return dst
            except Exception:
                continue
        return ""

    def load(self, upscale: int = 2):
        if self._restorer is not None:
            return self._restorer
        model_path = self._ensure_weights()
        if not model_path:
            return None
        import torch
        _orig_load = torch.load
        def _patched_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            try:
                dev = self._get_device()
            except Exception:
                dev = "cpu"
            kwargs.setdefault("map_location", dev)
            return _orig_load(*args, **kwargs)
        torch.load = _patched_load
        from gfpgan import GFPGANer
        self._restorer = GFPGANer(model_path=model_path, upscale=upscale, arch="clean", channel_multiplier=2, bg_upsampler=None)
        return self._restorer

    def enhance_crop(self, crop_rgb: np.ndarray, upscale: int = 2, whole: bool = False) -> np.ndarray:
        if crop_rgb is None or crop_rgb.size == 0:
            return crop_rgb
        try:
            restorer = self.load(upscale=upscale)
        except Exception:
            return crop_rgb
        if restorer is None:
            return crop_rgb
        bgr = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR)
        try:
            if whole:
                _, _, restored_img = restorer.enhance(bgr, has_aligned=False, only_center_face=True, paste_back=True)
                if restored_img is not None:
                    return cv2.cvtColor(restored_img, cv2.COLOR_BGR2RGB)
            else:
                _, restored_faces, _ = restorer.enhance(bgr, has_aligned=False, only_center_face=True, paste_back=False)
                if restored_faces and len(restored_faces) > 0:
                    out = cv2.cvtColor(restored_faces[0], cv2.COLOR_BGR2RGB)
                    return out
        except Exception:
            pass
        return crop_rgb

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
        if crop_rgb is None or crop_rgb.size == 0:
            return np.zeros((0,), dtype=np.float32)
        m = self._load()
        if m is None:
            return np.zeros((0,), dtype=np.float32)
        try:
            import torch
            import torchvision.transforms as T
            
            # ArcFace expects strictly 112x112 input
            size = 112
            t = T.Compose([
                T.ToTensor(), 
                T.Resize((size, size)), 
                T.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
            ])
            x = t(crop_rgb).unsqueeze(0).to(self._device)
            with torch.no_grad():
                feat = m(x)[0]
                feat = torch.nn.functional.normalize(feat, dim=0)
            return feat.cpu().numpy().astype(np.float32)
        except Exception as e:
            print(f"Error extracting embedding: {e}")
            return np.zeros((0,), dtype=np.float32)

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


detector = FaceDetector(sdk_dir=os.path.join(os.path.dirname(__file__), "sdk_src"))
gfpgan_manager = GFPGANManager(base_dir=os.path.dirname(__file__))
codeformer_manager = CodeFormerManager()
embedder = FaceEmbedder()
try:
    from facexlib.detection import init_detection_model
    _retina_det = init_detection_model('retinaface_resnet50', half=False)
except Exception:
    _retina_det = None

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
    if _retina_det is not None:
        try:
            rlt = _retina_det.detect_faces(bgr_small, conf_threshold=0.5)
            if rlt is not None and len(rlt) > 0:
                boxes_s = rlt[:, 0:4].astype(np.float32)
                scores = rlt[:, 4].astype(np.float32)
            else:
                boxes_s, scores = np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32)
        except Exception:
            boxes_s, scores = detector.detect(bgr_small)
    else:
        boxes_s, scores = detector.detect(bgr_small)
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
    target_min = 256
    if min(h, w) < target_min:
        scale = target_min / float(min(h, w))
        crop = cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    denoise_h = max(1, int(5 * level))
    crop = cv2.fastNlMeansDenoisingColored(crop, None, denoise_h, denoise_h, 7, 21)
    crop = _clahe_luminance(crop, clip_limit=2.0 + 2.0 * level, tile_grid_size=8)
    crop = _unsharp_mask(crop, strength=0.4 + 0.6 * level, kernel=5, sigma=1.2)
    crop = _gamma(crop, gamma=1.0 - 0.2 * level)
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


def detect_faces(image_input, enhancer: str = "GFPGAN", enhance_level: float = 0.5, gfpgan_upscale: int = 2, codeformer_w: float = 0.5, compute_embeddings: bool = False, crop_mode: str = "Face", portrait_scale: float = 3.0, preclean_whole: bool = False, preclean_level: float = 0.4, det_max_side: int = 1280):
    rgb = _load_image(image_input)
    if rgb is None:
        return None, [], pd.DataFrame([]), pd.DataFrame([])
    rgb_for_det = enhance_whole_image(rgb, level=float(preclean_level)) if preclean_whole else rgb
    bgr = cv2.cvtColor(rgb_for_det, cv2.COLOR_RGB2BGR)
    boxes, scores = _detect_boxes_with_downscale(bgr, max_side=int(det_max_side))

    h, w = rgb.shape[:2]
    anns: List[Tuple[List[int], str]] = []
    crops: List[np.ndarray] = []
    embeds_rows: List[dict] = []

    for i in range(len(boxes)):
        x1, y1, x2, y2 = boxes[i].tolist()
        s = float(scores[i])
        x1, y1, x2, y2 = _clip_box(x1, y1, x2, y2, w, h)
        if crop_mode == "Portrait":
            px1, py1, px2, py2 = _compute_portrait_box(x1, y1, x2, y2, w, h, scale=float(portrait_scale), margin=0.5)
            anns.append(([px1, py1, px2, py2], f"{s:.2f}"))
            crop = rgb_for_det[py1:py2, px1:px2]
        else:
            anns.append(([x1, y1, x2, y2], f"{s:.2f}"))
            crop = rgb_for_det[y1:y2, x1:x2]
        if crop.size > 0:
            if min(crop.shape[0], crop.shape[1]) < 64:
                crops.append(crop)
                if compute_embeddings:
                    emb = embedder.embed(crop)
                    embeds_rows.append({"index": i, "len": int(emb.size), "norm": float(np.linalg.norm(emb)) if emb.size > 0 else 0.0, "first5": list(map(float, emb[:5])) if emb.size >= 5 else []})
                continue
            if enhancer == "None":
                out_crop = crop
            elif enhancer == "OpenCV":
                out_crop = enhance_face_crop(crop, level=enhance_level)
            elif enhancer == "GFPGAN":
                out_crop = gfpgan_manager.enhance_crop(crop, upscale=gfpgan_upscale, whole=(crop_mode == "Portrait"))
            elif enhancer == "GFPGAN+CodeFormer":
                first = gfpgan_manager.enhance_crop(crop, upscale=gfpgan_upscale, whole=(crop_mode == "Portrait"))
                out_crop = codeformer_manager.refine_crop(first, fidelity=codeformer_w, upscale=1)
            else:
                out_crop = crop
            crops.append(out_crop)
            if compute_embeddings:
                emb = embedder.embed(out_crop)
                embeds_rows.append({"index": i, "len": int(emb.size), "norm": float(np.linalg.norm(emb)) if emb.size > 0 else 0.0, "first5": list(map(float, emb[:5])) if emb.size >= 5 else []})

    df = pd.DataFrame(
        [
            {"x1": int(b[0]), "y1": int(b[1]), "x2": int(b[2]), "y2": int(b[3]), "score": float(scores[i])}
            for i, b in enumerate(boxes)
        ]
    )
    df_emb = pd.DataFrame(embeds_rows)

    annotated = (rgb, anns)
    return annotated, crops, df, df_emb

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

if __name__ == "__main__":
    port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    demo.launch(server_name="0.0.0.0", server_port=port, share=True)
