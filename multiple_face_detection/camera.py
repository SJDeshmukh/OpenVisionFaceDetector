import cv2
import os
from datetime import datetime

# Create folder to save images
save_folder = "captured_images"
os.makedirs(save_folder, exist_ok=True)

# Open laptop camera (0 = default camera)
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("❌ Cannot open camera")
    exit()

print("📸 Press 's' to save image")
print("❌ Press 'q' to quit")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame")
        break

    cv2.imshow("Laptop Camera", frame)

    key = cv2.waitKey(1) & 0xFF

    # Save image when 's' is pressed
    if key == ord('s'):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(save_folder, f"image_{timestamp}.jpg")
        cv2.imwrite(filename, frame)
        print(f"✅ Image saved: {filename}")

    # Quit when 'q' is pressed
    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()