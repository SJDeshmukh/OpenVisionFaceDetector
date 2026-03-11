import os
import urllib.request
import sys

MODELS = {
    # RealESRGAN
    'multiple_face_detection/models/realesrgan/RealESRGAN_x4plus.pth': 
        'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
    
    # GFPGAN
    'multiple_face_detection/models/gfpgan/GFPGANv1.3.pth': 
        'https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.3.pth',

    # 3DDFA-V3 (Face Model Assets)
    'backend/standalone_live_mesh/3DDFA-V3/assets/face_model.npy':
        'https://huggingface.co/Zidu-Wang/3DDFA-V3/resolve/main/assets/face_model.npy',
    'backend/standalone_live_mesh/3DDFA-V3/assets/net_recon.pth':
        'https://huggingface.co/Zidu-Wang/3DDFA-V3/resolve/main/assets/net_recon.pth',
}

def download_file(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
        print(f"--- Skipping {os.path.basename(path)} (already exists) ---")
        return

    print(f"--- Downloading {os.path.basename(path)}... ---")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    try:
        # Use a proper User-Agent to avoid some download blocks
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-agent', 'Mozilla/5.0')]
        urllib.request.install_opener(opener)
        urllib.request.urlretrieve(url, path)
        print(f"--- Success: {path} ---")
    except Exception as e:
        print(f"--- FAILED to download {path}: {e} ---")
        # Don't exit, try others

if __name__ == "__main__":
    print("AI Model Auto-Downloader starting...")
    for path, url in MODELS.items():
        download_file(url, path)
    print("Auto-download process finished.")
