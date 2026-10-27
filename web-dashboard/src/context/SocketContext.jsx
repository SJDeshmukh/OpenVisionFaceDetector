import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { io } from 'socket.io-client';
import { BASE_URL } from '../config';
import { useAuth } from './AuthContext';

const SocketContext = createContext(null);

export const SocketProvider = ({ children }) => {
  const { user, logout, refreshFeatures } = useAuth();
  const [socket, setSocket] = useState(null);
  const [toastMsg, setToastMsg] = useState(null);
  const userRole = user?.role;
  const vendorId = user?.vendor_id;
  const isAuthenticated = Boolean(user);

  useEffect(() => {
    if (!isAuthenticated) {
      setSocket((current) => {
        current?.disconnect();
        return null;
      });
      return;
    }
    const s = io(BASE_URL, {
      // Never fall back to long polling here. On a small Gunicorn instance,
      // failed polling sessions can occupy every request thread and hold API
      // mutations until the polling timeout expires.
      transports: ['websocket'],
      path: '/socket.io/',
      withCredentials: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 10000,
      auth: {}
    });
    setSocket(s);

    s.on('force_logout', (data) => {
      if (userRole === 'vendor' || userRole === 'vendor_admin' || userRole === 'admin') {
        if (String(data.vendor_id) === String(vendorId)) {
          console.log("Force logout received via Socket.IO:", data.reason);
          logout();
          window.location.href = '/login';
        }
      }
    });
    
    s.on('force_logout_web', (data) => {
      if (userRole === 'vendor' || userRole === 'vendor_admin' || userRole === 'admin') {
        if (String(data.vendor_id) === String(vendorId)) {
          console.log("Force logout (web) via Socket.IO:", data.reason);
          logout();
          window.location.href = '/login';
        }
      }
    });
    
    s.on('features_updated', async (data) => {
      try {
        if (!data || !data.vendor_id) return;
        if (String(data.vendor_id) !== String(vendorId)) return;
        await refreshFeatures();
        setToastMsg("Plan updated");
        setTimeout(() => setToastMsg(null), 3000);
      } catch (e) {}
    });

    return () => {
      if (s) s.disconnect();
    };
  }, [isAuthenticated, userRole, vendorId, logout, refreshFeatures]);

  useEffect(() => {
    if (!socket || !isAuthenticated) return;

    const joinRooms = () => {
      if (userRole === 'super_admin') {
        socket.emit('join_super_admin');
        return;
      }
      if (vendorId) {
        socket.emit('join_vendor', { vendor_id: vendorId });
      }
    };

    if (socket.connected) {
      joinRooms();
    }

    socket.on('connect', joinRooms);
    return () => {
      socket.off('connect', joinRooms);
    };
  }, [socket, isAuthenticated, userRole, vendorId]);

  const value = useMemo(() => {
    const joinVendor = (vendor_id) => {
      if (!socket || !vendor_id) return;
      socket.emit('join_vendor', { vendor_id });
    };
    const joinSuperAdmin = () => {
      if (!socket) return;
      socket.emit('join_super_admin');
    };
    const on = (event, handler) => socket?.on?.(event, handler);
    const off = (event, handler) => socket?.off?.(event, handler);
    const emit = (event, ...args) => socket?.emit?.(event, ...args);
    return { socket, joinVendor, joinSuperAdmin, on, off, emit };
  }, [socket]);

  return <SocketContext.Provider value={value}>
    {children}
    {toastMsg && (
      <div className="fixed bottom-4 right-4 bg-slate-900 text-white px-4 py-2 rounded shadow-lg z-50 text-sm">
        {toastMsg}
      </div>
    )}
  </SocketContext.Provider>;
};

export const useSocket = () => useContext(SocketContext);
