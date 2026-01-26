# Central Configuration for Face Detection System

import os
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

# Backend Server Settings
DOMAIN_NAME = os.environ.get("DOMAIN_NAME", "localhost")
PORT = int(os.environ.get("PORT", 5001))
PROTOCOL = os.environ.get("PROTOCOL", "http")

# Production URLs (Generic)
# Priority:
# 1. Explicit Environment Variables (BACKEND_URL, FRONTEND_URL)
# 2. Render Environment Variables (RENDER_EXTERNAL_URL) - kept as fallback
# 3. Localhost Defaults

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
BACKEND_URL = os.environ.get("BACKEND_URL") or RENDER_URL or f"{PROTOCOL}://{DOMAIN_NAME}:{PORT}"
FRONTEND_URL = os.environ.get("FRONTEND_URL") or "http://localhost:5173"

# Active Base URL
BASE_URL = BACKEND_URL

# Database
DB_NAME = "faces.db"

# Other constants can be added here
