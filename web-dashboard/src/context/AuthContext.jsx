import { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL, BASE_URL } from '../config';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check local storage for session
    const storedUser = localStorage.getItem('user');
    if (storedUser) {
      const parsedUser = JSON.parse(storedUser);
      setUser(parsedUser);
      if (parsedUser.token) {
        axios.defaults.headers.common['Authorization'] = `Bearer ${parsedUser.token}`;
      }
    }
    setLoading(false);

    // Add Axios Interceptor for Auto-Logout
    const interceptor = axios.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response) {
          const status = error.response.status;
          const errorMessage = error.response.data?.error || "";
          
          // 401 is always an auth failure. 
          // 403 with "Access Denied" or "Subscription Expired" is a suspension/expiry.
          if (status === 401 || (status === 403 && (errorMessage.includes("Access Denied") || errorMessage.includes("Subscription Expired")))) {
             console.log("Auto-logout triggered due to status:", status, "message:", errorMessage);
             logout();
             window.location.href = '/login'; // Force redirect
          }
        }
        return Promise.reject(error);
      }
    );

    return () => {
      axios.interceptors.response.eject(interceptor);
    };
  }, []);


  const login = async (username, password) => {
    try {
      let deviceId = localStorage.getItem('web_device_id');
      if (!deviceId) {
        deviceId = `web-${Math.random().toString(36).slice(2)}-${Date.now()}`;
        localStorage.setItem('web_device_id', deviceId);
      }
      const response = await axios.post(`${API_URL}/auth/login`, {
        username,
        password,
        device_id: deviceId,
        platform: 'web'
      });

      if (response.data.status === 'success') {
        const userData = {
          username: response.data.username,
          role: response.data.role,
          token: response.data.token,
          vendor_id: response.data.vendor_id,
          company_id: response.data.company_id,
          frontend_bundle_id: response.data.frontend_bundle_id,
          backend_service_id: response.data.backend_service_id,
          vendor_config: response.data.vendor_config,
          features: response.data.features || []
        };
        setUser(userData);
        localStorage.setItem('user', JSON.stringify(userData));
        axios.defaults.headers.common['Authorization'] = `Bearer ${userData.token}`;
        return { success: true, role: userData.role, redirect_url: response.data.redirect_url };
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
      axios.post(`${API_URL}/auth/logout`, { username, device_id: deviceId }).catch(() => {});
    } catch (e) {}
    setUser(null);
    localStorage.removeItem('user');
    delete axios.defaults.headers.common['Authorization'];
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
