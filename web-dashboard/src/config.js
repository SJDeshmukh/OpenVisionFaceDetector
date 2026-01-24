const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:5001').replace(/\/$/, '');
export const API_URL = `${BACKEND_URL}/api`;
