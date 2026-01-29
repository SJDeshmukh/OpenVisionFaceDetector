import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';
import { Monitor, Wifi, WifiOff, RefreshCw, Maximize2, X, Search, Camera, ChevronRight, LayoutGrid, Building2 } from 'lucide-react';

const DeviceMonitor = ({ vendorId, deviceId, deviceName }) => {
  const { user } = useAuth();
  const [image, setImage] = useState(null);
  const [status, setStatus] = useState('connecting'); // connecting, online, offline
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
            } else {
                setStatus('offline');
            }
        }
      } catch (error) {
        if (mounted) setStatus('error');
      }
    };

    fetchFrame();
    // Poll faster (1s) if fullscreen, slower (10s) if thumbnail to save bandwidth
    const interval = setInterval(fetchFrame, isFullscreen ? 1000 : 10000);

    return () => {
        mounted = false;
        clearInterval(interval);
    };
  }, [vendorId, deviceId, user, isFullscreen]);

  const toggleFullscreen = (e) => {
      e?.stopPropagation();
      setIsFullscreen(!isFullscreen);
  };

  // Fullscreen Modal View
  if (isFullscreen) {
      return (
        <div className="fixed inset-0 z-[100] bg-black flex flex-col items-center justify-center p-4">
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
    <div 
        onClick={() => setIsFullscreen(true)}
        className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col hover:shadow-md transition-all cursor-pointer group"
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
        <div className="flex items-center gap-2 min-w-0">
            <Monitor size={16} className="text-blue-500 shrink-0" />
            <span className="font-semibold text-slate-700 truncate text-sm" title={deviceName}>{deviceName}</span>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium ${status === 'online' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}`}>
            <div className={`w-1.5 h-1.5 rounded-full ${status === 'online' ? 'bg-green-500 animate-pulse' : 'bg-slate-400'}`} />
            {status === 'online' ? 'LIVE' : 'OFF'}
        </div>
      </div>

      {/* Video Area (Snapshot) */}
      <div className="relative aspect-video bg-slate-900 flex items-center justify-center overflow-hidden">
        {image && status === 'online' ? (
            <img 
                src={image} 
                alt="Live" 
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" 
            />
        ) : (
            <div className="text-slate-500 flex flex-col items-center">
                <WifiOff size={32} className="mb-2 opacity-50" />
                <span className="text-xs">Signal Lost</span>
            </div>
        )}
        
        {/* Overlay */}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
             <div className="opacity-0 group-hover:opacity-100 transform translate-y-2 group-hover:translate-y-0 transition-all duration-300 bg-white/20 backdrop-blur-sm text-white px-4 py-2 rounded-full flex items-center gap-2">
                <Maximize2 size={16} />
                <span className="text-sm font-medium">Click to View</span>
             </div>
        </div>
      </div>

      {/* Footer Info */}
      <div className="px-4 py-2 bg-white text-xs text-slate-500 flex justify-between items-center border-t border-slate-100">
        <span className="font-mono">{deviceId}</span>
        <span className="flex items-center gap-1"><Camera size={12} /> Cam 01</span>
      </div>
    </div>
  );
};

const LiveFeed = () => {
  const { user } = useAuth();
  const [devices, setDevices] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(new Date());
  
  // Selection State
  const [selectedVendorId, setSelectedVendorId] = useState(null);
  const [vendorSearch, setVendorSearch] = useState('');

  // Fetch Vendors (for SuperAdmin mapping)
  const fetchVendors = async () => {
    try {
        // Only fetch if we don't have them or to refresh
        const response = await axios.get(`${API_URL}/admin/vendors`, {
            headers: { Authorization: `Bearer ${user?.token}` }
        });
        setVendors(response.data.vendors || []);
    } catch (error) {
        console.error("Error fetching vendors:", error);
    }
  };

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
    fetchVendors();
    const interval = setInterval(fetchActiveDevices, 5000); // Refresh list every 5s
    return () => clearInterval(interval);
  }, []);

  // Compute Active Vendors from Devices List
  const activeVendorIds = useMemo(() => {
      const ids = new Set(devices.map(d => d.vendor_id));
      return Array.from(ids);
  }, [devices]);

  // Combine Active Vendors with Vendor Details
  const activeVendorsList = useMemo(() => {
      // If we have vendor details, use them. Otherwise create placeholders.
      const list = activeVendorIds.map(vid => {
          const details = vendors.find(v => v.id === vid);
          const deviceCount = devices.filter(d => d.vendor_id === vid).length;
          return {
              id: vid,
              name: details ? details.company_name : `Vendor #${vid}`,
              deviceCount
          };
      });
      
      // Filter by search
      if (!vendorSearch) return list;
      return list.filter(v => 
          v.name.toLowerCase().includes(vendorSearch.toLowerCase()) || 
          v.id.toString().includes(vendorSearch)
      );
  }, [activeVendorIds, vendors, devices, vendorSearch]);

  // Filter Devices for Selected Vendor
  const displayedDevices = useMemo(() => {
      if (!selectedVendorId) return [];
      return devices.filter(d => d.vendor_id === selectedVendorId);
  }, [selectedVendorId, devices]);

  // Auto-select first vendor if none selected and vendors exist (optional, but good UX)
  useEffect(() => {
      if (!selectedVendorId && activeVendorsList.length > 0) {
          setSelectedVendorId(activeVendorsList[0].id);
      }
  }, [activeVendorsList.length]); // Only run when list length changes (initially)

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col gap-6 p-6">
      
      {/* Header */}
      <div className="flex justify-between items-end flex-shrink-0">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <Monitor className="text-blue-600" />
            Global Live Feed
          </h1>
          <p className="text-slate-500 mt-1">Real-time surveillance from active terminals.</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-400">
            <RefreshCw size={14} className="animate-spin-slow" />
            Updated: {lastUpdated.toLocaleTimeString()}
        </div>
      </div>

      {/* Main Layout */}
      <div className="flex-1 flex gap-6 min-h-0">
          
          {/* Sidebar: Vendor List */}
          <div className="w-80 bg-white rounded-2xl border border-slate-200 shadow-sm flex flex-col overflow-hidden">
              <div className="p-4 border-b border-slate-100 bg-slate-50/50">
                  <h3 className="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                      <Building2 size={18} className="text-slate-400" />
                      Active Vendors
                  </h3>
                  <div className="relative">
                      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input 
                          type="text" 
                          placeholder="Search vendors..." 
                          className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                          value={vendorSearch}
                          onChange={(e) => setVendorSearch(e.target.value)}
                      />
                  </div>
              </div>
              
              <div className="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar">
                  {loading ? (
                      <div className="p-4 text-center text-slate-400 text-sm">Loading...</div>
                  ) : activeVendorsList.length === 0 ? (
                      <div className="p-8 text-center text-slate-400">
                          <WifiOff size={24} className="mx-auto mb-2 opacity-50" />
                          <p className="text-sm">No active vendors</p>
                      </div>
                  ) : (
                      activeVendorsList.map(vendor => (
                          <button
                              key={vendor.id}
                              onClick={() => setSelectedVendorId(vendor.id)}
                              className={`w-full text-left p-3 rounded-xl flex items-center justify-between transition-all ${
                                  selectedVendorId === vendor.id 
                                  ? 'bg-blue-50 text-blue-700 shadow-sm ring-1 ring-blue-200' 
                                  : 'hover:bg-slate-50 text-slate-600'
                              }`}
                          >
                              <div className="min-w-0">
                                  <div className="font-medium truncate">{vendor.name}</div>
                                  <div className="text-xs opacity-70 flex items-center gap-1">
                                      <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></div>
                                      {vendor.deviceCount} Device{vendor.deviceCount !== 1 ? 's' : ''} Online
                                  </div>
                              </div>
                              <ChevronRight size={16} className={`opacity-50 transition-transform ${selectedVendorId === vendor.id ? 'translate-x-1 text-blue-500' : ''}`} />
                          </button>
                      ))
                  )}
              </div>
          </div>

          {/* Main Area: Device Grid */}
          <div className="flex-1 bg-slate-50 rounded-2xl border border-slate-200 p-6 overflow-y-auto shadow-inner">
              {!selectedVendorId ? (
                  <div className="h-full flex flex-col items-center justify-center text-slate-400">
                      <LayoutGrid size={48} className="mb-4 opacity-20" />
                      <p className="text-lg font-medium text-slate-500">Select a vendor to view feeds</p>
                      <p className="text-sm">Choose from the list on the left</p>
                  </div>
              ) : displayedDevices.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-slate-400">
                      <WifiOff size={48} className="mb-4 opacity-20" />
                      <p className="text-lg font-medium text-slate-500">No active devices</p>
                      <p className="text-sm">This vendor has no devices currently streaming</p>
                  </div>
              ) : (
                  <div>
                      <div className="mb-6 flex items-center justify-between">
                          <div>
                              <h2 className="text-xl font-bold text-slate-800">
                                  {activeVendorsList.find(v => v.id === selectedVendorId)?.name}
                              </h2>
                              <p className="text-slate-500 text-sm">
                                  Showing {displayedDevices.length} active camera{displayedDevices.length !== 1 ? 's' : ''}
                              </p>
                          </div>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                          {displayedDevices.map(dev => (
                              <DeviceMonitor 
                                  key={`${dev.vendor_id}-${dev.device_id}`}
                                  vendorId={dev.vendor_id}
                                  deviceId={dev.device_id}
                                  deviceName={dev.device_name}
                              />
                          ))}
                      </div>
                  </div>
              )}
          </div>

      </div>
    </div>
  );
};

export default LiveFeed;
