import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Shield, Clock, Search, Filter, AlertCircle, CheckCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';

const AuditLogs = () => {
  const { user } = useAuth();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [actionFilter, setActionFilter] = useState('all');

  useEffect(() => {
    fetchLogs();
  }, []);

  const fetchLogs = async () => {
    try {
      const response = await axios.get(`${API_URL}/admin/audit-logs`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setLogs(response.data.logs || []);
    } catch (error) {
      console.error("Error fetching audit logs:", error);
    } finally {
      setLoading(false);
    }
  };

  const filteredLogs = logs.filter(log => {
    const matchesSearch = 
      (log.actor_username?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (log.action?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (log.target_vendor_id?.toString() || '').includes(searchTerm);
      
    const matchesAction = actionFilter === 'all' || log.action === actionFilter;
    
    return matchesSearch && matchesAction;
  });

  const uniqueActions = [...new Set(logs.map(log => log.action))];

  return (
    <div className="space-y-6 p-6">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Audit Logs</h1>
          <p className="text-slate-500">Immutable record of all administrative actions.</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-slate-400" size={20} />
          <input
            type="text"
            placeholder="Search actor, action, or vendor ID..."
            className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
            <Filter size={20} className="text-slate-400" />
            <select
                className="border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
            >
                <option value="all">All Actions</option>
                {uniqueActions.map(action => (
                    <option key={action} value={action}>{action}</option>
                ))}
            </select>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Timestamp</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Actor</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Action</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Target Vendor</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
                <tr><td colSpan="5" className="text-center py-8">Loading logs...</td></tr>
            ) : filteredLogs.length === 0 ? (
                <tr><td colSpan="5" className="text-center py-8 text-slate-500">No logs found matching your criteria.</td></tr>
            ) : (
                filteredLogs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600 font-mono">
                    <div className="flex items-center">
                        <Clock size={14} className="mr-2 text-slate-400" />
                        {new Date(log.timestamp).toLocaleString()}
                    </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-slate-900">
                    <div className="flex items-center">
                        <Shield size={14} className="mr-2 text-blue-500" />
                        {log.actor_username}
                    </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-700 font-semibold">
                    {log.action}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
                     {log.target_vendor_id ? `Vendor #${log.target_vendor_id}` : '-'}
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-500 font-mono text-xs max-w-xs truncate">
                        {typeof log.details === 'string' ? log.details : JSON.stringify(log.details)}
                    </td>
                </tr>
                ))
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
};

export default AuditLogs;