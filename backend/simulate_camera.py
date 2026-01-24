import requests
import time
import base64
import os

# Create a dummy image (a simple colored square)
# Or better, let's use a real image if available, or generate one.
# I'll create a small PPM image and convert to base64 for simplicity, or just use a dummy string if the backend accepts it (backend expects base64).

def create_dummy_image(color_rgb):
    # PPM format: P3 width height maxval r g b ...
    header = "P3 100 100 255 "
    body = " ".join([f"{color_rgb[0]} {color_rgb[1]} {color_rgb[2]}" for _ in range(100*100)])
    ppm_data = (header + body).encode('utf-8')
    return base64.b64encode(ppm_data).decode('utf-8')

# Let's try to use a real base64 image string (a small red dot) for better browser compatibility
# I'll use a valid 1x1 pixel JPEG base64
# Note: In real app, we send full data URL "data:image/jpeg;base64,..."
# The backend passes it through.
# Let's verify what format the frontend expects.
# The frontend code I just fixed handles both cases (with or without prefix).
# But to be safe and match the Android app, let's include the prefix.

RED_DOT_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
BLUE_DOT_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

RED_DOT = "data:image/png;base64," + RED_DOT_BASE64
BLUE_DOT = "data:image/png;base64," + BLUE_DOT_BASE64

print("Starting Camera Stream Simulation...")
print("Press Ctrl+C to stop.")

url = "http://localhost:5001/api/stream/upload"

try:
    while True:
        # Alternate colors to show "liveness"
        timestamp = int(time.time())
        img = RED_DOT if timestamp % 2 == 0 else BLUE_DOT
        
        payload = {"image": img}
        try:
            r = requests.post(url, json=payload)
            if r.status_code == 200:
                print(f"Frame sent! Status: {r.status_code}")
            else:
                print(f"Error: {r.status_code} - {r.text}")
        except Exception as e:
            print(f"Connection Error: {e}")
            
        time.sleep(1) # 1 FPS
except KeyboardInterrupt:
    print("Stream stopped.")
