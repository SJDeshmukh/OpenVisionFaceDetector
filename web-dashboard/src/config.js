let backendUrl = import.meta.env.VITE_BACKEND_URL;

if (!backendUrl) {
  // If env var is missing, check if we are in development or production
  if (import.meta.env.DEV) {
    backendUrl = 'http://127.0.0.1:5001';
  } else {
    // Hardcoded fallback for production to ensure it works on Render
    backendUrl = 'https://face-detection-backend-69o7.onrender.com';
  }
}

if (!backendUrl.startsWith('http')) {
  backendUrl = `https://${backendUrl}`;
}
const BACKEND_URL = backendUrl.replace(/\/$/, '');
export const API_URL = `${BACKEND_URL}/api`;
