import { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL, BASE_URL } from '../config';

// Always send cookies (httpOnly session token) with cross-origin requests
axios.defaults.withCredentials = true;

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [staffSession, setStaffSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Load user profile from localStorage
    const storedUser = localStorage.getItem('user');
    if (storedUser) {
      const parsedUser = JSON.parse(storedUser);
      setUser(parsedUser);
      // Restore Authorization header from stored token
      if (parsedUser.token) {
        axios.defaults.headers.common['Authorization'] = `Bearer ${parsedUser.token}`;
      }
      // If student and person_id is missing, force a refresh
      if (parsedUser.role === 'user' && !parsedUser.person_id) {
        refreshUserData().catch(() => {});
      }
    }

    const storedStaff = localStorage.getItem('staffSession');
    if (storedStaff) {
      setStaffSession(JSON.parse(storedStaff));
    }
    // Remove ngrok-specific header handling
    delete axios.defaults.headers.common['ngrok-skip-browser-warning'];
    setLoading(false);

    // Add Axios Interceptor for Auto-Logout
    const interceptor = axios.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response) {
          const status = error.response.status;
          const errorMessage = error.response.data?.error || "";

          // 401 is always an auth failure.
          // 403 with "Subscription Expired" or explicit suspension should logout.
          const isSuspended = errorMessage.includes("Subscription Expired") || errorMessage.includes("Account Suspended") || errorMessage.includes("Service Suspended");
          const isFeatureMissing = errorMessage.includes("Feature") && errorMessage.includes("not enabled");
          if (status === 401 || (status === 403 && isSuspended)) {
             console.log("Auto-logout triggered due to status:", status, "message:", errorMessage);
             logout();
             window.location.href = '/login'; // Force redirect
          } else if (status === 403 && isFeatureMissing) {
             // Feature removed from plan: refresh profile and continue (no logout)
             try {
               refreshUserData().catch(() => {});
             } catch (e) {}
          }
        }
        return Promise.reject(error);
      }
    );

    return () => {
      axios.interceptors.response.eject(interceptor);
    };
  }, []);


  const login = async (username, password, secondary_password = null) => {
    try {
      let deviceId = localStorage.getItem('web_device_id');
      if (!deviceId) {
        deviceId = `web-${Math.random().toString(36).slice(2)}-${Date.now()}`;
        localStorage.setItem('web_device_id', deviceId);
      }
      const response = await axios.post(`${API_URL}/auth/login`, {
        username,
        password,
        secondary_password,
        device_id: deviceId,
        platform: 'web'
      });

      if (response.data.status === 'success') {
        if (response.data.needs_student_password) {
          return {
            success: true,
            status: 'success',
            needs_student_password: true,
            username: response.data.username
          };
        }
        const userData = {
          id: response.data.username,
          username: response.data.username,
          role: response.data.role,
          token: response.data.token,
          vendor_id: response.data.vendor_id,
          company_id: response.data.company_id,
          frontend_bundle_id: response.data.frontend_bundle_id,
          backend_service_id: response.data.backend_service_id,
          vendor_config: response.data.vendor_config,
          features: response.data.features || [],
          vertical: response.data.vertical,
          person_id: response.data.person_id
        };
        setUser(userData);
        localStorage.setItem('user', JSON.stringify(userData));
        axios.defaults.headers.common['Authorization'] = `Bearer ${userData.token}`;
        return {
          success: true,
          role: userData.role,
          redirect_url: response.data.redirect_url,
          force_password_change: response.data.force_password_change || false
        };
      } else {
        // Handle case where status is not success but no error was thrown
        return { success: false, error: response.data.error || "Unexpected response from server" };
      }
    } catch (error) {
      console.error("Login failed:", error);
      const errorMsg = error.response?.data?.error || error.message || "Login failed";
      return { success: false, error: errorMsg };
    }
  };

  const logout = () => {
    try {
      const deviceId = localStorage.getItem('web_device_id');
      const username = user?.username;
      // withCredentials=true (global default) ensures the cookie is sent so
      // the backend can delete both the active_sessions row AND clear the cookie.
      axios.post(`${API_URL}/auth/logout`, { username, device_id: deviceId }).catch(() => {});
    } catch (e) {}
    setUser(null);
    setStaffSession(null);
    localStorage.removeItem('user');
    localStorage.removeItem('staffSession');
    delete axios.defaults.headers.common['Authorization'];
  };

  const loginAsStaff = async (pin) => {
    if (!user?.vendor_id) return { success: false, error: "Not logged in" };
    try {
      const res = await axios.post(`${API_URL}/leave/admin/verify-pin`, {
        vendor_id: user.vendor_id,
        pin
      });
      if (res.data.status === 'success') {
        const staffData = res.data.staff;
        setStaffSession(staffData);
        localStorage.setItem('staffSession', JSON.stringify(staffData));
        return { success: true, staff: staffData };
      }
      return { success: false, error: "Invalid PIN" };
    } catch (e) {
      return { success: false, error: e.response?.data?.error || "Verification failed" };
    }
  };

  const logoutStaff = () => {
    setStaffSession(null);
    localStorage.removeItem('staffSession');
  };

  const refreshUserData = async () => {
    try {
      const res = await axios.get(`${API_URL}/auth/me`);
      const data = res.data;
      if (!data) return null;

      setUser((prev) => {
        if (!prev) return prev;
        const next = {
          ...prev,
          username: data.username,
          role: data.role,
          vendor_id: data.vendor_id,
          frontend_bundle_id: data.frontend_bundle_id,
          backend_service_id: data.backend_service_id,
          vendor_config: data.vendor_config,
          features: data.features || [],
          vertical: data.vertical,
          web_login_enabled: data.web_login_enabled,
          person_id: data.person_id,
          id: data.username
        };

        // If web login is disabled for this vendor, force logout
        if (data.web_login_enabled === 0 && data.role !== 'super_admin') {
           console.log("Web login disabled for vendor, logging out...");
           logout();
           window.location.href = '/login';
           return null;
        }

        localStorage.setItem('user', JSON.stringify(next));
        return next;
      });
      return data;
    } catch (e) {
      console.error("Refresh User Data failed:", e);
      return null;
    }
  };

  const refreshFeatures = refreshUserData; // Keep alias for compatibility

  return (
    <AuthContext.Provider value={{
      user, staffSession, login, logout, loginAsStaff, logoutStaff,
      loading, refreshFeatures, refreshUserData
    }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
