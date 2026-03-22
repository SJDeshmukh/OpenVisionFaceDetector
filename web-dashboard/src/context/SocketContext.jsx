import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { io } from 'socket.io-client';
import { BASE_URL } from '../config';
import { useAuth } from './AuthContext';

const SocketContext = createContext(null);

export const SocketProvider = ({ children }) => {
  const { user, logout, refreshFeatures, refreshUserData } = useAuth();
  const [socket, setSocket] = useState(null);
  const [toastMsg, setToastMsg] = useState(null);

  useEffect(() => {
    if (!user || !user.token) {
      if (socket) {
        socket.disconnect();
        setSocket(null);
      }
      return;
    }
    const s = io(BASE_URL, { 
      transports: ['polling'],
      upgrade: false,
      path: '/socket.io/',
      withCredentials: true,
      reconnectionAttempts: 5,
      query: {}
    });
    setSocket(s);

    s.on('force_logout', (data) => {
      if (user.role === 'vendor' || user.role === 'vendor_admin' || user.role === 'admin') {
        if (String(data.vendor_id) === String(user.vendor_id)) {
          console.log("Force logout received via Socket.IO:", data.reason);
          logout();
          window.location.href = '/login';
        }
      }
    });
    
    s.on('force_logout_web', (data) => {
      if (user.role === 'vendor' || user.role === 'vendor_admin' || user.role === 'admin') {
        if (String(data.vendor_id) === String(user.vendor_id)) {
          console.log("Force logout (web) via Socket.IO:", data.reason);
          logout();
          window.location.href = '/login';
        }
      }
    });
    
    s.on('features_updated', async (data) => {
      try {
        if (!data || !data.vendor_id) return;
        if (String(data.vendor_id) !== String(user.vendor_id)) return;
        await refreshFeatures();
        setToastMsg("Plan updated");
        setTimeout(() => setToastMsg(null), 3000);
      } catch (e) {}
    });

    s.on('vendor_updated', async (data) => {
      try {
        if (!data || !data.vendor_id) return;
        if (String(data.vendor_id) !== String(user.vendor_id)) return;
        await refreshUserData();
      } catch (e) {}
    });

    return () => {
      if (s) s.disconnect();
    };
  }, [user]);

  useEffect(() => {
    if (!socket || !user) return;

    const joinRooms = () => {
      if (user.role === 'super_admin') {
        socket.emit('join_super_admin');
        return;
      }
      if (user.vendor_id) {
        socket.emit('join_vendor', { vendor_id: user.vendor_id });
      }
    };

    if (socket.connected) {
      joinRooms();
    }

    socket.on('connect', joinRooms);
    return () => {
      socket.off('connect', joinRooms);
    };
  }, [socket, user]);

  const value = useMemo(() => {
    const joinVendor = (vendor_id) => {
      if (!socket || !vendor_id) return;
      socket.emit('join_vendor', { vendor_id });
    };
    const joinSuperAdmin = () => {
      if (!socket) return;
      socket.emit('join_super_admin');
    };
    return { socket, joinVendor, joinSuperAdmin };
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
