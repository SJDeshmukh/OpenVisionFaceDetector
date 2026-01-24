let backendUrl = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:5001';
if (!backendUrl.startsWith('http')) {
  backendUrl = `https://${backendUrl}`;
}
const BACKEND_URL = backendUrl.replace(/\/$/, '');
export const API_URL = `${BACKEND_URL}/api`;
