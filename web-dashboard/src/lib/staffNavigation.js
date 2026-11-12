export const STAFF_NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', path: '/dashboard' },
  { key: 'people', label: 'People', path: '/people' },
  { key: 'faces', label: 'Faces', path: '/faces' },
  { key: 'classes', label: 'Classes', path: '/classes' },
  { key: 'academic_management', label: 'Resident Academic Setup', path: '/resident-academic-setup' },
  { key: 'timetable', label: 'Timetable', path: '/timetable' },
  { key: 'wages', label: 'Wages', path: '/wages' },
  { key: 'attendance', label: 'Attendance', path: '/attendance' },
  { key: 'bulk_image_attendance', label: 'Bulk Image Attendance', path: '/bulk-image-attendance' },
  { key: 'live_attendance', label: 'Live Attendance', path: '/live-attendance' },
  { key: 'cameras', label: 'Cameras', path: '/cameras' },
  { key: 'reports', label: 'Reports', path: '/reports' },
  { key: 'settings', label: 'Settings', path: '/settings' },
  { key: 'leave_management', label: 'Leave Management', path: '/leave-management', required: true },
  { key: 'face_reset_requests', label: 'Face Reset Requests', path: '/face-reset-requests' },
  { key: 'hostel_alerts', label: 'Hostel Alerts', path: '/hostel-alerts' },
  { key: 'hostel_allocation', label: 'Hostel Allocation', path: '/hostel-allocation' },
];

export const DEFAULT_STAFF_NAV_KEYS = ['dashboard', 'leave_management'];

export const BASE_STAFF_NAV_KEYS = ['dashboard', 'people', 'attendance', 'settings'];
export const STAFF_NAV_FEATURE_REQUIREMENTS = {
  faces: ['classes', 'bulk_image_attendance'],
  classes: ['classes', 'bulk_image_attendance', 'lecture_wise_reports'],
  academic_management: ['academic_management'],
  timetable: ['shifts', 'add_shift'],
  wages: ['payroll', 'report_payroll'],
  bulk_image_attendance: ['bulk_image_attendance'],
  live_attendance: ['live_attendance'],
  cameras: ['cameras'],
  reports: ['reports', 'report_detailed', 'report_payroll', 'lecture_wise_reports'],
  leave_management: ['leave_management'],
  face_reset_requests: ['parent_login'],
  hostel_alerts: ['hostel_attendance_alerts'],
  hostel_allocation: ['hostel_allocation'],
};

const KNOWN_KEYS = new Set(STAFF_NAV_ITEMS.map(item => item.key));
const PATH_TO_KEY = new Map(STAFF_NAV_ITEMS.map(item => [item.path, item.key]));

const featureSet = (features) => {
  if (Array.isArray(features)) return new Set(features);
  if (typeof features === 'string') {
    try {
      const parsed = JSON.parse(features);
      return new Set(Array.isArray(parsed) ? parsed : []);
    } catch {
      return new Set();
    }
  }
  return new Set();
};

export const staffNavItemsForFeatures = (features) => {
  const enabled = featureSet(features);
  const base = new Set(BASE_STAFF_NAV_KEYS);
  return STAFF_NAV_ITEMS.filter(item => {
    if (base.has(item.key)) return true;
    const requirements = STAFF_NAV_FEATURE_REQUIREMENTS[item.key] || [];
    return requirements.some(feature => enabled.has(feature));
  });
};

export const normalizeStaffNavKeys = (value) => {
  const source = Array.isArray(value) ? value : DEFAULT_STAFF_NAV_KEYS;
  const selected = new Set(source.filter(key => KNOWN_KEYS.has(key)));
  selected.add('leave_management');
  return STAFF_NAV_ITEMS.map(item => item.key).filter(key => selected.has(key));
};

export const staffCanAccessNav = (staffSession, key) => {
  if (!staffSession) return true;
  return normalizeStaffNavKeys(staffSession.navbar_items).includes(key);
};

export const staffCanAccessPath = (staffSession, path) => {
  if (!staffSession) return true;
  const key = PATH_TO_KEY.get(path);
  return Boolean(key) && staffCanAccessNav(staffSession, key);
};

export const toggleStaffNavKey = (value, key) => {
  const selected = new Set(normalizeStaffNavKeys(value));
  if (key === 'leave_management') return [...selected];
  if (selected.has(key)) selected.delete(key);
  else selected.add(key);
  return STAFF_NAV_ITEMS.map(item => item.key).filter(itemKey => selected.has(itemKey));
};
