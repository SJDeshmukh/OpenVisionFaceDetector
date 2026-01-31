import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Server, ListOrdered, Activity, RefreshCcw } from 'lucide-react';
import { Shield } from 'lucide-react';

const JobsDashboard = () => {
  const { user } = useAuth();
  const [queues, setQueues] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [events, setEvents] = useState([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [queueFilter, setQueueFilter] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const [metricType, setMetricType] = useState('latency');
  const [bucket, setBucket] = useState('minute');
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [metrics, setMetrics] = useState(null);

  const fetchQueues = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/admin/system/queues`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setQueues(res.data);
      setError(null);
    } catch (e) {
      setError(e.response?.data?.error || e.message);
    } finally {
      setLoading(false);
    }
  };
  const fetchEvents = async () => {
    try {
      const res = await axios.get(`${API_URL}/admin/jobs/events`, {
        params: { status: statusFilter || undefined, queue: queueFilter || undefined, name: nameFilter || undefined, limit: 100 },
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setEvents(res.data.events || []);
    } catch (e) {}
  };
  const fetchMetrics = async () => {
    try {
      const res = await axios.get(`${API_URL}/admin/jobs/metrics`, {
        params: { window_minutes: windowMinutes, bucket },
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setMetrics(res.data);
    } catch (e) {}
  };

  useEffect(() => {
    fetchQueues();
    fetchEvents();
    fetchMetrics();
    const t = setInterval(fetchQueues, 5000);
    const e = setInterval(fetchEvents, 5000);
    const m = setInterval(fetchMetrics, 10000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { fetchEvents(); }, [statusFilter, queueFilter, nameFilter]);
  useEffect(() => { fetchMetrics(); }, [bucket, windowMinutes]);

  if (loading) return <div className="p-6">Loading jobs…</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  const totalActive = Object.values(queues?.active || {}).reduce((acc, arr) => acc + (Array.isArray(arr) ? arr.length : 0), 0);
  const totalReserved = Object.values(queues?.reserved || {}).reduce((acc, arr) => acc + (Array.isArray(arr) ? arr.length : 0), 0);
  const totalScheduled = Object.values(queues?.scheduled || {}).reduce((acc, arr) => acc + (Array.isArray(arr) ? arr.length : 0), 0);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Background Jobs</h1>
          <p className="text-slate-500">Celery queues and worker activity</p>
        </div>
        <button onClick={fetchQueues} className="flex items-center gap-2 text-xs bg-slate-100 px-3 py-1.5 rounded border border-slate-200">
          <RefreshCcw size={14}/> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <Server size={18} className="text-indigo-600" />
            <span className="font-semibold">Broker</span>
          </div>
          <div className="text-slate-700">Type: <span className="font-mono">{queues?.broker}</span></div>
          <div className="text-slate-700 mt-1">Workers: <span className="font-mono">{queues?.workers?.length || 0}</span></div>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="text-slate-500 text-sm mb-1">Active</div>
          <div className="text-3xl font-bold text-green-600">{totalActive}</div>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="text-slate-500 text-sm mb-1">Reserved</div>
          <div className="text-3xl font-bold text-orange-500">{totalReserved}</div>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="text-slate-500 text-sm mb-1">Scheduled</div>
          <div className="text-3xl font-bold text-indigo-600">{totalScheduled}</div>
        </div>
      </div>

      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
        <h2 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2"><ListOrdered size={16}/> Queue Lengths</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.keys(queues?.queues || {}).length === 0 ? (
            <div className="text-slate-500">No queues discovered</div>
          ) : (
            Object.entries(queues.queues).map(([name, len]) => (
              <div key={name} className="p-4 rounded-lg border border-slate-200 bg-slate-50 flex items-center justify-between">
                <span className="font-mono">{name}</span>
                <span className="text-xl font-bold">{len}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
        <h2 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2"><Activity size={16}/> Active Tasks (per worker)</h2>
        {Object.keys(queues?.active || {}).length === 0 ? (
          <div className="text-slate-500">No active tasks</div>
        ) : (
          Object.entries(queues.active).map(([worker, tasks]) => (
            <div key={worker} className="mb-4">
              <div className="text-sm font-semibold text-slate-700 mb-2">{worker}</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {tasks.map((t, idx) => (
                  <div key={idx} className="p-3 rounded-lg border border-slate-200 bg-slate-50">
                    <div className="font-mono text-xs">{t?.name || 'task'}</div>
                    <div className="text-xs text-slate-500">id: {t?.id}</div>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-slate-800">Heatmap</h2>
          <div className="flex items-center gap-2">
            <select className="border border-slate-200 rounded px-2 py-1 text-sm" value={metricType} onChange={e => setMetricType(e.target.value)}>
              <option value="latency">Latency p95</option>
              <option value="failure">Failure Rate</option>
            </select>
            <select className="border border-slate-200 rounded px-2 py-1 text-sm" value={bucket} onChange={e => setBucket(e.target.value)}>
              <option value="minute">Minute</option>
              <option value="hour">Hour</option>
            </select>
            <input type="number" className="border border-slate-200 rounded px-2 py-1 text-sm w-24" value={windowMinutes} onChange={e => setWindowMinutes(Number(e.target.value || 60))}/>
          </div>
        </div>
        {!metrics ? (
          <div className="text-slate-500">Loading metrics…</div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-xs text-slate-500">Queue</th>
                  {metrics.times.map(t => (
                    <th key={t} className="px-2 py-2 text-xs text-slate-500 whitespace-nowrap">{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(metrics.series).map(([q, arr]) => (
                  <tr key={q}>
                    <td className="px-3 py-2 text-xs font-mono">{q}</td>
                    {arr.map(point => {
                      const val = metricType === 'latency' ? point.p95 : point.fail_rate;
                      const intensity = Math.min(1, metricType === 'latency' ? (val / 5.0) : val); 
                      const color = metricType === 'latency'
                        ? `rgba(99,102,241,${intensity})`
                        : `rgba(239,68,68,${intensity})`;
                      return (
                        <td key={point.time} className="px-1 py-3 text-center">
                          <div className="rounded-sm" style={{ backgroundColor: color }}>
                            <span className="text-[10px] text-white px-1">
                              {metricType === 'latency' ? `${Math.round(val*100)/100}s` : `${Math.round(val*100)}%`}
                            </span>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
        <h2 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2"><Shield size={16}/> Task Events</h2>
        <div className="flex flex-wrap gap-2 mb-4">
          <input placeholder="Status" className="border border-slate-200 rounded px-2 py-1 text-sm" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} />
          <input placeholder="Queue" className="border border-slate-200 rounded px-2 py-1 text-sm" value={queueFilter} onChange={e => setQueueFilter(e.target.value)} />
          <input placeholder="Name" className="border border-slate-200 rounded px-2 py-1 text-sm" value={nameFilter} onChange={e => setNameFilter(e.target.value)} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {events.length === 0 ? (
            <div className="text-slate-500">No recent events</div>
          ) : (
            events.map(ev => (
              <div key={ev.id} className="p-4 rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex justify-between">
                  <span className="font-mono text-xs">{ev.name}</span>
                  <span className={`text-xs font-bold ${ev.status === 'failure' ? 'text-red-600' : ev.status === 'retry' ? 'text-orange-600' : 'text-green-700'}`}>{ev.status}</span>
                </div>
                <div className="text-xs text-slate-500 mt-1">id: {ev.task_id}</div>
                <div className="text-xs text-slate-500 mt-1">queue: {ev.queue || '-'}</div>
                <div className="text-xs text-slate-500 mt-1">worker: {ev.worker || '-'}</div>
                <div className="text-xs text-slate-500 mt-1">started: {ev.started_at || '-'}</div>
                <div className="text-xs text-slate-500 mt-1">finished: {ev.finished_at || '-'}</div>
                {ev.error && <div className="text-xs text-red-600 mt-1">error: {ev.error}</div>}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default JobsDashboard;
