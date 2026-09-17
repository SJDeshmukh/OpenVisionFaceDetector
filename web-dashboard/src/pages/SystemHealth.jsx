import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Activity, Database, Server, Zap } from 'lucide-react';

const SystemHealth = () => {
  const { user } = useAuth();
  const [health, setHealth] = useState(null);
  const [reportHealth, setReportHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reportError, setReportError] = useState(null);

  useEffect(() => {
    const fetchHealth = async () => {
      const headers = { Authorization: `Bearer ${user?.token}` };
      const [systemResult, reportResult] = await Promise.allSettled([
        axios.get(`${API_URL}/admin/system/health`, { headers }),
        axios.get(`${API_URL}/admin/hybrid-reports/health`, { headers }),
      ]);
      if (systemResult.status === 'fulfilled') {
        setHealth(systemResult.value.data);
      } else {
        setError(systemResult.reason?.response?.data?.error || systemResult.reason?.message);
      }
      if (reportResult.status === 'fulfilled') {
        setReportHealth(reportResult.value.data);
      } else if (reportResult.reason?.response?.data?.status) {
        // A degraded pipeline deliberately returns 503 with useful health data.
        setReportHealth(reportResult.reason.response.data);
      } else {
        setReportError(reportResult.reason?.response?.data?.error || reportResult.reason?.message);
      }
      setLoading(false);
    };
    fetchHealth();
  }, [user?.token]);

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
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm md:col-span-2 lg:col-span-3">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div className="flex items-center gap-2">
              <Activity size={18} className="text-violet-600" />
              <span className="font-semibold">Hybrid Report Delivery</span>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
              reportHealth?.status === 'healthy'
                ? 'bg-emerald-100 text-emerald-700'
                : reportHealth?.status === 'disabled'
                  ? 'bg-slate-100 text-slate-600'
                  : 'bg-amber-100 text-amber-700'
            }`}>
              {reportHealth?.status || (reportError ? 'unavailable' : 'unknown')}
            </span>
          </div>
          {reportError ? (
            <div className="text-sm text-red-600">{reportError}</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm text-slate-700">
              <div>
                <div>Backend: <span className="font-mono">{reportHealth?.backend || '-'}</span></div>
                <div className="mt-1">Canary vendors: <span className="font-mono">{
                  reportHealth?.full_rollout
                    ? 'All vendors'
                    : (reportHealth?.canary_vendor_ids || []).join(', ') || 'None'
                }</span></div>
              </div>
              <div>
                <div>Employee reports (24h): <span className="font-mono">{
                  JSON.stringify(reportHealth?.recent_24h?.employee || {})
                }</span></div>
                <div className="mt-1">Automated reports (24h): <span className="font-mono">{
                  JSON.stringify(reportHealth?.recent_24h?.automated || {})
                }</span></div>
              </div>
              <div>
                <div>Database queue: <span className="font-mono">{
                  reportHealth?.queues?.database_jobs?.visible ?? '-'
                } waiting</span></div>
                <div className="mt-1">Dead-letter queue: <span className="font-mono">{
                  reportHealth?.queues?.dead_letter?.visible ?? '-'
                } waiting</span></div>
              </div>
              {(reportHealth?.problems || []).length > 0 && (
                <ul className="md:col-span-3 list-disc pl-5 text-amber-700">
                  {reportHealth.problems.map((problem) => <li key={problem}>{problem}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SystemHealth;
