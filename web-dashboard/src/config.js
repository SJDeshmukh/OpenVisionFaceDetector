// Central Configuration
// You can switch between Local and Production here

const LOCAL_BACKEND = 'http://127.0.0.1:5001';

// Active Backend Configuration
// 1. Build-time Env Var (VITE_API_URL) - Best for Static Site Hosting (S3, Vercel, etc.)
// 2. Localhost Default - For local development
// 3. Relative Path / Origin - Fallback for generic server deployments (EC2, Nginx) where API is on same domain
const ENV_API_URL = import.meta.env.VITE_API_URL;
const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';

// If no Env Var is set, and we are NOT local, we assume the API is reachable via the current origin
// (This works if you proxy /api to the backend, or serve frontend from the backend)
const BASE_URL = ENV_API_URL || (isLocal ? LOCAL_BACKEND : 'https://face-detection-backend-69o7.onrender.com');

export const API_URL = `${BASE_URL}/api`;
export const API_BASE_URL = API_URL;

export const FRONTEND_BUNDLES = {
  'attendance_ui': ['Dashboard', 'Attendance', 'Live Attendance', 'Settings', 'Reports', 'People', 'Cameras', 'Audit Logs'],
  'attendance_payroll_ui': ['Dashboard', 'Attendance', 'Live Attendance', 'Wages', 'Settings', 'Reports', 'People', 'Cameras', 'Audit Logs', 'Timetable'],
  'enterprise_custom_ui': 'ALL',
  'default_attendance': 'ALL' 
};
