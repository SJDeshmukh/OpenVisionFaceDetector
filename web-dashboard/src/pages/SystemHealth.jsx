import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Activity, Database, Server, Zap } from 'lucide-react';

const SystemHealth = () => {
  const { user } = useAuth();
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await axios.get(`${API_URL}/admin/system/health`, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        setHealth(res.data);
      } catch (e) {
        setError(e.response?.data?.error || e.message);
      } finally {
        setLoading(false);
      }
    };
    fetchHealth();
  }, []);

  if (loading) return <div className="p-6">Loading system health…</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">System Health</h1>
        <p className="text-slate-500">Live snapshot of backend services.</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <Database size={18} className="text-indigo-600" />
            <span className="font-semibold">Database</span>
          </div>
          <div className="text-slate-700">Status: <span className="font-mono">{health?.db}</span></div>
          <div className="text-slate-700 mt-1">Active Sessions: <span className="font-mono">{health?.active_sessions}</span></div>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <Server size={18} className="text-green-600" />
            <span className="font-semibold">Redis</span>
          </div>
          <div className="text-slate-700">Status: <span className="font-mono">{health?.redis}</span></div>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={18} className="text-yellow-600" />
            <span className="font-semibold">Socket.IO</span>
          </div>
          <div className="text-slate-700">Mode: <span className="font-mono">{health?.socketio?.async_mode}</span></div>
          <div className="text-slate-700 mt-1">Ping Timeout: <span className="font-mono">{health?.socketio?.ping_timeout}</span></div>
          <div className="text-slate-700 mt-1">Ping Interval: <span className="font-mono">{health?.socketio?.ping_interval}</span></div>
        </div>
      </div>
    </div>
  );
};

export default SystemHealth;
