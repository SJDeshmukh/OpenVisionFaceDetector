import os
import sys

"""
Export MobileFaceNet (ArcFace-style) to ONNX for browser inference.

Inputs:
  - WEIGHTS=/abs/path/to/mobilefacenet.pth (required)

Output:
  - web-dashboard/public/models/mobilefacenet_arcface.onnx
"""

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
PUBLIC_MODELS = os.path.join(REPO_ROOT, "web-dashboard", "public", "models")
SDK_SRC = os.path.join(REPO_ROOT, "multiple_face_detection", "sdk_src")

def main():
    weights = os.environ.get("WEIGHTS")
    if not weights or not os.path.exists(weights):
        print("Set WEIGHTS=/abs/path/to/mobilefacenet_weights.pth (file not found)")
        return 1

    sys.path.insert(0, SDK_SRC)
    try:
        import torch
        from face_landmark.MobileFaceNet import MobileFaceNet
    except Exception as e:
        print("Import error:", e)
        return 1

    # Build model
    model = MobileFaceNet(in_channels=3)
    model.eval()

    # Load weights
    try:
        state = torch.load(weights, map_location="cpu")
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        model.load_state_dict(state, strict=False)
    except Exception as e:
        print("Warning: failed to load weights strictly:", e)
        try:
            model.load_state_dict(state, strict=False)
        except Exception as e2:
            print("Load still failed:", e2)
            return 1

    os.makedirs(PUBLIC_MODELS, exist_ok=True)
    out_path = os.path.join(PUBLIC_MODELS, "mobilefacenet_arcface.onnx")

    # Dummy input
    x = torch.randn(1, 3, 112, 112, dtype=torch.float32)

    torch.onnx.export(
        model, x, out_path,
        input_names=["input"],
        output_names=["embedding"],
        opset_version=13,
        dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}}
    )
    print("Exported:", out_path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
