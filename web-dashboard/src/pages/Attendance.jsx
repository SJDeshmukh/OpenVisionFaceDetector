import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { 
  Search, 
  Filter, 
  Download,
  Calendar,
  MapPin,
  User,
  ChevronDown,
  ChevronRight,
  RefreshCw
} from 'lucide-react';
import { cn } from '../lib/utils';
import { API_URL } from '../config';

import { useSocket } from '../context/SocketContext';

const Attendance = () => {
  const { socket } = useSocket();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [expandedRow, setExpandedRow] = useState(null);

  const [filterOptions, setFilterOptions] = useState({ names: [], departments: [], designations: [], shifts: [], phones: [], dynamic_filters: {}, visible_standard_filters: {} });
  const [filters, setFilters] = useState({
    startDate: '',
    endDate: '',
    department: '',
    designation: '',
    shift: '',
    phone: '',
    name: '',
    deviceName: ''
  });
  const [deviceOptions, setDeviceOptions] = useState([]);
  const { user } = useAuth();
  const filtersRef = useRef(filters);
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  useEffect(() => {
    fetchFilters(filtersRef.current);
  }, []);

  useEffect(() => {
    fetchLogs(); // Trigger fetch on mount and filter change
    
    if (!socket) return;
    const handleAttendanceUpdated = (ev) => {
      // If filters are active, we might need a full refresh to be safe
      // but for "real time" we can just re-fetch the current view.
      if (String(ev.vendor_id) === String(user.vendor_id)) {
        fetchLogs(true);
        fetchFilters(filtersRef.current);
      }
    };
    const handlePersonsUpdated = (ev) => {
      if (String(ev.vendor_id) === String(user.vendor_id)) {
        fetchLogs(true);
        fetchFilters(filtersRef.current);
      }
    };
    socket.on('attendance_updated', handleAttendanceUpdated);
    socket.on('persons_updated', handlePersonsUpdated);
    
    return () => {
      socket.off('attendance_updated', handleAttendanceUpdated);
      socket.off('persons_updated', handlePersonsUpdated);
    };
  }, [filters, socket, user?.vendor_id]); // Re-create listener when filters change to ensure correct context if needed

  useEffect(() => {
    const t = setTimeout(() => fetchFilters(filtersRef.current), 250);
    return () => clearTimeout(t);
  }, [filters]);

  const fetchFilters = async (activeFilters) => {
    try {
      const params = new URLSearchParams();
      const f = activeFilters || {};
      Object.entries(filterOptions.dynamic_filters || {}).forEach(([key]) => {
        const v = f[key];
        if (v && String(v).trim() !== '') params.append(key, v);
      });
      const res = await axios.get(`${API_URL}/attendance/filters?${params.toString()}`);
      const nextOptions = res.data || {};
      setFilterOptions(nextOptions);
      const nextFilters = { ...filtersRef.current };
      Object.entries(nextOptions.dynamic_filters || {}).forEach(([key, cfg]) => {
        const allowed = new Set(((cfg && cfg.options) || []).map(String));
        if (nextFilters[key] && !allowed.has(String(nextFilters[key]))) nextFilters[key] = '';
      });
      const current = filtersRef.current;
      const changed = Object.keys(nextFilters).some(k => String(nextFilters[k] ?? '') !== String(current[k] ?? ''));
      if (changed) setFilters(nextFilters);
    } catch (error) {
      console.error("Error fetching filters:", error);
    }
  };

  const fetchLogs = async (isBackground = false) => {
    // Only set refreshing state for manual actions (not auto-refresh)
    if (!isBackground) setIsRefreshing(true);
    
    try {
      const params = new URLSearchParams();
      if (filters.startDate) params.append('start_date', filters.startDate);
      if (filters.endDate) params.append('end_date', filters.endDate);
      Object.entries(filterOptions.dynamic_filters || {}).forEach(([key, cfg]) => {
        const val = filters[key];
        if (val && String(val).trim() !== '') {
          params.append(key, val);
        }
      });

      if (filters.deviceName && String(filters.deviceName).trim() !== '') {
        params.append('device_name', filters.deviceName);
      }
      const response = await axios.get(`${API_URL}/attendance?${params.toString()}`);
      const list = response.data?.attendance || [];
      setLogs(list);
      try {
        const setNames = new Set();
        list.forEach(l => {
          const dn = l.device_name || '';
          if (dn && dn.trim() !== '') setNames.add(dn.trim());
        });
        setDeviceOptions(Array.from(setNames).sort());
      } catch (e) {}
      setError(null);
    } catch (error) {
      console.error("Error fetching logs:", error);
      if (error.response && error.response.status === 403) {
        setError(error.response.data.error || "Access Denied");
      }
    } finally {
      // Always turn off blocking loader (for initial load) and refreshing spinner
      setLoading(false);
      setIsRefreshing(false);
    }
  };

  const handleSearch = () => {
    fetchLogs();
  };

  const handleExport = () => {
    const params = new URLSearchParams();
    if (filters.startDate) params.append('start_date', filters.startDate);
    if (filters.endDate) params.append('end_date', filters.endDate);
    Object.entries(filterOptions.dynamic_filters || {}).forEach(([key, cfg]) => {
      const val = filters[key];
      if (val && String(val).trim() !== '') {
        params.append(key, val);
      }
    });
    
    // Add token for auth
    if (user?.token) params.append('token', user.token);
    
    window.location.href = `${API_URL}/reports/export?${params.toString()}`;
  };

  const getStatus = (log) => {
    // Backend provided late flag
    // Handle both integer 1/0 and boolean true/false or string "1"
    if (log.is_late === 1 || log.is_late === true || log.is_late === '1') {
      return { label: 'Late', color: 'bg-amber-100 text-amber-700' };
    }
    
    // Check Out
    if (log.status === 'CHECK_OUT') {
      return { label: 'Check Out', color: 'bg-slate-100 text-slate-700' };
    }

    // On Time Check In
    if (log.status === 'CHECK_IN') {
      return { label: 'On Time', color: 'bg-green-100 text-green-700' };
    }

    // Fallback based on timestamp if old data (legacy support)
    // Note: This fallback uses hardcoded 9:30 AM which might differ from DB logic
    // but useful for old records without is_late flag.
    const hour = new Date(log.timestamp).getHours();
    if (hour < 9) return { label: 'Early', color: 'bg-blue-100 text-blue-700' };
    if (hour === 9 && new Date(log.timestamp).getMinutes() <= 30) return { label: 'On Time', color: 'bg-green-100 text-green-700' };
    return { label: 'Late', color: 'bg-amber-100 text-amber-700' };
  };

  const showShiftColumn = user?.features?.includes('shifts') && !!(filterOptions.dynamic_filters && filterOptions.dynamic_filters.shift);

  const groupedLogs = logs.reduce((acc, log) => {
    const key = log.person_id ? `id:${log.person_id}` : `name:${log.vendor_id || 'unknown'}:${log.name}`;
    if (!acc[key]) {
      acc[key] = {
        key,
        name: log.name,
        person_id: log.person_id || null,
        logs: []
      };
    }
    acc[key].logs.push(log);
    return acc;
  }, {});

  // Convert to array and sort by latest timestamp
  const sortedGroups = Object.entries(groupedLogs)
    .map(([_, group]) => ({
      name: group.name,
      person_id: group.person_id,
      logs: group.logs.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)),
      latestLog: group.logs.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0]
    }))
    .sort((a, b) => new Date(b.latestLog.timestamp) - new Date(a.latestLog.timestamp));

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Attendance Logs</h1>
          <p className="text-slate-500">Track employee check-ins and movements.</p>
        </div>
        <div className="flex space-x-3">
           <div className="relative">
              <button 
                onClick={() => {
                   setFilters({
                    startDate: new Date().toISOString().split('T')[0],
                    endDate: new Date().toISOString().split('T')[0],
                    department: '',
                    designation: '',
                    shift: '',
                    phone: '',
                    name: ''
                  });
                  // Need to wait for state update or call fetch directly with new params. 
                  // Since setState is async, we'll just set it and let user click refresh or add a useEffect dependency if we wanted auto-refresh.
                  // For better UX, let's trigger a fetch with today's date directly or just update state and let user search.
                  // Or better, just set state and call fetchLogs() logic manually or use a separate effect.
                  // Let's keep it simple: Reset state.
                }}
                className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors"
              >
                <Calendar size={18} />
                <span>Today</span>
              </button>
           </div>
           <button 
             onClick={() => fetchLogs(false)}
             className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors"
           >
             <RefreshCw size={18} className={isRefreshing ? "animate-spin" : ""} />
             <span>Refresh</span>
           </button>
           <button 
             onClick={handleExport}
             className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors"
           >
             <Download size={18} />
             <span>Export</span>
           </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <span className="font-medium">{error}</span>
        </div>
      )}

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row gap-4 items-end md:items-center flex-wrap">
        <div className="w-full md:w-auto">
            <input 
              type="date" 
              value={filters.startDate}
              onChange={(e) => setFilters({...filters, startDate: e.target.value})}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            />
        </div>

        <div className="w-full md:w-auto">
            <input 
              type="date" 
              value={filters.endDate}
              onChange={(e) => setFilters({...filters, endDate: e.target.value})}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            />
        </div>

        <div className="w-full md:w-52">
            <select
              value={filters.deviceName || ''}
              onChange={(e) => setFilters({...filters, deviceName: e.target.value})}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            >
              <option value="">All Devices</option>
              {deviceOptions.map(opt => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
        </div>

        {Object.entries(filterOptions.dynamic_filters || {}).map(([key, cfg]) => (
          <div key={key} className="w-full md:w-44">
            <select
              value={filters[key] || ''}
              onChange={(e) => setFilters({...filters, [key]: e.target.value})}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            >
              <option value="">{`All ${cfg?.label || key}`}</option>
              {(cfg?.options || []).map(opt => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </div>
        ))}

        <button 
          onClick={handleSearch}
          className="p-2 bg-blue-600 text-white hover:bg-blue-700 transition-colors border border-transparent rounded-lg"
        >
          <Filter size={20} />
        </button>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="w-10 px-6 py-4"></th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Employee</th>
              {showShiftColumn && (
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Shift</th>
              )}
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Date</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Time</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Activity</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Confidence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan="8" className="p-8 text-center text-slate-500">Loading logs...</td></tr>
            ) : sortedGroups.length === 0 ? (
              <tr><td colSpan="8" className="p-8 text-center text-slate-500">No attendance records found.</td></tr>
            ) : (
              sortedGroups.map((group, idx) => {
                const log = group.latestLog; // Show latest log in summary
                const status = getStatus(log);
                const isExpanded = expandedRow === idx;
                
                return (
                  <>
                    <tr 
                      key={idx} 
                      className={cn(
                        "hover:bg-slate-50/80 transition-colors cursor-pointer",
                        isExpanded ? "bg-slate-50" : ""
                      )}
                      onClick={() => setExpandedRow(isExpanded ? null : idx)}
                    >
                      <td className="px-6 py-4">
                        {isExpanded ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center space-x-3">
                          {log.captured_image ? (
                            <img 
                              src={log.captured_image.startsWith('data:') ? log.captured_image : `data:image/jpeg;base64,${log.captured_image}`} 
                              alt="Captured" 
                              className="h-10 w-10 rounded-full object-cover border border-slate-200"
                            />
                          ) : (
                            <div className="h-10 w-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400">
                              <User size={20} />
                            </div>
                          )}
                          <div>
                             <span className="font-medium text-slate-900 block">{log.name}</span>
                             {user?.role === 'super_admin' && log.vendor_id && (
                               <span className="text-xs text-slate-400 block">Vendor #{log.vendor_id}</span>
                             )}
                             <span className="text-xs text-slate-500">{group.logs.length} Records</span>
                          </div>
                        </div>
                      </td>
                      {showShiftColumn && (
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                          {log.shift || <span className="text-slate-400 italic">None</span>}
                        </td>
                      )}
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                        {new Date(log.timestamp.replace(' ', 'T')).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-slate-700">
                        {new Date(log.timestamp.replace(' ', 'T')).toLocaleTimeString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                         <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100">
                           {log.activity || 'Work'}
                         </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
                          {status.label}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                        <div className="flex items-center space-x-2">
                          <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                            <div className="h-full bg-green-500 rounded-full" style={{width: '98%'}}></div>
                          </div>
                          <span>98%</span>
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-slate-50/50">
                        <td colSpan="8" className="px-6 py-4 pl-12">
                          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                             <table className="w-full text-left">
                                <thead className="bg-slate-50 border-b border-slate-100">
                                   <tr>
                                      <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Image</th>
                                      <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Time</th>
                                      <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Date</th>
                                      <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Status</th>
                                   </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-50">
                                   {group.logs.map((historyLog, hIdx) => (
                                      <tr key={hIdx} className="hover:bg-slate-50">
                                         <td className="px-4 py-2">
                                            {historyLog.captured_image ? (
                                              <img 
                                                src={historyLog.captured_image.startsWith('data:') ? historyLog.captured_image : `data:image/jpeg;base64,${historyLog.captured_image}`} 
                                                alt="Thumb" 
                                                className="h-12 w-12 rounded-md object-cover border border-slate-200"
                                              />
                                            ) : (
                                              <div className="h-12 w-12 rounded-md bg-slate-100 flex items-center justify-center text-slate-400">
                                                <User size={16} />
                                              </div>
                                            )}
                                         </td>
                                         <td className="px-4 py-2 text-sm font-mono text-slate-700">
                                            {new Date(historyLog.timestamp.replace(' ', 'T')).toLocaleTimeString()}
                                         </td>
                                         <td className="px-4 py-2 text-sm text-slate-600">
                                            {new Date(historyLog.timestamp.replace(' ', 'T')).toLocaleDateString()}
                                         </td>
                                         <td className="px-4 py-2">
                                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getStatus(historyLog).color}`}>
                                               {getStatus(historyLog).label}
                                               {historyLog.activity && historyLog.activity !== 'Work' && ` (${historyLog.activity})`}
                                            </span>
                                         </td>
                                      </tr>
                                   ))}
                                </tbody>
                             </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
};

export default Attendance;
