import { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  Search, 
  Filter, 
  Download,
  Calendar,
  Clock,
  MapPin,
  User,
  ChevronDown,
  ChevronRight,
  RefreshCw
} from 'lucide-react';
import { cn } from '../lib/utils';
import { API_URL } from '../config';

const Attendance = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [expandedRow, setExpandedRow] = useState(null);

  const [filterOptions, setFilterOptions] = useState({ departments: [], designations: [] });
  const [filters, setFilters] = useState({
    startDate: '',
    endDate: '',
    department: '',
    designation: '',
    name: ''
  });

  useEffect(() => {
    fetchFilters();
  }, []);

  useEffect(() => {
    fetchLogs(); // Trigger fetch on mount and filter change
    
    // Auto-refresh every 5 seconds using current filters
    const interval = setInterval(() => {
      fetchLogs(true); // isBackground = true (Silent refresh)
    }, 5000);
    
    return () => clearInterval(interval);
  }, [filters]); // Re-create interval when filters change to capture new state

  const fetchFilters = async () => {
    try {
      const res = await axios.get(`${API_URL}/reports/filters`);
      setFilterOptions({
        departments: res.data?.departments || [],
        designations: res.data?.designations || []
      });
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
      if (filters.department) params.append('department', filters.department);
      if (filters.designation) params.append('designation', filters.designation);
      if (filters.name) params.append('name', filters.name);

      const response = await axios.get(`${API_URL}/attendance?${params.toString()}`);
      setLogs(response.data?.attendance || []);
    } catch (error) {
      console.error("Error fetching logs:", error);
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
    if (filters.department) params.append('department', filters.department);
    if (filters.designation) params.append('designation', filters.designation);
    
    window.location.href = `${API_URL}/reports/export?${params.toString()}`;
  };

  const getStatus = (timestamp) => {
    const hour = new Date(timestamp).getHours();
    if (hour < 9) return { label: 'Early', color: 'bg-blue-100 text-blue-700' };
    if (hour === 9 && new Date(timestamp).getMinutes() <= 30) return { label: 'On Time', color: 'bg-green-100 text-green-700' };
    return { label: 'Late', color: 'bg-amber-100 text-amber-700' };
  };

  // Real timeline data derived from actual logs
  const getTimeline = (currentLog) => {
    // Helper to parse timestamp as UTC
    const parseTime = (ts) => new Date(ts.endsWith('Z') ? ts : ts + 'Z');

    // Filter all logs for the same person on the same day (in local time)
    const logDate = parseTime(currentLog.timestamp).toDateString();
    
    return logs
      .filter(log => 
        log.name === currentLog.name && 
        parseTime(log.timestamp).toDateString() === logDate
      )
      .sort((a, b) => parseTime(a.timestamp) - parseTime(b.timestamp))
      .map(log => ({
        time: parseTime(log.timestamp).toLocaleTimeString(),
        event: log.status === 'CHECK_IN' ? 'Check In' : 'Check Out',
        location: 'Main Entrance'
      }));
  };

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
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row gap-4 items-end md:items-center flex-wrap">
        <div className="relative flex-1 min-w-[200px] w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
          <input 
            type="text" 
            placeholder="Search by employee..." 
            value={filters.name}
            onChange={(e) => setFilters({...filters, name: e.target.value})}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            className="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
          />
        </div>
        
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
        
        <div className="w-full md:w-40">
          <select 
            value={filters.department}
            onChange={(e) => setFilters({...filters, department: e.target.value})}
            className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="">All Departments</option>
            {filterOptions?.departments?.map(dept => (
              <option key={dept} value={dept}>{dept}</option>
            ))}
          </select>
        </div>

        <div className="w-full md:w-40">
          <select 
            value={filters.designation}
            onChange={(e) => setFilters({...filters, designation: e.target.value})}
            className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          >
            <option value="">All Designations</option>
            {filterOptions?.designations?.map(desig => (
              <option key={desig} value={desig}>{desig}</option>
            ))}
          </select>
        </div>

        <button 
          onClick={handleSearch}
          className="p-2 bg-blue-600 text-white hover:bg-blue-700 transition-colors border border-transparent rounded-lg"
        >
          <Filter size={20} />
        </button>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="w-10 px-6 py-4"></th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Employee</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Date</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Time</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Camera</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Confidence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan="7" className="p-8 text-center text-slate-500">Loading logs...</td></tr>
            ) : logs.length === 0 ? (
              <tr><td colSpan="7" className="p-8 text-center text-slate-500">No attendance records found.</td></tr>
            ) : (
              logs.map((log, idx) => {
                const status = getStatus(log.timestamp);
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
                          <span className="font-medium text-slate-900">{log.name}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                        {/* Treat timestamp as UTC if it looks naive, or just let browser handle it.
                            If server sends "2026-01-24 10:00:00", browser sees it as local.
                            If user is in same timezone as server, it's fine.
                            If user is ahead (IST vs UTC), 10:00 UTC becomes 10:00 IST (wrong).
                            We can force it to be treated as UTC by appending 'Z' if missing. */}
                        {new Date(log.timestamp.endsWith('Z') ? log.timestamp : log.timestamp + 'Z').toLocaleDateString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-slate-700">
                        {new Date(log.timestamp.endsWith('Z') ? log.timestamp : log.timestamp + 'Z').toLocaleTimeString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                        <div className="flex items-center space-x-1">
                          <MapPin size={14} className="text-slate-400" />
                          <span>Main Entrance</span>
                        </div>
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
                        <td colSpan="8" className="px-6 py-4 pl-20">
                          <div className="flex gap-6">
                             {/* Captured Frame */}
                             <div className="flex flex-col gap-2">
                                <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider">Captured Frame</h4>
                                {log.captured_image ? (
                                  <img 
                                    src={log.captured_image.startsWith('data:') ? log.captured_image : `data:image/jpeg;base64,${log.captured_image}`} 
                                    alt="Captured Event" 
                                    className="h-32 w-32 rounded-lg object-cover border border-slate-200 shadow-sm"
                                  />
                                ) : (
                                  <div className="h-32 w-32 rounded-lg bg-slate-100 flex items-center justify-center text-slate-400 border border-slate-200">
                                    <span className="text-xs">No Image</span>
                                  </div>
                                )}
                             </div>

                             {/* Timeline */}
                             <div className="flex-1 space-y-4">
                                <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider">Day Timeline</h4>
                                <div className="relative border-l-2 border-slate-200 ml-2 space-y-6 pb-2">
                                  {getTimeline(log).map((event, i) => (
                                    <div key={i} className="relative pl-6">
                                      <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-white border-2 border-blue-500"></div>
                                      <p className="text-sm font-semibold text-slate-800">{event.event}</p>
                                      <p className="text-xs text-slate-500 flex items-center mt-1">
                                        <Clock size={12} className="mr-1" />
                                        {event.time}
                                      </p>
                                    </div>
                                  ))}
                                </div>
                             </div>
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
  );
};

export default Attendance;