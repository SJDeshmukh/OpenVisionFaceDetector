import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import People from './pages/People';
import Attendance from './pages/Attendance';
import Cameras from './pages/Cameras';
import Reports from './pages/Reports';
import Settings from './pages/Settings';
import AuditLogs from './pages/AuditLogs';
import Login from './pages/Login';
import Recharge from './pages/Recharge';
import Timetable from './pages/Timetable';
import Wages from './pages/Wages';
import LiveAttendance from './pages/LiveAttendance';
import BulkImageAttendance from './pages/BulkImageAttendance';
import Classes from './pages/Classes';
import AcademicManagement from './pages/AcademicManagement';
import SuperAdminDashboard from './pages/SuperAdminDashboard'; // New
import SuperAdminLogin from './pages/SuperAdminLogin';
import LiveFeed from './pages/LiveFeed';
import SystemHealth from './pages/SystemHealth';
import JobsDashboard from './pages/JobsDashboard';
import { AuthProvider, useAuth } from './context/AuthContext';
import { SocketProvider } from './context/SocketContext';
import Faces from './pages/Faces';
import LeaveManagement from './pages/LeaveManagement';
import FaceResetRequests from './pages/FaceResetRequests';
import OwnerAdvances from './pages/OwnerAdvances';
import HostelAlerts from './pages/HostelAlerts';
import HostelAllocation from './pages/HostelAllocation';
import PrivacyPolicy from './pages/PrivacyPolicy';

import { usesStudentRecords } from './lib/businessTerminology';
import { staffCanAccessNav } from './lib/staffNavigation';

// Protected Route Component
const ProtectedRoute = ({ allowedRoles }) => {
  const { user } = useAuth();

  if (!user) {
    // Redirect logic based on where they are trying to go?
    // For now, default to /login. SuperAdminLogin handles its own auth.
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    // If role not allowed, redirect to home or authorized page
    if (user.role === 'super_admin') return <Navigate to="/admin/vendors" replace />;
    if (user.role === 'user' || user.role === 'student') {
      const isStudent = usesStudentRecords(user?.vertical);
      return <Navigate to={isStudent ? "/leave-management" : "/attendance"} replace />;
    }
    return <Navigate to="/attendance" replace />;
  }

  return <Outlet />;
};

const FeatureRoute = ({ anyOf, children }) => {
  const { user } = useAuth();
  if (user?.role === 'super_admin') return children;
  const enabled = Array.isArray(user?.features) ? user.features : [];
  return anyOf.some(feature => enabled.includes(feature))
    ? children
    : <Navigate to="/dashboard" replace />;
};

const StaffNavigationRoute = ({ navKey, children }) => {
  const { staffSession } = useAuth();
  if (!staffSession || staffCanAccessNav(staffSession, navKey)) return children;
  return <Navigate to="/leave-management" replace />;
};

const FaceResetRoute = () => {
  const { user } = useAuth();
  const vertical = String(user?.vertical || '').trim().toLowerCase();
  const supported = !['daily_wages', 'wages', 'factory', 'enterprise'].includes(vertical) &&
    user?.features?.includes('parent_login');
  return supported ? <FaceResetRequests /> : <Navigate to="/dashboard" replace />;
};

const HostelAlertsRoute = () => {
  const { user } = useAuth();
  const allowed = ['vendor_admin', 'admin', 'owner'].includes(user?.role) &&
    user?.features?.includes('hostel_attendance_alerts');
  return allowed ? <HostelAlerts /> : <Navigate to="/dashboard" replace />;
};

const HostelAllocationRoute = () => {
  const { user, staffSession } = useAuth();
  const staffAllowed = !staffSession || staffCanAccessNav(staffSession, 'hostel_allocation');
  const allowed = staffAllowed && (Boolean(staffSession) || ['vendor_admin', 'admin', 'owner', 'rector', 'hod'].includes(user?.role)) &&
    user?.features?.includes('hostel_allocation');
  return allowed ? <HostelAllocation /> : <Navigate to="/dashboard" replace />;
};

function App() {
  return (
    <AuthProvider>
      <SocketProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/privacy-policy" element={<PrivacyPolicy />} />
            <Route path="/privacy" element={<Navigate to="/privacy-policy" replace />} />
            <Route path="/super_admin" element={<SuperAdminLogin />} />

            {/* Standalone Protected Routes */}
            <Route element={<ProtectedRoute allowedRoles={['vendor_admin', 'admin']} />}>
              <Route path="/recharge" element={<Recharge />} />
            </Route>

            <Route element={<Layout />}>
              {/* SuperAdmin Routes */}
              <Route element={<ProtectedRoute allowedRoles={['super_admin']} />}>
                <Route path="/admin/vendors" element={<SuperAdminDashboard />} />
                <Route path="/admin/audit-logs" element={<AuditLogs />} />
                <Route path="/admin/live-feed" element={<LiveFeed />} />
                <Route path="/admin/system-health" element={<SystemHealth />} />
                <Route path="/admin/jobs" element={<JobsDashboard />} />
              </Route>

              <Route element={<ProtectedRoute allowedRoles={['owner']} />}>
                <Route path="/owner/advances" element={<FeatureRoute anyOf={['payroll', 'report_payroll']}><OwnerAdvances /></FeatureRoute>} />
              </Route>

              {/* Admin/Rector/HOD/Faculty Routes */}
              <Route element={<ProtectedRoute allowedRoles={['admin', 'vendor_admin', 'owner', 'rector', 'hod', 'user', 'student', 'faculty']} />}>
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<StaffNavigationRoute navKey="dashboard"><Dashboard /></StaffNavigationRoute>} />
                <Route path="/people" element={<StaffNavigationRoute navKey="people"><People /></StaffNavigationRoute>} />
                <Route path="/attendance" element={<StaffNavigationRoute navKey="attendance"><Attendance /></StaffNavigationRoute>} />
                <Route path="/cameras" element={<StaffNavigationRoute navKey="cameras"><FeatureRoute anyOf={['cameras']}><Cameras /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/reports" element={<StaffNavigationRoute navKey="reports"><FeatureRoute anyOf={['reports', 'report_detailed', 'report_payroll', 'lecture_wise_reports', 'parent_login']}><Reports /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/settings" element={<StaffNavigationRoute navKey="settings"><Settings /></StaffNavigationRoute>} />
                <Route path="/timetable" element={<StaffNavigationRoute navKey="timetable"><FeatureRoute anyOf={['shifts', 'add_shift']}><Timetable /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/wages" element={<StaffNavigationRoute navKey="wages"><FeatureRoute anyOf={['payroll', 'report_payroll', 'payable_hours']}><Wages /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/live-attendance" element={<StaffNavigationRoute navKey="live_attendance"><FeatureRoute anyOf={['live_attendance']}><LiveAttendance /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/bulk-image-attendance" element={<StaffNavigationRoute navKey="bulk_image_attendance"><FeatureRoute anyOf={['bulk_image_attendance']}><BulkImageAttendance /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/classes" element={<StaffNavigationRoute navKey="classes"><FeatureRoute anyOf={['classes', 'bulk_image_attendance']}><Classes /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/resident-academic-setup" element={<StaffNavigationRoute navKey="academic_management"><FeatureRoute anyOf={['academic_management']}><AcademicManagement /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/faces" element={<StaffNavigationRoute navKey="faces"><FeatureRoute anyOf={['bulk_image_attendance', 'classes']}><Faces /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/leave-management" element={<StaffNavigationRoute navKey="leave_management"><FeatureRoute anyOf={['leave_management', 'parent_login']}><LeaveManagement /></FeatureRoute></StaffNavigationRoute>} />
                <Route path="/face-reset-requests" element={<StaffNavigationRoute navKey="face_reset_requests"><FaceResetRoute /></StaffNavigationRoute>} />
                <Route path="/hostel-alerts" element={<StaffNavigationRoute navKey="hostel_alerts"><HostelAlertsRoute /></StaffNavigationRoute>} />
                <Route path="/hostel-allocation" element={<HostelAllocationRoute />} />
              </Route>

              {/* Shared/User Routes */}
              <Route element={<ProtectedRoute allowedRoles={['admin', 'user', 'student', 'vendor_admin', 'owner', 'faculty']} />}>
                <Route path="/users" element={<StaffNavigationRoute navKey="people"><People /></StaffNavigationRoute>} />
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
      </SocketProvider>
    </AuthProvider>
  );
}

export default App;
