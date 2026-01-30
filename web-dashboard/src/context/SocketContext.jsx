import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { io } from 'socket.io-client';
import { BASE_URL } from '../config';
import { useAuth } from './AuthContext';

const SocketContext = createContext(null);

export const SocketProvider = ({ children }) => {
  const { user } = useAuth();
  const [socket, setSocket] = useState(null);

  useEffect(() => {
    if (!user || !user.token) {
      if (socket) {
        socket.disconnect();
        setSocket(null);
      }
      return;
    }
    const s = io(BASE_URL, { transports: ['polling'], upgrade: false, path: '/socket.io' });
    setSocket(s);
    return () => {
      if (s) s.disconnect();
    };
  }, [user]);

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

  return <SocketContext.Provider value={value}>{children}</SocketContext.Provider>;
};

export const useSocket = () => useContext(SocketContext);
