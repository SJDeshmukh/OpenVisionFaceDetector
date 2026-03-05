import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { useSocket } from '../context/SocketContext';
import { 
  Video, 
  User, 
  Clock, 
  MapPin, 
  Activity, 
  Wifi, 
  WifiOff,
  Maximize2
} from 'lucide-react';

const LiveAttendance = () => {
  const { user } = useAuth();
  const [liveImage, setLiveImage] = useState(null);
  const [logs, setLogs] = useState([]);
  const [devices, setDevices] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [isPublishing, setIsPublishing] = useState(false);
  const publishStreamRef = useRef(null);
  const publishIntervalRef = useRef(null);
  const publishVideoRef = useRef(null);
  const publishCanvasRef = useRef(null);
  const lastFrameTimeRef = useRef(0);

  // Clock
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Poll Stream
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(async () => {
      try {
        const url = new URL(`${API_URL}/stream/view`);
        if (selectedDeviceId && selectedDeviceId.trim() !== '') {
          url.searchParams.set('device_id', selectedDeviceId);
        }
        const res = await fetch(url.toString(), {
          headers: {
            'Authorization': `Bearer ${user.token}`
          }
        });
        const data = await res.json();
        if (data.status === 'online' && data.image) {
            setLiveImage(data.image.startsWith('data:') ? data.image : `data:image/jpeg;base64,${data.image}`);
            setIsConnected(true);
            lastFrameTimeRef.current = Date.now();
        } else {
            setIsConnected(false);
        }
      } catch (e) {
        setIsConnected(false);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [user, selectedDeviceId]);

  const stopPublishing = async () => {
    try {
      if (publishIntervalRef.current) {
        clearInterval(publishIntervalRef.current);
        publishIntervalRef.current = null;
      }
      if (publishVideoRef.current) {
        try {
          publishVideoRef.current.pause();
        } catch (e) {}
        publishVideoRef.current = null;
      }
      if (publishStreamRef.current) {
        try {
          publishStreamRef.current.getTracks().forEach(t => t.stop());
        } catch (e) {}
        publishStreamRef.current = null;
      }
    } finally {
      setIsPublishing(false);
    }
  };

  const startPublishing = async () => {
    if (!user?.token) return;
    try {
      if (isPublishing) return;
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      publishStreamRef.current = stream;
      const video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      await video.play();
      publishVideoRef.current = video;
      const canvas = document.createElement('canvas');
      publishCanvasRef.current = canvas;

      const deviceId = localStorage.getItem('web_device_id') || `web-${Date.now()}`;
      localStorage.setItem('web_device_id', deviceId);
      setIsPublishing(true);

      const tick = async () => {
        try {
          if (!publishVideoRef.current) return;
          const v = publishVideoRef.current;
          const w = 320;
          const h = Math.max(1, Math.round((v.videoHeight || 240) * (w / Math.max(1, v.videoWidth || 320))));
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(v, 0, 0, w, h);
          const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
          const base64 = dataUrl.split(',')[1];
          await fetch(`${API_URL}/stream/upload`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${user.token}`
            },
            body: JSON.stringify({
              vendor_id: user.vendor_id,
              device_id: deviceId,
              device_name: `Web ${deviceId.slice(-6)}`,
              image: base64
            })
          });
        } catch (e) {}
      };

      await tick();
      publishIntervalRef.current = setInterval(tick, 200);
    } catch (e) {
      await stopPublishing();
    }
  };

  useEffect(() => {
    return () => {
      stopPublishing();
    };
  }, []);

// Poll Logs + Socket push
const { socket } = useSocket();
useEffect(() => {
  if (!user || !socket) return;
  const handleFrameUpdate = (ev) => {
    if (!ev) return;
    if (String(ev.vendor_id) !== String(user.vendor_id)) return;
    if (!ev.image) return;
    setLiveImage(ev.image.startsWith('data:') ? ev.image : `data:image/jpeg;base64,${ev.image}`);
    setIsConnected(true);
    lastFrameTimeRef.current = Date.now();
  };
  socket.on('frame_update', handleFrameUpdate);
  const interval = setInterval(() => {
    if (lastFrameTimeRef.current && Date.now() - lastFrameTimeRef.current > 1500) {
      setIsConnected(false);
    }
  }, 500);
  return () => {
    clearInterval(interval);
    socket.off('frame_update', handleFrameUpdate);
  };
}, [user, socket]);

  const fetchLogs = async () => {
    try {
      const params = new URLSearchParams();
      params.append('limit', '50');
      if (selectedDeviceId && selectedDeviceId.trim() !== '') {
        params.append('device_id', selectedDeviceId);
      }
      const res = await axios.get(`${API_URL}/attendance?${params.toString()}`);
      const allLogs = res.data.attendance || [];
      const sorted = allLogs.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 50);
      setLogs(sorted);
    } catch (e) {
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [user, selectedDeviceId]);

  const fetchActiveDevices = async () => {
    try {
      const res = await axios.get(`${API_URL}/stream/active-devices`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const list = res?.data?.devices || [];
      setDevices(list);
      if (!selectedDeviceId && list.length > 0) {
        setSelectedDeviceId(list[0].device_id);
      }
    } catch (e) {}
  };

  useEffect(() => {
    if (!user) return;
    fetchActiveDevices();
    const t = setInterval(fetchActiveDevices, 5000);
    return () => clearInterval(t);
  }, [user]);

  useEffect(() => {
    if (!user || !socket) return;
    const handleAttendanceUpdated = (ev) => {
      if (String(ev.vendor_id) === String(user.vendor_id)) {
        setLogs((prev) => [ev, ...prev].slice(0, 50));
      }
    };
    socket.on('attendance_updated', handleAttendanceUpdated);
    return () => { 
      socket.off('attendance_updated', handleAttendanceUpdated); 
    };
  }, [user, socket]);

  const getStatusColor = (status, isLate) => {
    if (status === 'CHECK_OUT') return 'text-slate-500 bg-slate-100 border-slate-200';
    if (isLate === 1) return 'text-amber-600 bg-amber-50 border-amber-200';
    return 'text-green-600 bg-green-50 border-green-200';
  };

  return (
    <div className="h-[calc(100vh-9rem)] flex flex-col lg:flex-row gap-6 overflow-hidden">
      
      {/* Left Column: Live Feed */}
      <div className="flex-1 flex flex-col gap-6 min-h-0">
        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex-1 flex flex-col min-h-0">
          <div className="flex justify-between items-center mb-4 flex-shrink-0">
            <div>
              <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                <Video className="text-blue-500" size={24} />
                Live Camera Feed
              </h2>
              <p className="text-slate-500 text-sm">Real-time surveillance stream</p>
            </div>
            <div className="flex items-center gap-3">
              <select
                value={selectedDeviceId}
                onChange={(e) => setSelectedDeviceId(e.target.value)}
                className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-700"
              >
                {devices.length === 0 ? (
                  <option value="">No active devices</option>
                ) : devices.map(d => (
                  <option key={d.device_id} value={d.device_id}>{d.device_name || d.device_id}</option>
                ))}
              </select>
              <button
                onClick={() => (isPublishing ? stopPublishing() : startPublishing())}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border ${isPublishing ? 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100' : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'}`}
              >
                {isPublishing ? 'Stop Camera' : 'Use This Camera'}
              </button>
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium ${isConnected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                {isConnected ? <Wifi size={16} /> : <WifiOff size={16} />}
                {isConnected ? 'Online' : 'Offline'}
              </div>
            </div>
          </div>

          <div className="flex-1 bg-slate-900 rounded-xl overflow-hidden relative group min-h-0">
             {isConnected && liveImage ? (
               <img src={liveImage} alt="Live" className="w-full h-full object-contain" />
             ) : (
               <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-600">
                 <Video size={64} className="mb-4 opacity-50" />
                 <p>Waiting for camera connection...</p>
               </div>
             )}
             
             {/* Overlay Info */}
             <div className="absolute top-4 left-4 bg-black/50 backdrop-blur-md text-white px-3 py-1.5 rounded-lg text-sm font-mono flex items-center gap-2">
               <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
               LIVE
             </div>
             
             <div className="absolute top-4 right-4 bg-black/50 backdrop-blur-md text-white px-3 py-1.5 rounded-lg text-sm font-mono">
               {currentTime.toLocaleTimeString()}
             </div>
          </div>
        </div>
      </div>

      {/* Right Column: Real-time Events */}
      <div className="w-full lg:w-96 flex flex-col">
        <div className="bg-white p-0 rounded-2xl border border-slate-200 shadow-sm flex-1 flex flex-col overflow-hidden">
          <div className="p-6 border-b border-slate-100 bg-slate-50/50">
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <Activity className="text-blue-500" size={20} />
              Recent Activity
            </h2>
            <p className="text-slate-500 text-xs">Latest check-ins and check-outs</p>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
            {logs.length === 0 ? (
              <div className="text-center text-slate-400 py-10">
                <Clock size={40} className="mx-auto mb-3 opacity-50" />
                <p>No recent activity</p>
              </div>
            ) : (
              logs.map((log, idx) => (
                <div key={idx} className="flex items-start gap-3 p-3 rounded-xl hover:bg-slate-50 transition-colors border border-transparent hover:border-slate-100 animate-in fade-in slide-in-from-right-4 duration-300 fill-mode-backwards" style={{animationDelay: `${idx * 50}ms`}}>
                  <div className="relative">
                    {log.captured_image ? (
                      <img 
                        src={log.captured_image.startsWith('data:') ? log.captured_image : `data:image/jpeg;base64,${log.captured_image}`} 
                        className="w-12 h-12 rounded-full object-cover border-2 border-white shadow-sm"
                        alt={log.name}
                      />
                    ) : (
                      <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 border-2 border-white shadow-sm">
                        <User size={20} />
                      </div>
                    )}
                    <div className={`absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-2 border-white flex items-center justify-center ${log.status === 'CHECK_IN' ? 'bg-green-500' : 'bg-slate-500'}`}>
                      {log.status === 'CHECK_IN' ? <div className="w-2 h-2 bg-white rounded-full"></div> : <div className="w-2 h-2 bg-white/50 rounded-full"></div>}
                    </div>
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start">
                      <h3 className="font-semibold text-slate-800 truncate">{log.name}</h3>
                      <span className="text-xs text-slate-400 font-mono">{new Date(log.timestamp.replace(' ', 'T')).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'})}</span>
                    </div>
                    <p className="text-xs text-slate-500 mb-1.5">{log.department || 'Employee'}</p>
                    
                    <div className="flex flex-wrap gap-2">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium border ${getStatusColor(log.status, log.is_late)}`}>
                        {log.status === 'CHECK_IN' ? (log.is_late ? 'Late Entry' : 'On Time') : 'Check Out'}
                      </span>
                      {log.activity && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-blue-50 text-blue-600 border border-blue-100">
                          {log.activity}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

    </div>
  );
};

export default LiveAttendance;
