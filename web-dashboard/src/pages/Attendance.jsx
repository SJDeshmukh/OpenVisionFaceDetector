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
  ChevronRight
} from 'lucide-react';
import { cn } from '../lib/utils';

const API_URL = 'http://127.0.0.1:5001/api';

const Attendance = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedRow, setExpandedRow] = useState(null);

  useEffect(() => {
    fetchLogs();
  }, []);

  const fetchLogs = async () => {
    try {
      const response = await axios.get(`${API_URL}/attendance`);
      setLogs(response.data.attendance || []);
      setLoading(false);
    } catch (error) {
      console.error("Error fetching logs:", error);
      setLoading(false);
    }
  };

  const getStatus = (timestamp) => {
    const hour = new Date(timestamp).getHours();
    if (hour < 9) return { label: 'Early', color: 'bg-blue-100 text-blue-700' };
    if (hour === 9 && new Date(timestamp).getMinutes() <= 30) return { label: 'On Time', color: 'bg-green-100 text-green-700' };
    return { label: 'Late', color: 'bg-amber-100 text-amber-700' };
  };

  // Real timeline data derived from actual logs
  const getTimeline = (currentLog) => {
    // Filter all logs for the same person on the same day
    const logDate = new Date(currentLog.timestamp).toDateString();
    
    return logs
      .filter(log => 
        log.name === currentLog.name && 
        new Date(log.timestamp).toDateString() === logDate
      )
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
      .map(log => ({
        time: new Date(log.timestamp).toLocaleTimeString(),
        event: log.status === 'CHECK_IN' ? 'Check In' : 'Check Out',
        location: 'Main Entrance' // Currently we assume single camera location
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
              <button className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors">
                <Calendar size={18} />
                <span>Today</span>
              </button>
           </div>
          <button className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors shadow-sm">
            <Download size={18} />
            <span>Export Report</span>
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-wrap gap-4 items-center">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
          <input 
            type="text" 
            placeholder="Search by employee..." 
            className="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
          />
        </div>
        
        <div className="w-40">
          <select className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20">
            <option>All Departments</option>
            <option>Engineering</option>
            <option>Sales</option>
          </select>
        </div>

        <div className="w-40">
          <select className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20">
            <option>All Statuses</option>
            <option>On Time</option>
            <option>Late</option>
            <option>Absent</option>
          </select>
        </div>

        <button className="p-2 text-slate-400 hover:text-slate-600 transition-colors border border-slate-200 rounded-lg">
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
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Check In</th>
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
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap font-medium text-slate-900">
                        {log.name}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                        {new Date(log.timestamp).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-slate-700">
                        {new Date(log.timestamp).toLocaleTimeString()}
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
                        <td colSpan="7" className="px-6 py-4 pl-20">
                          <div className="space-y-4">
                            <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider">Day Timeline</h4>
                            <div className="relative border-l-2 border-slate-200 ml-2 space-y-6 pb-2">
                              {getTimeline(log).map((event, i) => (
                                <div key={i} className="relative pl-6">
                                  <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-white border-2 border-blue-500"></div>
                                  <p className="text-sm font-semibold text-slate-800">{event.event}</p>
                                  <p className="text-xs text-slate-500 flex items-center mt-1">
                                    <Clock size={12} className="mr-1" /> {event.time}
                                    <span className="mx-2">•</span>
                                    <MapPin size={12} className="mr-1" /> {event.location}
                                  </p>
                                </div>
                              ))}
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