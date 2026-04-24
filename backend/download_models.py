import os
import urllib.request
from huggingface_hub import hf_hub_download

# Resolve all paths relative to this script's location so the downloader
# works correctly regardless of which directory it is invoked from.
_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))  # .../backend/
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)                 # .../face_detection/

def _p(*parts):
    return os.path.join(_PROJECT_ROOT, *parts)

# ---------------------------------------------------------------------------
# Direct-download models (GitHub releases)
# ---------------------------------------------------------------------------
MODELS = {
    _p("multiple_face_detection/models/realesrgan/RealESRGAN_x4plus.pth"):
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    _p("multiple_face_detection/models/realesrgan/RealESRGAN_x2plus.pth"):
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    _p("multiple_face_detection/models/gfpgan/GFPGANv1.4.pth"):
        "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
}

# ---------------------------------------------------------------------------
# HuggingFace dataset files
# key   = repo_id
# value = list of (filename_in_repo, expected_local_abs_path)
#
# IMPORTANT: local_dir must be the PARENT of the first path component in
# filename so that hf_hub_download recreates the correct tree.
# e.g. filename="assets/face_model.npy", local_dir=".../3DDFA-V3/"
#      → downloads to  ".../3DDFA-V3/assets/face_model.npy"  ✓
# ---------------------------------------------------------------------------
_3DDFA_DIR = _p("backend/standalone_live_mesh/3DDFA-V3")

HF_MODELS = {
    "Zidu-Wang/3DDFA-V3": {
        "local_dir": _3DDFA_DIR,
        "files": [
            ("assets/face_model.npy", _p("backend/standalone_live_mesh/3DDFA-V3/assets/face_model.npy")),
            ("assets/net_recon.pth",  _p("backend/standalone_live_mesh/3DDFA-V3/assets/net_recon.pth")),
        ],
    },
}


def download_file(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
        print(f"--- Skipping {os.path.basename(path)} (already exists) ---")
        return
    print(f"--- Downloading {os.path.basename(path)}... ---")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response, open(path, "wb") as out_file:
            out_file.write(response.read())
        print(f"--- Success: {path} ---")
    except Exception as e:
        print(f"--- FAILED to download {os.path.basename(path)}: {e} ---")


def download_hf_models():
    for repo_id, cfg in HF_MODELS.items():
        local_dir = cfg["local_dir"]
        for filename, expected_path in cfg["files"]:
            if os.path.exists(expected_path) and os.path.getsize(expected_path) > 1024:
                print(f"--- Skipping HF {filename} (already exists) ---")
                continue
            print(f"--- Downloading HF {filename} from {repo_id}... ---")
            os.makedirs(os.path.dirname(expected_path), exist_ok=True)
            try:
                hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    repo_type="dataset",
                    local_dir=local_dir,
                    local_dir_use_symlinks=False,
                )
                print(f"--- Success: {expected_path} ---")
            except Exception as e:
                print(f"--- FAILED HF download {filename}: {e} ---")


def run_full_download():
    print("AI Model Auto-Downloader starting...")
    for path, url in MODELS.items():
        download_file(url, path)
    download_hf_models()
    print("Auto-download process finished.")


if __name__ == "__main__":
    run_full_download()
