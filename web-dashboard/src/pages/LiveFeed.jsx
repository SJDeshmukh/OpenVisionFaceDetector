import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';
import { Monitor, Wifi, WifiOff, RefreshCw, Maximize2, X } from 'lucide-react';

const DeviceMonitor = ({ vendorId, deviceId, deviceName }) => {
  const { user } = useAuth();
  const [image, setImage] = useState(null);
  const [status, setStatus] = useState('connecting'); // connecting, online, offline
  const [lastSeen, setLastSeen] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    let mounted = true;
    
    const fetchFrame = async () => {
      try {
        const response = await axios.get(`${API_URL}/stream/view`, {
            params: { vendor_id: vendorId, device_id: deviceId },
            headers: { Authorization: `Bearer ${user?.token}` }
        });
        
        if (mounted) {
            if (response.data.status === 'online' && response.data.image) {
                setImage(response.data.image.startsWith('data:') ? response.data.image : `data:image/jpeg;base64,${response.data.image}`);
                setStatus('online');
                setLastSeen(new Date());
            } else {
                setStatus('offline');
            }
        }
      } catch (error) {
        if (mounted) setStatus('error');
      }
    };

    fetchFrame();
    const interval = setInterval(fetchFrame, 1000); // 1 FPS

    return () => {
        mounted = false;
        clearInterval(interval);
    };
  }, [vendorId, deviceId, user]);

  const toggleFullscreen = () => setIsFullscreen(!isFullscreen);

  // Fullscreen Modal View
  if (isFullscreen) {
      return (
        <div className="fixed inset-0 z-50 bg-black flex flex-col items-center justify-center p-4">
            <div className="absolute top-4 right-4 flex gap-4">
                 <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium ${status === 'online' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                    {status === 'online' ? <Wifi size={16} /> : <WifiOff size={16} />}
                    {status === 'online' ? 'Live' : 'Offline'}
                </div>
                <button onClick={toggleFullscreen} className="bg-white/10 hover:bg-white/20 text-white p-2 rounded-full backdrop-blur-sm transition-colors">
                    <X size={24} />
                </button>
            </div>
            
            {image ? (
                <img 
                    src={image} 
                    alt={`Live feed from ${deviceName}`} 
                    className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
                />
            ) : (
                <div className="text-white text-center">
                    <WifiOff size={48} className="mx-auto mb-4 opacity-50" />
                    <p className="text-xl">Stream Offline</p>
                </div>
            )}
            
            <div className="absolute bottom-8 left-0 right-0 text-center">
                <h3 className="text-white text-xl font-bold mb-1">{deviceName}</h3>
                <p className="text-slate-400 text-sm">Vendor ID: {vendorId} • Device ID: {deviceId}</p>
            </div>
        </div>
      );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
        <div className="flex items-center gap-2 min-w-0">
            <Monitor size={16} className="text-blue-500 shrink-0" />
            <span className="font-semibold text-slate-700 truncate text-sm" title={deviceName}>{deviceName}</span>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${status === 'online' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>
            <div className={`w-1.5 h-1.5 rounded-full ${status === 'online' ? 'bg-green-500 animate-pulse' : 'bg-slate-400'}`} />
            {status === 'online' ? 'LIVE' : 'OFF'}
        </div>
      </div>

      {/* Video Area */}
      <div className="relative aspect-video bg-slate-900 flex items-center justify-center group">
        {image && status === 'online' ? (
            <img 
                src={image} 
                alt="Live" 
                className="w-full h-full object-cover" 
            />
        ) : (
            <div className="text-slate-500 flex flex-col items-center">
                <WifiOff size={32} className="mb-2 opacity-50" />
                <span className="text-xs">Signal Lost</span>
            </div>
        )}
        
        {/* Overlay Controls */}
        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
             <button 
                onClick={toggleFullscreen}
                className="bg-white/20 hover:bg-white/30 text-white p-2 rounded-full backdrop-blur-sm transition-transform hover:scale-110"
                title="Fullscreen"
            >
                <Maximize2 size={20} />
            </button>
        </div>
      </div>

      {/* Footer Info */}
      <div className="px-4 py-2 bg-white text-xs text-slate-500 flex justify-between items-center border-t border-slate-100">
        <span>ID: {deviceId}</span>
        <span>Vendor: #{vendorId}</span>
      </div>
    </div>
  );
};

const LiveFeed = () => {
  const { user } = useAuth();
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(new Date());

  const fetchActiveDevices = async () => {
    try {
      const response = await axios.get(`${API_URL}/stream/active-devices`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setDevices(response.data.devices || []);
      setLastUpdated(new Date());
    } catch (error) {
      console.error("Error fetching active devices:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchActiveDevices();
    const interval = setInterval(fetchActiveDevices, 5000); // Refresh list every 5s
    return () => clearInterval(interval);
  }, []);

  // Group devices by Vendor
  const devicesByVendor = devices.reduce((acc, dev) => {
      if (!acc[dev.vendor_id]) acc[dev.vendor_id] = [];
      acc[dev.vendor_id].push(dev);
      return acc;
  }, {});

  return (
    <div className="space-y-6 p-6">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <Monitor className="text-blue-600" />
            Global Live Feed
          </h1>
          <p className="text-slate-500 mt-1">Real-time surveillance from all active mobile terminals.</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-400">
            <RefreshCw size={14} className="animate-spin-slow" />
            Updated: {lastUpdated.toLocaleTimeString()}
        </div>
      </div>

      {loading ? (
          <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          </div>
      ) : devices.length === 0 ? (
          <div className="bg-slate-50 rounded-2xl border-2 border-dashed border-slate-200 p-12 text-center">
              <div className="w-16 h-16 bg-white rounded-full flex items-center justify-center mx-auto mb-4 shadow-sm border border-slate-100">
                  <WifiOff size={32} className="text-slate-300" />
              </div>
              <h3 className="text-lg font-semibold text-slate-700 mb-2">No Active Streams</h3>
              <p className="text-slate-500 max-w-md mx-auto">
                  No mobile devices are currently streaming. Devices will appear here automatically when they start sending frames.
              </p>
          </div>
      ) : (
          <div className="space-y-8">
              {Object.entries(devicesByVendor).map(([vendorId, vendorDevices]) => (
                  <div key={vendorId} className="bg-slate-50/50 rounded-2xl p-6 border border-slate-100">
                      <h3 className="text-lg font-bold text-slate-700 mb-4 flex items-center gap-2">
                          <span className="w-2 h-6 bg-blue-500 rounded-full"></span>
                          Vendor #{vendorId}
                          <span className="text-sm font-normal text-slate-400 ml-2">({vendorDevices.length} devices)</span>
                      </h3>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                          {vendorDevices.map(dev => (
                              <DeviceMonitor 
                                  key={`${dev.vendor_id}-${dev.device_id}`}
                                  vendorId={dev.vendor_id}
                                  deviceId={dev.device_id}
                                  deviceName={dev.device_name}
                              />
                          ))}
                      </div>
                  </div>
              ))}
          </div>
      )}
    </div>
  );
};

export default LiveFeed;