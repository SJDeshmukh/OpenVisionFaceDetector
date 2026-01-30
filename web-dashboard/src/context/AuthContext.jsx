import { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { io } from 'socket.io-client';
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
        if (error.response && (error.response.status === 401 || error.response.status === 403)) {
           // Check if it's an auth error (not just some permission error for a specific resource)
           // However, for vendor suspension (403 Access Denied), we SHOULD logout.
           const errorMessage = error.response.data?.error || "";
           if (errorMessage.includes("Access Denied") || errorMessage.includes("Invalid or Expired Token") || errorMessage.includes("Authentication Required")) {
               console.log("Auto-logout triggered due to auth error:", errorMessage);
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

  // Socket.IO for Force Logout (and other real-time auth events)
  useEffect(() => {
    let socket;
    if (user && user.token) {
        socket = io(BASE_URL);
        
        socket.on('connect', () => {
            console.log("Auth Socket connected");
            if (user.role === 'vendor' && user.vendor_id) {
                // We don't necessarily need to join a room if the backend broadcasts to all clients
                // But typically backend emits to specific rooms or namespaces.
                // The current backend implementation emits 'force_logout' with {vendor_id} to all clients (broadcast=True by default in socketio.emit if no room specified)
                // OR creates a room for the vendor.
                // Let's check backend implementation of suspend_vendor:
                // socketio.emit('force_logout', {'vendor_id': vendor_id}) -> Broadcasts to ALL.
                // So we just need to filter on client side.
            }
        });

        socket.on('force_logout', (data) => {
            if (user.role === 'vendor' && String(data.vendor_id) === String(user.vendor_id)) {
                 console.log("Force logout received via Socket.IO");
                 logout();
                 window.location.href = '/login';
            }
        });
    }
    return () => {
        if (socket) socket.disconnect();
    };
  }, [user]);


  const login = async (username, password) => {
    try {
      const response = await axios.post(`${API_URL}/auth/login`, {
        username,
        password
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