import { useEffect, useState } from 'react';
import axios from 'axios';
import { Bell, RefreshCw, Save } from 'lucide-react';
import { API_URL } from '../config';

const defaults = {
  enabled: 0,
  owner_phone: '',
  cutoff_time: '19:00',
  escalation_minutes: 60,
  timezone: 'Asia/Kolkata',
  student_template: '',
  parent_template: '',
  owner_summary_enabled: 1,
};

export default function HostelAlerts() {
  const [settings, setSettings] = useState(defaults);
  const [deliveries, setDeliveries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [settingsResponse, deliveriesResponse] = await Promise.all([
        axios.get(`${API_URL}/hostel-alerts/settings`),
        axios.get(`${API_URL}/hostel-alerts/deliveries?limit=100`),
      ]);
      setSettings({ ...defaults, ...(settingsResponse.data?.settings || {}) });
      setDeliveries(deliveriesResponse.data?.deliveries || []);
    } catch (requestError) {
      setError(requestError.response?.data?.error || requestError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const response = await axios.put(`${API_URL}/hostel-alerts/settings`, {
        ...settings,
        enabled: Boolean(settings.enabled),
        owner_summary_enabled: Boolean(settings.owner_summary_enabled),
        escalation_minutes: Number(settings.escalation_minutes),
      });
      setSettings({ ...defaults, ...(response.data?.settings || {}) });
    } catch (requestError) {
      setError(requestError.response?.data?.error || requestError.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-8 text-slate-500">Loading Hostel Alerts…</div>;

  return (
    <div className="p-4 md:p-8 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Bell className="text-indigo-600" size={24} />
            <h1 className="text-2xl font-bold text-slate-900">Hostel Alerts</h1>
          </div>
          <p className="text-sm text-slate-500 mt-1">Notify residents at cutoff, then parents only if entry is still missing after the grace period.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="px-4 py-2 border rounded-lg flex items-center gap-2 text-sm">
            <RefreshCw size={16} /> Refresh
          </button>
          <button onClick={save} disabled={saving} className="px-4 py-2 bg-indigo-600 text-white rounded-lg flex items-center gap-2 text-sm disabled:opacity-60">
            <Save size={16} /> {saving ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      </div>

      {error && <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">{error}</div>}

      <section className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm space-y-5">
        <label className="flex items-center justify-between gap-4 p-4 rounded-xl bg-slate-50 border">
          <div>
            <div className="font-semibold text-slate-900">Run automated hostel entry alerts</div>
            <div className="text-xs text-slate-500">The SuperAdmin feature and this vendor-level switch must both remain enabled.</div>
          </div>
          <input type="checkbox" className="h-5 w-5" checked={Boolean(settings.enabled)} onChange={e => setSettings(s => ({ ...s, enabled: e.target.checked ? 1 : 0 }))} />
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="text-sm font-medium text-slate-700">Hostel administrator WhatsApp
            <input value={settings.owner_phone || ''} onChange={e => setSettings(s => ({ ...s, owner_phone: e.target.value }))} placeholder="+919876543210" className="mt-1 w-full border rounded-lg px-3 py-2" />
          </label>
          <label className="text-sm font-medium text-slate-700">Daily entry cutoff
            <input type="time" value={settings.cutoff_time || '19:00'} onChange={e => setSettings(s => ({ ...s, cutoff_time: e.target.value }))} className="mt-1 w-full border rounded-lg px-3 py-2" />
          </label>
          <label className="text-sm font-medium text-slate-700">Parent escalation after (minutes)
            <input type="number" min="5" max="1440" value={settings.escalation_minutes} onChange={e => setSettings(s => ({ ...s, escalation_minutes: e.target.value }))} className="mt-1 w-full border rounded-lg px-3 py-2" />
          </label>
          <label className="text-sm font-medium text-slate-700">Hostel timezone
            <select value={settings.timezone || 'Asia/Kolkata'} onChange={e => setSettings(s => ({ ...s, timezone: e.target.value }))} className="mt-1 w-full border rounded-lg px-3 py-2 bg-white">
              <option value="Asia/Kolkata">Asia/Kolkata</option>
              <option value="Asia/Dubai">Asia/Dubai</option>
              <option value="Asia/Singapore">Asia/Singapore</option>
              <option value="Europe/London">Europe/London</option>
              <option value="America/New_York">America/New_York</option>
            </select>
          </label>
        </div>

        <label className="flex items-center gap-3 text-sm text-slate-700">
          <input type="checkbox" checked={Boolean(settings.owner_summary_enabled)} onChange={e => setSettings(s => ({ ...s, owner_summary_enabled: e.target.checked ? 1 : 0 }))} />
          Send one daily missing-entry summary to the hostel administrator
        </label>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <label className="text-sm font-medium text-slate-700">Resident message template
            <textarea rows="5" value={settings.student_template || ''} onChange={e => setSettings(s => ({ ...s, student_template: e.target.value }))} placeholder="Leave blank to use the default message." className="mt-1 w-full border rounded-lg px-3 py-2" />
          </label>
          <label className="text-sm font-medium text-slate-700">Parent message template
            <textarea rows="5" value={settings.parent_template || ''} onChange={e => setSettings(s => ({ ...s, parent_template: e.target.value }))} placeholder="Leave blank to use the default message." className="mt-1 w-full border rounded-lg px-3 py-2" />
          </label>
        </div>
        <p className="text-xs text-slate-500">Template fields: {'{student_name}'}, {'{date}'}, {'{cutoff_time}'}, {'{current_time}'}. Connect WhatsApp from Settings before enabling delivery.</p>
      </section>

      <section className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="p-5 border-b"><h2 className="font-bold text-slate-900">Recent Alert Deliveries</h2></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600"><tr>
              <th className="text-left px-4 py-3">Date</th><th className="text-left px-4 py-3">Resident</th>
              <th className="text-left px-4 py-3">Stage</th><th className="text-left px-4 py-3">Recipient</th>
              <th className="text-left px-4 py-3">Status</th><th className="text-left px-4 py-3">Details</th>
            </tr></thead>
            <tbody>
              {deliveries.map(item => <tr key={item.id} className="border-t">
                <td className="px-4 py-3">{item.alert_date}</td><td className="px-4 py-3">{item.name || (item.person_id === 0 ? 'Administrator summary' : `Person ${item.person_id}`)}</td>
                <td className="px-4 py-3 capitalize">{String(item.alert_type || '').replace('_', ' ')}</td><td className="px-4 py-3">{item.recipient_phone || 'Missing'}</td>
                <td className="px-4 py-3"><span className={`px-2 py-1 rounded-full text-xs font-semibold ${item.status === 'sent' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{item.status}</span></td>
                <td className="px-4 py-3 text-slate-500 max-w-xs">{item.error || '—'}</td>
              </tr>)}
              {!deliveries.length && <tr><td colSpan="6" className="px-4 py-8 text-center text-slate-500">No alerts have been processed yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
