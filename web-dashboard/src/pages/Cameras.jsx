import { API_URL } from '../config';
import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Plus, 
  Wifi, 
  WifiOff, 
  RefreshCw, 
  Settings, 
  Trash2,
  Video
} from 'lucide-react';

const Cameras = () => {
  const { user } = useAuth();
  const [cameras, setCameras] = useState([]);
  const [liveImages, setLiveImages] = useState({});
  const camerasRef = useRef([]);
  useEffect(() => {
    camerasRef.current = cameras;
  }, [cameras]);

  const fetchActiveDevices = async () => {
    if (!user?.token) return;
    try {
      const res = await fetch(`${API_URL}/stream/active-devices`, {
        headers: { Authorization: `Bearer ${user.token}` }
      });
      const data = await res.json();
      const devices = Array.isArray(data.devices) ? data.devices : [];
      setCameras(devices.map(d => ({
        id: d.device_id,
        vendor_id: d.vendor_id,
        device_id: d.device_id,
        name: d.device_name || `Device ${d.device_id}`,
        location: 'Terminal',
        status: 'Online',
        lastActive: d.last_seen ? new Date(d.last_seen).toLocaleString() : 'Live Now',
        ip: d.source_ip || 'Unknown'
      })));
    } catch (e) {
      setCameras([]);
    }
  };

  useEffect(() => {
    fetchActiveDevices();
    const interval = setInterval(fetchActiveDevices, 5000);
    return () => clearInterval(interval);
  }, [user?.token]);

  // Poll for live frames (1 FPS)
  useEffect(() => {
    const interval = setInterval(async () => {
      const currentCameras = camerasRef.current || [];
      if (!user?.token || currentCameras.length === 0) return;
      await Promise.all(currentCameras.map(async (cam) => {
        try {
          const response = await fetch(`${API_URL}/stream/view?device_id=${encodeURIComponent(cam.device_id)}`, {
            headers: { Authorization: `Bearer ${user.token}` }
          });
          const data = await response.json();
          if (data.status === 'online' && data.image) {
            const imgData = data.image.startsWith('data:image')
              ? data.image
              : `data:image/jpeg;base64,${data.image}`;
            setLiveImages(prev => ({ ...prev, [cam.device_id]: imgData }));
            setCameras(prev => prev.map(c => c.device_id === cam.device_id ? {
              ...c,
              status: 'Online',
              lastActive: data.timestamp ? new Date(data.timestamp).toLocaleString() : 'Live Now',
              ip: data.source_ip || c.ip
            } : c));
          } else {
            setCameras(prev => prev.map(c => c.device_id === cam.device_id ? { ...c, status: 'Offline' } : c));
          }
        } catch (error) {
          setCameras(prev => prev.map(c => c.device_id === cam.device_id ? { ...c, status: 'Offline' } : c));
        }
      }));
    }, 1000); // 1 FPS polling

    return () => clearInterval(interval);
  }, [user?.token]);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Camera Management</h1>
          <p className="text-slate-500">Monitor and configure surveillance feeds.</p>
        </div>
        {/* Disable adding cameras as we only support single kiosk for now */}
        <button disabled className="flex items-center space-x-2 px-4 py-2 bg-slate-100 text-slate-400 rounded-lg font-medium cursor-not-allowed">
          <Plus size={18} />
          <span>Add Camera</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {cameras.map((cam) => (
          <div key={cam.id} className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden group">
            {/* Camera Preview Placeholder */}
            <div className="h-48 bg-slate-900 relative flex items-center justify-center overflow-hidden">
              {cam.status === 'Online' ? (
                 <div className="absolute inset-0 bg-slate-800 flex items-center justify-center">
                    {/* Live Video Feed */}
                    {liveImages[cam.device_id] ? (
                        <img src={liveImages[cam.device_id]} alt="Live Stream" className="w-full h-full object-cover" />
                    ) : (
                        <Video size={48} className="text-slate-600" />
                    )}
                    
                    <div className="absolute top-3 left-3 bg-black/60 px-2 py-1 rounded text-xs text-white font-mono flex items-center">
                      <div className="w-2 h-2 bg-red-500 rounded-full mr-2 animate-pulse"></div>
                      REC
                    </div>
                 </div>
              ) : (
                <div className="text-slate-500 flex flex-col items-center">
                  <WifiOff size={32} className="mb-2" />
                  <span className="text-sm font-medium">Signal Lost</span>
                </div>
              )}
            </div>

            <div className="p-5">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 className="text-lg font-bold text-slate-800">{cam.name}</h3>
                  <p className="text-sm text-slate-500">{cam.location}</p>
                </div>
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  cam.status === 'Online' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                }`}>
                  {cam.status === 'Online' ? <Wifi size={12} className="mr-1" /> : <WifiOff size={12} className="mr-1" />}
                  {cam.status}
                </span>
              </div>

              <div className="flex items-center justify-between text-xs text-slate-400 mb-6">
                <span>IP: {cam.ip}</span>
                <span>Last active: {cam.lastActive}</span>
              </div>

              <div className="flex space-x-2 border-t border-slate-100 pt-4">
                <button className="flex-1 py-2 bg-slate-50 text-slate-600 rounded-lg text-sm font-medium hover:bg-slate-100 transition-colors">
                  View Feed
                </button>
                <button className="p-2 text-slate-400 hover:text-blue-600 transition-colors rounded-lg hover:bg-slate-50">
                  <Settings size={18} />
                </button>
                <button className="p-2 text-slate-400 hover:text-red-600 transition-colors rounded-lg hover:bg-slate-50">
                  <Trash2 size={18} />
                </button>
              </div>
            </div>
          </div>
        ))}

        {/* Add New Camera Card */}
        <button className="border-2 border-dashed border-slate-200 rounded-xl flex flex-col items-center justify-center p-6 text-slate-400 hover:border-blue-400 hover:text-blue-500 transition-all group h-full min-h-[300px]">
          <div className="w-12 h-12 rounded-full bg-slate-50 group-hover:bg-blue-50 flex items-center justify-center mb-4 transition-colors">
            <Plus size={24} />
          </div>
          <span className="font-medium">Connect New Camera</span>
        </button>
      </div>
    </div>
  );
};

export default Cameras;
