import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  AlertTriangle, Bell, CheckCircle2, ChevronRight, Clock3, Inbox,
  LoaderCircle, MessageCircle, Phone, RefreshCw, RotateCcw, Save,
  Send, ShieldCheck, Users, X,
} from 'lucide-react';
import { API_URL } from '../config';

const DEFAULT_STUDENT_TEMPLATE = '⚠️ *Hostel Entry Reminder*\n\nHello {student_name}, no hostel entry was recorded by {cutoff_time} on {date}. Please report to the hostel or contact the administrator.';
const DEFAULT_PARENT_TEMPLATE = '⚠️ *Hostel Attendance Alert*\n\nDear Parent/Guardian, {student_name} has not recorded hostel entry as of {current_time} on {date}. Please contact the student or hostel administrator.';
const TEMPLATE_FIELDS = ['{student_name}', '{date}', '{cutoff_time}', '{current_time}'];

const defaults = {
  enabled: 0,
  owner_phone: '',
  cutoff_time: '19:00',
  escalation_minutes: 60,
  timezone: 'Asia/Kolkata',
  student_template: DEFAULT_STUDENT_TEMPLATE,
  parent_template: DEFAULT_PARENT_TEMPLATE,
  owner_summary_enabled: 1,
};

const normalizeSettings = (value = {}) => ({
  ...defaults,
  ...value,
  enabled: value.enabled ? 1 : 0,
  owner_summary_enabled: value.owner_summary_enabled === undefined || value.owner_summary_enabled ? 1 : 0,
  escalation_minutes: Number(value.escalation_minutes ?? 60),
  student_template: value.student_template || DEFAULT_STUDENT_TEMPLATE,
  parent_template: value.parent_template || DEFAULT_PARENT_TEMPLATE,
});

const comparableSettings = (value) => JSON.stringify(normalizeSettings(value));

const previewTemplate = (template) => String(template || '')
  .replaceAll('{student_name}', 'Ananya Sharma')
  .replaceAll('{date}', '21 Sep 2026')
  .replaceAll('{cutoff_time}', '07:00 PM')
  .replaceAll('{current_time}', '08:00 PM');

const formatClock = (value) => {
  const [hours = 0, minutes = 0] = String(value || '00:00').split(':').map(Number);
  const suffix = hours >= 12 ? 'PM' : 'AM';
  return `${String(hours % 12 || 12).padStart(2, '0')}:${String(minutes).padStart(2, '0')} ${suffix}`;
};

const addMinutesToClock = (value, amount) => {
  const [hours = 0, minutes = 0] = String(value || '00:00').split(':').map(Number);
  const total = ((hours * 60 + minutes + Number(amount || 0)) % 1440 + 1440) % 1440;
  return formatClock(`${Math.floor(total / 60)}:${total % 60}`);
};

const formatStage = (value) => ({
  student: 'Resident reminder',
  student_reminder: 'Resident reminder',
  parent: 'Parent escalation',
  parent_alert: 'Parent escalation',
  parent_escalation: 'Parent escalation',
  owner_summary: 'Admin summary',
}[value] || String(value || 'Alert').replaceAll('_', ' '));

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 cursor-pointer rounded-full transition-colors focus:outline-none focus:ring-4 focus:ring-indigo-100 ${checked ? 'bg-indigo-600' : 'bg-slate-300'}`}
    >
      <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-all ${checked ? 'left-6' : 'left-1'}`} />
    </button>
  );
}

function Toast({ toast, onClose }) {
  if (!toast) return null;
  const isError = toast.type === 'error';
  return (
    <div className={`fixed right-4 top-4 z-50 flex max-w-sm items-start gap-3 rounded-2xl border px-4 py-3 shadow-xl ${isError ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-white text-slate-800'}`}>
      {isError ? <AlertTriangle className="mt-0.5 shrink-0 text-red-500" size={19} /> : <CheckCircle2 className="mt-0.5 shrink-0 text-emerald-500" size={19} />}
      <div className="min-w-0">
        <p className="text-sm font-semibold">{isError ? 'Could not complete request' : 'Changes saved'}</p>
        <p className="mt-0.5 text-xs opacity-80">{toast.message}</p>
      </div>
      <button type="button" onClick={onClose} className="cursor-pointer rounded-md p-0.5 opacity-60 hover:opacity-100" aria-label="Close notification"><X size={16} /></button>
    </div>
  );
}

function MessageEditor({ title, description, value, onChange, onReset, accent }) {
  const appendField = (field) => onChange(`${value || ''}${value?.endsWith(' ') || !value ? '' : ' '}${field}`);
  return (
    <article className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className={`border-b px-5 py-4 ${accent === 'emerald' ? 'bg-emerald-50/70' : 'bg-indigo-50/70'}`}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <MessageCircle size={18} className={accent === 'emerald' ? 'text-emerald-600' : 'text-indigo-600'} />
              <h3 className="font-semibold text-slate-900">{title}</h3>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
          </div>
          <button type="button" onClick={onReset} className="flex shrink-0 cursor-pointer items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-600 hover:bg-white hover:text-indigo-700">
            <RotateCcw size={13} /> Reset
          </button>
        </div>
      </div>
      <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(250px,.95fr)]">
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Message text</label>
          <textarea
            rows="8"
            value={value || ''}
            onChange={(event) => onChange(event.target.value)}
            className="mt-2 w-full resize-y rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-sm leading-6 text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-4 focus:ring-indigo-50"
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="mr-1 text-xs font-medium text-slate-500">Insert field:</span>
            {TEMPLATE_FIELDS.map((field) => (
              <button key={field} type="button" onClick={() => appendField(field)} className="cursor-pointer rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-50">
                {field}
              </button>
            ))}
          </div>
          <p className="mt-3 text-right text-[11px] text-slate-400">{String(value || '').length} characters</p>
        </div>
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">WhatsApp preview</p>
          <div className="rounded-[1.75rem] bg-slate-900 p-2 shadow-lg">
            <div className="min-h-56 rounded-[1.3rem] bg-[#efeae2] p-3">
              <div className="mb-3 flex items-center gap-2 rounded-xl bg-white/80 px-3 py-2">
                <div className="grid h-8 w-8 place-items-center rounded-full bg-emerald-600 text-xs font-bold text-white">HX</div>
                <div><p className="text-xs font-semibold text-slate-800">Hostel Desk</p><p className="text-[10px] text-slate-500">WhatsApp notification</p></div>
              </div>
              <div className="ml-auto max-w-[94%] rounded-2xl rounded-br-sm bg-[#d9fdd3] px-3 py-2.5 shadow-sm">
                <p className="whitespace-pre-wrap text-[11px] leading-5 text-slate-800">{previewTemplate(value) || 'Your message preview will appear here.'}</p>
                <p className="mt-1 text-right text-[9px] text-slate-500">Preview ✓✓</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

export default function HostelAlerts() {
  const [settings, setSettings] = useState(defaults);
  const [savedSettings, setSavedSettings] = useState(defaults);
  const [deliveries, setDeliveries] = useState([]);
  const [deliveryFilter, setDeliveryFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState(null);

  const dirty = comparableSettings(settings) !== comparableSettings(savedSettings);
  const escalationTime = addMinutesToClock(settings.cutoff_time, settings.escalation_minutes);

  const deliveryStats = useMemo(() => ({
    all: deliveries.length,
    sent: deliveries.filter((item) => item.status === 'sent').length,
    failed: deliveries.filter((item) => item.status !== 'sent').length,
  }), [deliveries]);

  const visibleDeliveries = useMemo(() => deliveries.filter((item) => (
    deliveryFilter === 'all' || (deliveryFilter === 'sent' ? item.status === 'sent' : item.status !== 'sent')
  )), [deliveries, deliveryFilter]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const load = async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    setError('');
    try {
      const [settingsResponse, deliveriesResponse] = await Promise.all([
        axios.get(`${API_URL}/hostel-alerts/settings`),
        axios.get(`${API_URL}/hostel-alerts/deliveries?limit=100`),
      ]);
      const normalized = normalizeSettings(settingsResponse.data?.settings);
      setSettings(normalized);
      setSavedSettings(normalized);
      setDeliveries(deliveriesResponse.data?.deliveries || []);
    } catch (requestError) {
      const message = requestError.response?.data?.error || requestError.message;
      setError(message);
      setToast({ type: 'error', message });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { load(true); }, []);

  const refresh = () => {
    if (dirty) {
      setToast({ type: 'error', message: 'Save your changes before refreshing so they are not lost.' });
      return;
    }
    load(false);
  };

  const save = async () => {
    const scheduleChanged = ['enabled', 'cutoff_time', 'escalation_minutes', 'timezone']
      .some((key) => String(settings[key]) !== String(savedSettings[key]));
    setSaving(true);
    setError('');
    try {
      const response = await axios.put(`${API_URL}/hostel-alerts/settings`, {
        ...settings,
        enabled: Boolean(settings.enabled),
        owner_summary_enabled: Boolean(settings.owner_summary_enabled),
        escalation_minutes: Number(settings.escalation_minutes),
      });
      const normalized = normalizeSettings(response.data?.settings);
      setSettings(normalized);
      setSavedSettings(normalized);
      setToast({
        type: 'success',
        message: scheduleChanged && normalized.enabled
          ? 'New alert cycle saved. Missing-entry reminders will be evaluated after the new cutoff on the next scheduler run.'
          : 'Hostel alert settings are now up to date.',
      });
    } catch (requestError) {
      const message = requestError.response?.data?.error || requestError.message;
      setError(message);
      setToast({ type: 'error', message });
    } finally {
      setSaving(false);
    }
  };

  const update = (key, value) => setSettings((current) => ({ ...current, [key]: value }));

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 pb-24 md:p-8 md:pb-24" aria-busy={loading || refreshing}>
      <Toast toast={toast} onClose={() => setToast(null)} />

      <header className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-indigo-700 via-violet-700 to-fuchsia-700 px-5 py-6 text-white shadow-xl shadow-indigo-200/50 md:px-8 md:py-8">
        <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-white/10 blur-2xl" />
        <div className="absolute -bottom-24 left-1/3 h-52 w-52 rounded-full bg-fuchsia-300/20 blur-3xl" />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-2xl">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold backdrop-blur"><Bell size={14} /> Hostel safety</span>
              <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${loading ? 'bg-white/15 text-white' : settings.enabled ? 'bg-emerald-300 text-emerald-950' : 'bg-white/15 text-white'}`}>
                {loading ? <LoaderCircle className="animate-spin" size={13} /> : <span className={`h-2 w-2 rounded-full ${settings.enabled ? 'animate-pulse bg-emerald-700' : 'bg-white/70'}`} />} {loading ? 'Loading saved settings' : settings.enabled ? 'Automation active' : 'Automation paused'}
              </span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Hostel Entry Alerts</h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-indigo-100">Keep residents, parents, and hostel staff informed when a student has not returned by the configured entry time.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={refresh} disabled={loading || refreshing} className="flex cursor-pointer items-center gap-2 rounded-xl border border-white/25 bg-white/10 px-4 py-2.5 text-sm font-semibold backdrop-blur transition hover:bg-white/20 disabled:cursor-wait disabled:opacity-60">
              <RefreshCw size={16} className={loading || refreshing ? 'animate-spin' : ''} /> {loading || refreshing ? 'Loading…' : 'Refresh'}
            </button>
            <button type="button" onClick={save} disabled={loading || saving || !dirty} className="flex cursor-pointer items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-indigo-700 shadow-sm transition hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-60">
              {saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />} {saving ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
            </button>
          </div>
        </div>
      </header>

      {error && (
        <div className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-red-800">
          <AlertTriangle className="mt-0.5 shrink-0" size={19} /><div><p className="text-sm font-semibold">Hostel alerts need attention</p><p className="mt-0.5 text-xs">{error}</p></div>
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[1.05fr_.95fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:p-6">
          <div className="flex items-start justify-between gap-5">
            <div className="flex gap-3">
              <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${settings.enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}><ShieldCheck size={22} /></div>
              <div><h2 className="font-bold text-slate-900">Automated entry monitoring</h2><p className="mt-1 max-w-xl text-sm leading-5 text-slate-500">Turn on daily checks for missing hostel entry. The SuperAdmin feature and WhatsApp connection must also remain enabled.</p></div>
            </div>
            <Toggle checked={Boolean(settings.enabled)} onChange={(value) => update('enabled', value ? 1 : 0)} label="Automated hostel entry alerts" />
          </div>
          <div className={`mt-5 flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs font-medium ${settings.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
            {settings.enabled ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            {settings.enabled ? 'Alerts will run according to the schedule below after you save.' : 'No resident or parent alerts will be sent while automation is paused.'}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:p-6">
          <div className="mb-4 flex items-center gap-2"><Clock3 className="text-indigo-600" size={20} /><h2 className="font-bold text-slate-900">Today’s alert journey</h2></div>
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <div className="min-w-[135px] flex-1 rounded-xl bg-indigo-50 p-3"><p className="text-[10px] font-bold uppercase tracking-wider text-indigo-500">Cutoff</p><p className="mt-1 font-bold text-indigo-950">{formatClock(settings.cutoff_time)}</p><p className="mt-1 text-[11px] text-indigo-700">Resident reminder</p></div>
            <ChevronRight className="shrink-0 text-slate-300" size={18} />
            <div className="min-w-[135px] flex-1 rounded-xl bg-fuchsia-50 p-3"><p className="text-[10px] font-bold uppercase tracking-wider text-fuchsia-500">Grace period</p><p className="mt-1 font-bold text-fuchsia-950">{settings.escalation_minutes || 0} minutes</p><p className="mt-1 text-[11px] text-fuchsia-700">Wait for entry</p></div>
            <ChevronRight className="shrink-0 text-slate-300" size={18} />
            <div className="min-w-[135px] flex-1 rounded-xl bg-amber-50 p-3"><p className="text-[10px] font-bold uppercase tracking-wider text-amber-600">Escalation</p><p className="mt-1 font-bold text-amber-950">{escalationTime}</p><p className="mt-1 text-[11px] text-amber-700">Notify parent</p></div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-5 py-4 md:px-6"><h2 className="font-bold text-slate-900">Schedule & recipients</h2><p className="mt-1 text-xs text-slate-500">Choose when alerts run and where the daily administrator summary is delivered.</p></div>
        <div className="grid gap-5 p-5 md:grid-cols-2 md:p-6 xl:grid-cols-4">
          <label className="block">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-700"><Phone size={15} className="text-indigo-500" /> Administrator WhatsApp</span>
            <input inputMode="tel" value={settings.owner_phone || ''} onChange={(event) => update('owner_phone', event.target.value)} placeholder="+91 98765 43210" className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-4 focus:ring-indigo-50" />
            <span className="mt-1.5 block text-[11px] text-slate-400">Include country code for reliable delivery.</span>
          </label>
          <label className="block">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-700"><Clock3 size={15} className="text-indigo-500" /> Daily entry cutoff</span>
            <input type="time" value={settings.cutoff_time || '19:00'} onChange={(event) => update('cutoff_time', event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-4 focus:ring-indigo-50" />
            <span className="mt-1.5 block text-[11px] text-slate-400">Missing-entry checks begin at this time.</span>
          </label>
          <div>
            <label className="text-sm font-semibold text-slate-700" htmlFor="escalation-minutes">Parent grace period</label>
            <div className="relative mt-2"><input id="escalation-minutes" type="number" min="5" max="1440" value={settings.escalation_minutes} onChange={(event) => update('escalation_minutes', event.target.value)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 pr-20 text-sm outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-4 focus:ring-indigo-50" /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-slate-400">minutes</span></div>
            <div className="mt-2 flex gap-1.5">{[30, 60, 120].map((minutes) => <button key={minutes} type="button" onClick={() => update('escalation_minutes', minutes)} className={`cursor-pointer rounded-lg px-2 py-1 text-[11px] font-semibold ${Number(settings.escalation_minutes) === minutes ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-indigo-50 hover:text-indigo-700'}`}>{minutes < 60 ? `${minutes}m` : `${minutes / 60}h`}</button>)}</div>
          </div>
          <label className="block">
            <span className="text-sm font-semibold text-slate-700">Hostel timezone</span>
            <select value={settings.timezone || 'Asia/Kolkata'} onChange={(event) => update('timezone', event.target.value)} className="mt-2 w-full cursor-pointer rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-4 focus:ring-indigo-50">
              <option value="Asia/Kolkata">Asia/Kolkata</option><option value="Asia/Dubai">Asia/Dubai</option><option value="Asia/Singapore">Asia/Singapore</option><option value="Europe/London">Europe/London</option><option value="America/New_York">America/New_York</option>
            </select>
            <span className="mt-1.5 block text-[11px] text-slate-400">Used for cutoff and escalation timing.</span>
          </label>
        </div>
        <div className="mx-5 mb-5 flex items-start justify-between gap-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 md:mx-6 md:mb-6">
          <div className="flex gap-3"><div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white text-indigo-600 shadow-sm"><Users size={18} /></div><div><p className="text-sm font-semibold text-slate-800">Daily administrator summary</p><p className="mt-0.5 text-xs leading-5 text-slate-500">Send one consolidated list of residents still missing after the grace period.</p></div></div>
          <Toggle checked={Boolean(settings.owner_summary_enabled)} onChange={(value) => update('owner_summary_enabled', value ? 1 : 0)} label="Daily administrator summary" />
        </div>
      </section>

      <section>
        <div className="mb-4"><h2 className="text-lg font-bold text-slate-900">WhatsApp messages</h2><p className="mt-1 text-sm text-slate-500">Personalize each message and preview exactly what recipients will see.</p></div>
        <div className="grid gap-5 2xl:grid-cols-2">
          <MessageEditor title="Resident reminder" description={`Sent at ${formatClock(settings.cutoff_time)} when hostel entry is missing.`} value={settings.student_template} onChange={(value) => update('student_template', value)} onReset={() => update('student_template', DEFAULT_STUDENT_TEMPLATE)} accent="indigo" />
          <MessageEditor title="Parent / guardian escalation" description={`Sent at ${escalationTime} only if the resident still has not returned.`} value={settings.parent_template} onChange={(value) => update('parent_template', value)} onReset={() => update('parent_template', DEFAULT_PARENT_TEMPLATE)} accent="emerald" />
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-4 border-b border-slate-100 p-5 md:flex-row md:items-center md:justify-between md:px-6">
          <div><h2 className="flex items-center gap-2 font-bold text-slate-900"><Send size={18} className="text-indigo-600" /> Recent alert deliveries</h2><p className="mt-1 text-xs text-slate-500">Latest 100 delivery attempts across residents, parents, and administrators.</p></div>
          <div className="flex flex-wrap gap-2">
            {[['all', `All ${deliveryStats.all}`], ['sent', `Sent ${deliveryStats.sent}`], ['failed', `Needs attention ${deliveryStats.failed}`]].map(([key, label]) => (
              <button key={key} type="button" onClick={() => setDeliveryFilter(key)} className={`cursor-pointer rounded-lg px-3 py-1.5 text-xs font-semibold transition ${deliveryFilter === key ? 'bg-indigo-600 text-white shadow-sm' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{label}</button>
            ))}
          </div>
        </div>

        {visibleDeliveries.length ? (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500"><tr><th className="px-5 py-3 text-left">Date</th><th className="px-5 py-3 text-left">Resident</th><th className="px-5 py-3 text-left">Stage</th><th className="px-5 py-3 text-left">Recipient</th><th className="px-5 py-3 text-left">Status</th><th className="px-5 py-3 text-left">Details</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {visibleDeliveries.map((item) => <tr key={item.id} className="transition hover:bg-slate-50/70"><td className="whitespace-nowrap px-5 py-3.5 text-slate-600">{item.alert_date}</td><td className="px-5 py-3.5 font-medium text-slate-800">{item.name || (item.person_id === 0 ? 'Administrator summary' : `Resident ${item.person_id}`)}</td><td className="px-5 py-3.5 text-slate-600">{formatStage(item.alert_type)}</td><td className="whitespace-nowrap px-5 py-3.5 text-slate-600">{item.recipient_phone || 'Not available'}</td><td className="px-5 py-3.5"><span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${item.status === 'sent' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{item.status === 'sent' ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}{item.status === 'sent' ? 'Sent' : String(item.status || 'Failed').replaceAll('_', ' ')}</span></td><td className="max-w-xs px-5 py-3.5 text-xs text-slate-500">{item.error || 'Delivered successfully'}</td></tr>)}
                </tbody>
              </table>
            </div>
            <div className="divide-y divide-slate-100 md:hidden">
              {visibleDeliveries.map((item) => <article key={item.id} className="p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold text-slate-800">{item.name || (item.person_id === 0 ? 'Administrator summary' : `Resident ${item.person_id}`)}</p><p className="mt-1 text-xs text-slate-500">{formatStage(item.alert_type)} · {item.alert_date}</p></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${item.status === 'sent' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{item.status === 'sent' ? 'Sent' : 'Needs attention'}</span></div><div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600"><p>{item.recipient_phone || 'Recipient number not available'}</p>{item.error && <p className="mt-1 text-red-600">{item.error}</p>}</div></article>)}
            </div>
          </>
        ) : (
          <div className="grid min-h-52 place-items-center px-6 py-10 text-center"><div><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-slate-400"><Inbox size={24} /></div><p className="mt-3 text-sm font-semibold text-slate-700">No matching deliveries</p><p className="mt-1 text-xs text-slate-500">Delivery results will appear here after alerts are processed.</p></div></div>
        )}
      </section>

      {dirty && (
        <div className="fixed bottom-4 left-1/2 z-40 flex w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 items-center justify-between gap-4 rounded-2xl border border-indigo-200 bg-white px-4 py-3 shadow-2xl shadow-indigo-200/60">
          <div className="min-w-0"><p className="text-sm font-semibold text-slate-900">You have unsaved changes</p><p className="truncate text-xs text-slate-500">Save to apply the updated alert schedule and messages.</p></div>
          <button type="button" onClick={save} disabled={saving} className="flex shrink-0 cursor-pointer items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60">{saving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />}{saving ? 'Saving…' : 'Save'}</button>
        </div>
      )}
    </div>
  );
}
