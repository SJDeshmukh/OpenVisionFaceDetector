import pandas as pd
import requests
import io
import os

# Mock data
data = {
    'Student Name': ['Alice Smith', 'Bob Jones', 'Charlie Brown'],
    'Mobile No': ['1234567890', '0987654321', '1122334455'],
    'Division': ['A', 'B', 'A'],
    'Roll Number': ['101', '102', '103'],
    'Department': ['CS', 'IT', 'CS']
}

df = pd.DataFrame(data)

# Save to buffer
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
    df.to_excel(writer, index=False)
buffer.seek(0)

# Target URL (local)
API_URL = "http://localhost:5001/api/bulk-attendance/upload-excel"
# For testing we might need a token, but I'll check if I can run just the logic or mock the request

print("Created mock Excel with columns:", df.columns.tolist())
print("Ready to test backend endpoint.")
