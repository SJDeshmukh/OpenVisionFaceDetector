import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import axios from 'axios';
import { API_URL } from '../config';

axios.defaults.withCredentials = true;

const AuthContext = createContext();

const withoutToken = (value) => {
  if (!value) return value;
  const safe = { ...value };
  delete safe.token;
  return safe;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [staffSession, setStaffSession] = useState(null);
  const [loading, setLoading] = useState(true);

  const clearSensitiveCaches = useCallback(() => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('people_cache_') || key.startsWith('dashboard_cache_') ||
          key.startsWith('bulk_attendance_batch_') || key.startsWith('registration_batch_id_') ||
          key.startsWith('admin_')) {
        localStorage.removeItem(key);
      }
    }
    ['registration_batch_id', 'active_lecture_id', 'lastClassFilter', 'token']
      .forEach((key) => localStorage.removeItem(key));
  }, []);

  const logout = useCallback(() => {
    const deviceId = localStorage.getItem('web_device_id');
    axios.post(`${API_URL}/auth/logout`, { username: user?.username, device_id: deviceId }).catch(() => {});
    setUser(null);
    setStaffSession(null);
    localStorage.removeItem('user');
    localStorage.removeItem('staffSession');
    clearSensitiveCaches();
    delete axios.defaults.headers.common.Authorization;
  }, [clearSensitiveCaches, user?.username]);

  const refreshUserData = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_URL}/auth/me`);
      if (!data) return null;
      if (data.web_login_enabled === 0 && data.role !== 'super_admin') {
        logout();
        return null;
      }
      setUser((previous) => {
        const next = withoutToken({
          ...(previous || {}), username: data.username, role: data.role,
          vendor_id: data.vendor_id, company_id: data.company_id, frontend_bundle_id: data.frontend_bundle_id,
          backend_service_id: data.backend_service_id, vendor_config: data.vendor_config,
          features: data.features || [], vertical: data.vertical,
          web_login_enabled: data.web_login_enabled, person_id: data.person_id,
          id: data.username,
        });
        localStorage.setItem('user', JSON.stringify(next));
        return next;
      });
      return data;
    } catch (error) {
      if (error.response?.status !== 401) console.error('Refresh user data failed:', error);
      return null;
    }
  }, [logout]);

  useEffect(() => {
    try {
      const storedUser = localStorage.getItem('user');
      if (storedUser) {
        const safeUser = withoutToken(JSON.parse(storedUser));
        setUser(safeUser);
        localStorage.setItem('user', JSON.stringify(safeUser));
        refreshUserData().catch(() => {});
      }
      const storedStaff = localStorage.getItem('staffSession');
      if (storedStaff) setStaffSession(JSON.parse(storedStaff));
    } catch {
      localStorage.removeItem('user');
      localStorage.removeItem('staffSession');
    }
    delete axios.defaults.headers.common['ngrok-skip-browser-warning'];
    delete axios.defaults.headers.common.Authorization;
    setLoading(false);

    const interceptor = axios.interceptors.response.use(
      (response) => response,
      (error) => {
        const status = error.response?.status;
        const message = error.response?.data?.error || '';
        const suspended = message.includes('Subscription Expired') ||
          message.includes('Account Suspended') || message.includes('Service Suspended');
        const featureMissing = message.includes('Feature') && message.includes('not enabled');
        if (status === 401 || (status === 403 && suspended)) {
          logout();
          if (window.location.pathname !== '/login') window.location.assign('/login');
        } else if (status === 403 && featureMissing) {
          refreshUserData().catch(() => {});
        }
        return Promise.reject(error);
      },
    );
    return () => axios.interceptors.response.eject(interceptor);
  }, [logout, refreshUserData]);

  const login = async (username, password, secondary_password = null) => {
    try {
      let deviceId = localStorage.getItem('web_device_id');
      if (!deviceId) {
        deviceId = `web-${crypto.randomUUID()}`;
        localStorage.setItem('web_device_id', deviceId);
      }
      const response = await axios.post(`${API_URL}/auth/login`, {
        username, password, secondary_password, device_id: deviceId, platform: 'web',
      });
      if (response.data.status !== 'success') {
        return { success: false, error: response.data.error || 'Unexpected response from server' };
      }
      if (response.data.needs_student_password) {
        return { success: true, status: 'success', needs_student_password: true, username: response.data.username };
      }
      const userData = withoutToken({
        id: response.data.username, username: response.data.username, role: response.data.role,
        vendor_id: response.data.vendor_id, company_id: response.data.company_id,
        frontend_bundle_id: response.data.frontend_bundle_id,
        backend_service_id: response.data.backend_service_id,
        vendor_config: response.data.vendor_config, features: response.data.features || [],
        vertical: response.data.vertical, person_id: response.data.person_id,
      });
      setUser(userData);
      localStorage.setItem('user', JSON.stringify(userData));
      return {
        success: true, role: userData.role, redirect_url: response.data.redirect_url,
        force_password_change: response.data.force_password_change || false,
      };
    } catch (error) {
      return { success: false, error: error.response?.data?.error || error.message || 'Login failed' };
    }
  };

  const loginAsStaff = async (pin) => {
    if (!user?.vendor_id) return { success: false, error: 'Not logged in' };
    try {
      const { data } = await axios.post(`${API_URL}/leave/admin/verify-pin`, { vendor_id: user.vendor_id, pin });
      if (data.status === 'success') {
        setStaffSession(data.staff);
        localStorage.setItem('staffSession', JSON.stringify(data.staff));
        return { success: true, staff: data.staff };
      }
      return { success: false, error: 'Invalid PIN' };
    } catch (error) {
      return { success: false, error: error.response?.data?.error || 'Verification failed' };
    }
  };

  const logoutStaff = () => {
    setStaffSession(null);
    localStorage.removeItem('staffSession');
  };

  return (
    <AuthContext.Provider value={{
      user, staffSession, login, logout, loginAsStaff, logoutStaff,
      loading, refreshFeatures: refreshUserData, refreshUserData,
    }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
