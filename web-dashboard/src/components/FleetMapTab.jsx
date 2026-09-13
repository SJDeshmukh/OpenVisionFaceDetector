import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Shield, Battery, Wifi, WifiOff, MapPin, AlertTriangle, RefreshCw, Search, Filter, Navigation } from 'lucide-react';
import { API_URL } from '../config';
import { useSocket } from '../context/SocketContext';

const loadLeaflet = () => {
  return new Promise((resolve) => {
    if (window.L) {
      resolve(window.L);
      return;
    }
    const existingLink = document.getElementById('leaflet-css');
    if (!existingLink) {
      const link = document.createElement('link');
      link.id = 'leaflet-css';
      link.rel = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(link);
    }

    const existingScript = document.getElementById('leaflet-js');
    if (existingScript) {
      if (window.L) {
        resolve(window.L);
      } else {
        existingScript.addEventListener('load', () => resolve(window.L));
      }
      return;
    }

    const script = document.createElement('script');
    script.id = 'leaflet-js';
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.onload = () => resolve(window.L);
    document.head.appendChild(script);
  });
};

const FleetMapTab = ({ userToken }) => {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all'); // 'all' | 'online' | 'outside' | 'low_battery'
  const [search, setSearch] = useState('');
  const [selectedDevice, setSelectedDevice] = useState(null);

  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersRef = useRef({});
  const circlesRef = useRef({});
  const { socket } = useSocket() || {};

  const parseNum = (val) => {
    if (val === null || val === undefined || val === '') return null;
    const n = Number(val);
    return isNaN(n) ? null : n;
  };

  const fetchTelemetry = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/admin/fleet/telemetry`, {
        headers: { Authorization: `Bearer ${userToken}` }
      });
      const rawDevices = res.data.devices || [];
      const normalized = rawDevices.map(dev => {
        const lat = parseNum(dev.latitude ?? dev.last_lat);
        const lng = parseNum(dev.longitude ?? dev.last_lng);
        const gLat = parseNum(dev.geofence_latitude ?? dev.geofence_lat);
        const gLng = parseNum(dev.geofence_longitude ?? dev.geofence_lng);
        const gRadius = parseNum(dev.geofence_radius);
        return {
          ...dev,
          latitude: lat,
          longitude: lng,
          last_lat: lat,
          last_lng: lng,
          geofence_latitude: gLat,
          geofence_longitude: gLng,
          geofence_lat: gLat,
          geofence_lng: gLng,
          geofence_radius: gRadius,
          vendor_name: dev.vendor_name || dev.company_name || `Vendor ${dev.vendor_id || ''}`
        };
      });
      setDevices(normalized);
    } catch (e) {
      console.error("Failed to fetch fleet telemetry:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTelemetry();
  }, [userToken]);

  // Real-time socket updates
  useEffect(() => {
    if (!socket || typeof socket.on !== 'function') return;
    const handleHealthUpdate = (data) => {
      setDevices(prev => prev.map(d => {
        if (d.device_id === data.device_id) {
          const lat = parseNum(data.latitude ?? data.last_lat ?? d.latitude);
          const lng = parseNum(data.longitude ?? data.last_lng ?? d.longitude);
          return {
            ...d,
            battery_level: data.battery_level ?? d.battery_level,
            last_active_at: data.last_active_at || new Date().toISOString(),
            is_online: true,
            latitude: lat,
            longitude: lng,
            last_lat: lat,
            last_lng: lng,
            geofence_status: data.geofence_status ?? d.geofence_status,
            distance_meters: data.distance_meters ?? d.distance_meters
          };
        }
        return d;
      }));
    };

    socket.on('device_health_update', handleHealthUpdate);
    return () => {
      if (typeof socket.off === 'function') {
        socket.off('device_health_update', handleHealthUpdate);
      }
    };
  }, [socket]);

  // Initialize and update Leaflet Map
  useEffect(() => {
    let isMounted = true;
    loadLeaflet().then((L) => {
      if (!isMounted || !mapContainerRef.current) return;

      if (!mapInstanceRef.current) {
        const map = L.map(mapContainerRef.current).setView([20.5937, 78.9629], 5); // India center default
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '© OpenStreetMap contributors'
        }).addTo(map);
        mapInstanceRef.current = map;
      }

      const map = mapInstanceRef.current;

      // Invalidate size in case tab or flex layout changed
      setTimeout(() => {
        if (isMounted && mapInstanceRef.current) {
          try {
            mapInstanceRef.current.invalidateSize();
          } catch (_) {}
        }
      }, 250);

      // Clear existing markers & circles
      Object.values(markersRef.current).forEach(m => m.remove());
      Object.values(circlesRef.current).forEach(c => c.remove());
      markersRef.current = {};
      circlesRef.current = {};

      const bounds = [];

      devices.forEach(dev => {
        const lat = dev.latitude != null ? Number(dev.latitude) : null;
        const lng = dev.longitude != null ? Number(dev.longitude) : null;
        const gLat = dev.geofence_latitude != null ? Number(dev.geofence_latitude) : null;
        const gLng = dev.geofence_longitude != null ? Number(dev.geofence_longitude) : null;
        const gRadius = dev.geofence_radius != null ? Number(dev.geofence_radius) : null;
        const vendorName = dev.vendor_name || dev.company_name || `Vendor ${dev.vendor_id || ''}`;

        // Render geofence anchor circle if available
        if (gLat != null && gLng != null && gRadius != null && !isNaN(gLat) && !isNaN(gLng) && gRadius > 0) {
          const circleKey = `${dev.vendor_id}_${gLat}_${gLng}`;
          if (!circlesRef.current[circleKey]) {
            const circle = L.circle([gLat, gLng], {
              radius: gRadius,
              color: '#6366f1',
              fillColor: '#818cf8',
              fillOpacity: 0.12,
              weight: 2,
              dashArray: '4, 4'
            }).addTo(map);
            circle.bindTooltip(`Geofence: ${vendorName} (${gRadius}m)`, { permanent: false });
            circlesRef.current[circleKey] = circle;
            bounds.push([gLat, gLng]);
          }
        }

        // Render device marker if coordinates exist
        if (lat != null && lng != null && !isNaN(lat) && !isNaN(lng)) {
          bounds.push([lat, lng]);

          let pulseColor = '#94a3b8'; // gray offline
          let statusText = 'Offline';
          if (dev.is_online) {
            if (dev.geofence_status === 'outside') {
              pulseColor = '#ef4444'; // red outside
              statusText = 'Outside Geofence';
            } else if (dev.geofence_status === 'inside') {
              pulseColor = '#22c55e'; // green inside
              statusText = 'Online (Inside)';
            } else {
              pulseColor = '#f59e0b'; // amber no geofence
              statusText = 'Online';
            }
          }

          const pulseHtml = `
            <div style="position: relative; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;">
              ${dev.is_online ? `<div style="position: absolute; width: 30px; height: 30px; border-radius: 50%; background: ${pulseColor}; opacity: 0.4; animation: ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;"></div>` : ''}
              <div style="width: 18px; height: 18px; border-radius: 50%; background: ${pulseColor}; border: 2.5px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.35);"></div>
            </div>
          `;

          const customIcon = L.divIcon({
            html: pulseHtml,
            className: 'custom-fleet-marker',
            iconSize: [32, 32],
            iconAnchor: [16, 16],
            popupAnchor: [0, -16]
          });

          const marker = L.marker([lat, lng], { icon: customIcon }).addTo(map);

          const popupContent = `
            <div style="font-family: sans-serif; min-width: 190px; padding: 4px;">
              <div style="font-weight: bold; font-size: 14px; color: #1e293b; margin-bottom: 2px;">${dev.device_name || 'Kiosk'}</div>
              <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">Vendor: <b>${vendorName}</b></div>
              <div style="display: flex; align-items: center; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                <span style="color: #64748b;">Status:</span>
                <span style="font-weight: bold; color: ${pulseColor};">${statusText}</span>
              </div>
              <div style="display: flex; align-items: center; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                <span style="color: #64748b;">Battery:</span>
                <span style="font-weight: bold; color: ${(dev.battery_level ?? 100) < 20 ? '#ef4444' : '#22c55e'};">${dev.battery_level != null ? dev.battery_level : '--'}%</span>
              </div>
              <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; margin-bottom: 4px; color: #475569;">
                <span>Coords:</span>
                <span style="font-family: monospace; font-weight: bold;">${lat.toFixed(5)}, ${lng.toFixed(5)}</span>
              </div>
              ${dev.distance_meters != null ? `
                <div style="display: flex; align-items: center; justify-content: space-between; font-size: 12px; margin-bottom: 4px;">
                  <span style="color: #64748b;">Distance:</span>
                  <span style="font-weight: bold; color: #334155;">${Math.round(dev.distance_meters)}m</span>
                </div>
              ` : ''}
              <div style="font-size: 10px; color: #94a3b8; margin-top: 6px;">Last active: ${dev.last_active_at ? new Date(dev.last_active_at).toLocaleTimeString() : 'Never'}</div>
            </div>
          `;

          marker.bindPopup(popupContent);
          markersRef.current[dev.device_id] = marker;
        }
      });

      if (bounds.length > 0 && !selectedDevice) {
        if (bounds.length === 1) {
          map.setView(bounds[0], 16);
        } else {
          map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
        }
      }
    });

    return () => {
      isMounted = false;
    };
  }, [devices]);

  const handleLocateDevice = (dev) => {
    setSelectedDevice(dev);
    const lat = dev.latitude != null ? Number(dev.latitude) : null;
    const lng = dev.longitude != null ? Number(dev.longitude) : null;
    if (!mapInstanceRef.current || lat == null || lng == null || isNaN(lat) || isNaN(lng)) return;
    mapInstanceRef.current.setView([lat, lng], 17, { animate: true });
    const marker = markersRef.current[dev.device_id];
    if (marker) {
      setTimeout(() => marker.openPopup(), 300);
    }
  };

  const filteredDevices = devices.filter(dev => {
    const matchesSearch = !search ||
      dev.device_name?.toLowerCase().includes(search.toLowerCase()) ||
      dev.vendor_name?.toLowerCase().includes(search.toLowerCase()) ||
      dev.device_id?.toLowerCase().includes(search.toLowerCase());

    if (!matchesSearch) return false;

    if (filter === 'online') return dev.is_online;
    if (filter === 'outside') return dev.geofence_status === 'outside';
    if (filter === 'low_battery') return (dev.battery_level ?? 100) < 20;
    return true;
  });

  const totalCount = devices.length;
  const onlineCount = devices.filter(d => d.is_online).length;
  const outsideCount = devices.filter(d => d.geofence_status === 'outside').length;
  const lowBatteryCount = devices.filter(d => (d.battery_level ?? 100) < 20).length;

  return (
    <div className="space-y-6">
      <style>
        {`
          @keyframes ping {
            75%, 100% {
              transform: scale(2);
              opacity: 0;
            }
          }
          .custom-fleet-marker {
            background: transparent !important;
            border: none !important;
          }
        `}
      </style>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Kiosks</span>
            <Shield size={18} className="text-indigo-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900 mt-2">{totalCount}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-emerald-600 uppercase tracking-wider">Online Pulse</span>
            <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></div>
          </div>
          <div className="text-2xl font-bold text-emerald-600 mt-2">{onlineCount}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-red-600 uppercase tracking-wider">Outside Geofence</span>
            <AlertTriangle size={18} className="text-red-500" />
          </div>
          <div className="text-2xl font-bold text-red-600 mt-2">{outsideCount}</div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-amber-600 uppercase tracking-wider">Low Battery (&lt;20%)</span>
            <Battery size={18} className="text-amber-500" />
          </div>
          <div className="text-2xl font-bold text-amber-600 mt-2">{lowBatteryCount}</div>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-wrap gap-4 items-center justify-between">
        <div className="flex-1 min-w-[240px] relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-slate-400" size={18} />
          <input
            type="text"
            placeholder="Search kiosk, vendor, or place name..."
            className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-2">
          <Filter size={16} className="text-slate-400" />
          {[['all', 'All'], ['online', 'Online'], ['outside', 'Outside Geofence'], ['low_battery', 'Low Battery']].map(([val, label]) => (
            <button
              key={val}
              onClick={() => setFilter(val)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                filter === val
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
          <button
            onClick={fetchTelemetry}
            className="p-2 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 transition"
            title="Refresh Telemetry"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Map & Sidebar Split */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Interactive Map */}
        <div className="lg:col-span-2 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col h-[600px] relative">
          <div className="p-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MapPin size={16} className="text-indigo-600" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-700">Live Kiosk Fleet Map</span>
            </div>
            <div className="flex items-center gap-4 text-xs text-slate-500">
              <span className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-emerald-500"></div> Inside</span>
              <span className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-red-500"></div> Outside</span>
              <span className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-slate-400"></div> Offline</span>
            </div>
          </div>
          <div ref={mapContainerRef} className="flex-1 w-full h-full z-10" />
        </div>

        {/* Kiosk Sidebar List */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm flex flex-col h-[600px]">
          <div className="p-4 border-b border-slate-100 flex items-center justify-between">
            <h3 className="font-bold text-slate-800 text-sm">Active Kiosks ({filteredDevices.length})</h3>
            <span className="text-xs text-slate-400">Auto-refreshed</span>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-slate-100 p-2">
            {filteredDevices.length === 0 ? (
              <div className="text-center py-16 text-slate-400">
                <MapPin size={32} className="mx-auto mb-2 opacity-20" />
                <p className="text-xs">No kiosks matching current filters.</p>
              </div>
            ) : (
              filteredDevices.map(dev => {
                const isSelected = selectedDevice?.device_id === dev.device_id;
                const battery = dev.battery_level ?? 0;
                return (
                  <div
                    key={dev.device_id}
                    onClick={() => handleLocateDevice(dev)}
                    className={`p-3 rounded-xl cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-indigo-50 border border-indigo-200'
                        : 'hover:bg-slate-50 border border-transparent'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="font-bold text-sm text-slate-800 flex items-center gap-2">
                          <div className={`w-2 h-2 rounded-full ${dev.is_online ? (dev.geofence_status === 'outside' ? 'bg-red-500 animate-ping' : 'bg-emerald-500') : 'bg-slate-300'}`}></div>
                          {dev.device_name || `Mobile ${dev.device_id?.substring(0, 6)}`}
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">{dev.vendor_name}</div>
                      </div>

                      <div className="flex items-center gap-1.5 text-xs font-bold">
                        <Battery size={14} className={battery < 20 ? "text-red-500" : battery < 50 ? "text-amber-500" : "text-emerald-500"} />
                        <span className={battery < 20 ? "text-red-600" : "text-slate-700"}>{dev.battery_level != null ? `${dev.battery_level}%` : '--'}</span>
                      </div>
                    </div>

                    <div className="mt-3 flex items-center justify-between text-xs">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {dev.geofence_status === 'outside' && (
                          <span className="px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-semibold text-[10px]">
                            OUTSIDE ({Math.round(dev.distance_meters || 0)}m)
                          </span>
                        )}
                        {dev.geofence_status === 'inside' && (
                          <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-semibold text-[10px]">
                            INSIDE GEOFENCE
                          </span>
                        )}
                        {dev.geofence_status === 'no_gps' && (
                          <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-semibold text-[10px]">
                            NO GPS FIX
                          </span>
                        )}
                        {dev.geofence_status === 'disabled' && (
                          <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 font-medium text-[10px]">
                            NO GEOFENCE
                          </span>
                        )}
                        {dev.latitude != null && dev.longitude != null ? (
                          <span className="text-[10px] text-slate-400 font-mono">
                            {Number(dev.latitude).toFixed(3)}, {Number(dev.longitude).toFixed(3)}
                          </span>
                        ) : (
                          <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded italic">
                            No GPS coords
                          </span>
                        )}
                      </div>

                      {dev.latitude != null && dev.longitude != null && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleLocateDevice(dev);
                          }}
                          className="flex items-center gap-1 text-indigo-600 hover:text-indigo-800 font-semibold text-xs ml-2 shrink-0 bg-indigo-50 hover:bg-indigo-100 px-2 py-1 rounded transition-colors"
                        >
                          <Navigation size={12} /> Locate
                        </button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default FleetMapTab;
