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
import SuperAdminDashboard from './pages/SuperAdminDashboard'; // New
import SuperAdminLogin from './pages/SuperAdminLogin';
import LiveFeed from './pages/LiveFeed';
import SystemHealth from './pages/SystemHealth';
import JobsDashboard from './pages/JobsDashboard';
import { AuthProvider, useAuth } from './context/AuthContext';
import { SocketProvider } from './context/SocketContext';
import Faces from './pages/Faces';

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
    return <Navigate to="/attendance" replace />;
  }

  return <Outlet />;
};

function App() {
  return (
    <AuthProvider>
      <SocketProvider>
        <BrowserRouter>
          <Routes>
          <Route path="/login" element={<Login />} />
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

            {/* Admin Routes */}
            <Route element={<ProtectedRoute allowedRoles={['admin', 'vendor_admin']} />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/people" element={<People />} />
              <Route path="/cameras" element={<Cameras />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/timetable" element={<Timetable />} />
              <Route path="/wages" element={<Wages />} />
              <Route path="/live-attendance" element={<LiveAttendance />} />
              <Route path="/bulk-image-attendance" element={<BulkImageAttendance />} />
              <Route path="/classes" element={<Classes />} />
              <Route path="/faces" element={<Faces />} />
            </Route>

            {/* Shared/User Routes */}
            <Route element={<ProtectedRoute allowedRoles={['admin', 'user', 'vendor_admin']} />}>
               {/* User lands on Attendance/Identify page */}
               <Route path="/attendance" element={<Attendance />} />
               {/* Allow users to access People page? Maybe restrict based on role if needed, but for now keeping as is */}
               <Route path="/users" element={<People />} /> 
            </Route>
          </Route>
          </Routes>
        </BrowserRouter>
      </SocketProvider>
    </AuthProvider>
  );
}

export default App;
