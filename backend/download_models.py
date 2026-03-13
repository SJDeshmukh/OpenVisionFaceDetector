import os
import urllib.request
import sys
from huggingface_hub import hf_hub_download

MODELS = {
    # RealESRGAN (GitHub)
    'multiple_face_detection/models/realesrgan/RealESRGAN_x4plus.pth': 
        'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
    
    # GFPGAN (GitHub)
    'multiple_face_detection/models/gfpgan/GFPGANv1.4.pth': 
        'https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth',
}

# 3DDFA-V3 (HuggingFace)
HF_MODELS = {
    'Zidu-Wang/3DDFA-V3': [
        ('assets/face_model.npy', 'backend/standalone_live_mesh/3DDFA-V3/assets/face_model.npy'),
        ('assets/net_recon.pth', 'backend/standalone_live_mesh/3DDFA-V3/assets/net_recon.pth'),
    ]
}

def download_file(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
        print(f"--- Skipping {os.path.basename(path)} (already exists) ---")
        return

    print(f"--- Downloading {os.path.basename(path)}... ---")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(path, 'wb') as out_file:
            out_file.write(response.read())
        print(f"--- Success: {path} ---")
    except Exception as e:
        print(f"--- FAILED to download {path}: {e} ---")

def download_hf_models():
    for repo_id, files in HF_MODELS.items():
        for filename, local_path in files:
            if os.path.exists(local_path) and os.path.getsize(local_path) > 1024:
                print(f"--- Skipping HF {filename} (already exists) ---")
                continue
            
            print(f"--- Downloading HF {filename} from {repo_id}... ---")
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            try:
                # Use repo_type="dataset" because these are in a dataset repo
                path = hf_hub_download(
                    repo_id=repo_id, 
                    filename=filename, 
                    repo_type="dataset",
                    local_dir=os.path.dirname(local_path), 
                    local_dir_use_symlinks=False
                )
                print(f"--- Success: {local_path} ---")
            except Exception as e:
                print(f"--- FAILED HF download {filename}: {e} ---")

if __name__ == "__main__":
    print("AI Model Auto-Downloader starting...")
    for path, url in MODELS.items():
        download_file(url, path)
    
    download_hf_models()
    print("Auto-download process finished.")
