import os
import sys

"""
Export ArcFace (IR_SE50) PyTorch weights to ONNX for browser inference.

Output:
  - web-dashboard/public/models/arcface_ir_se50.onnx

This script attempts to use facexlib's ArcFace backbone and downloads
canonical weights if not present. You can also pass WEIGHTS=/path/to/weights.pth.
"""

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))
PUBLIC_MODELS = os.path.join(REPO_ROOT, "web-dashboard", "public", "models")
os.makedirs(PUBLIC_MODELS, exist_ok=True)

def main():
    weights_path = os.environ.get("WEIGHTS", "").strip()

    try:
        import torch
        from torch import nn
    except Exception as e:
        print("PyTorch not available:", e)
        return 1

    try:
        # Try facexlib ArcFace backbone (try multiple known class names)
        Arc = None
        try:
            from facexlib.recognition.arcface_arch import IR_SE_50 as Arc
        except Exception:
            try:
                from facexlib.recognition.arcface_arch import IR_50 as Arc
            except Exception:
                Arc = None
        if Arc is None:
            # Try insightface-style iresnet50 if available
            try:
                from facexlib.recognition.arcface_arch import iresnet50 as Arc
            except Exception:
                pass
        if Arc is None:
            print("ArcFace backbone class not found in facexlib. Install a compatible facexlib.")
            return 1

        # Some classes expect image size argument, some don't
        try:
            model = Arc([112, 112])
        except Exception:
            model = Arc()
        model.eval()

        if not weights_path:
            try:
                # facexlib provides loader utility
                from facexlib.utils import load_file_from_url
                # Use a common IR-SE50 checkpoint
                url = "https://github.com/xinntao/facexlib/releases/download/arcface/ir_se50.pth"
                weights_path = load_file_from_url(url=url, model_dir=os.path.join(REPO_ROOT, "weights"))
            except Exception as _:
                print("Could not auto-download weights. Set WEIGHTS=/path/to/ir_se50.pth")
                return 1

        ckpt = torch.load(weights_path, map_location="cpu")
        if isinstance(ckpt, dict) and "state_dict" in ckpt:
            ckpt = ckpt["state_dict"]
        try:
            model.load_state_dict(ckpt, strict=False)
        except Exception as e:
            print("State dict load failed (continuing with strict=False):", e)
            try:
                model.load_state_dict(ckpt, strict=False)
            except Exception as e2:
                print("Load still failed:", e2)
                return 1

        dummy = torch.randn(1, 3, 112, 112, dtype=torch.float32)
        onnx_out = os.path.join(PUBLIC_MODELS, "arcface_ir_se50.onnx")
        torch.onnx.export(
            model, dummy, onnx_out,
            input_names=["input"],
            output_names=["embedding"],
            opset_version=13,
            dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}}
        )
        print("Exported:", onnx_out)
        return 0
    except Exception as e:
        print("Export failed:", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
