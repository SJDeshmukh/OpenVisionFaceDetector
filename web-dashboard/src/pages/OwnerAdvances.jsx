import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Check, Clock3, IndianRupee, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { API_URL } from '../config';

const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: 2,
});

const readableDate = (value) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString('en-IN');
};

const OwnerAdvances = () => {
  const [advances, setAdvances] = useState([]);
  const [filter, setFilter] = useState('pending');
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadAdvances = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await axios.get(`${API_URL}/owner/advances`, { params: { status: 'all' } });
      setAdvances(Array.isArray(data.advances) ? data.advances : []);
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'Could not load advance requests.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAdvances(); }, [loadAdvances]);

  const pending = useMemo(
    () => advances.filter((item) => String(item.status || '').toLowerCase() === 'pending'),
    [advances],
  );
  const visible = filter === 'all'
    ? advances
    : advances.filter((item) => String(item.status || '').toLowerCase() === filter);
  const pendingAmount = pending.reduce((sum, item) => sum + Number(item.amount || 0), 0);

  const decide = async (advance, action) => {
    const employee = advance.name || advance.employee_name || 'this employee';
    let rejectionReason = '';
    if (action === 'approve') {
      if (!window.confirm(`Approve ${currency.format(Number(advance.amount || 0))} for ${employee}?`)) return;
    } else {
      rejectionReason = window.prompt(`Reason for rejecting ${employee}'s advance:`)?.trim() || '';
      if (!rejectionReason) return;
    }

    setProcessingId(advance.id);
    setError('');
    setNotice('');
    try {
      const payload = { advance_id: advance.id };
      if (rejectionReason) payload.rejection_reason = rejectionReason;
      const { data } = await axios.post(`${API_URL}/owner/advances/${action}`, payload);
      setNotice(data.message || `Advance ${action === 'approve' ? 'approved' : 'rejected'}.`);
      await loadAdvances();
    } catch (requestError) {
      setError(requestError.response?.data?.error || `Could not ${action} this advance.`);
    } finally {
      setProcessingId(null);
    }
  };

  return (
    <section className="min-h-[calc(100vh-8rem)] space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-violet-500">
            <ShieldCheck size={18} />
            <span className="text-xs font-semibold uppercase tracking-[0.16em]">Owner authorization</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900">Advance approvals</h1>
          <p className="mt-1 text-sm text-slate-500">Only approved advances are deducted from employee payroll.</p>
        </div>
        <button type="button" onClick={loadAdvances} disabled={loading}
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-violet-500 hover:text-violet-600 disabled:opacity-60">
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-5">
          <div className="flex items-center justify-between text-amber-600"><span className="text-sm font-medium">Pending requests</span><Clock3 size={20} /></div>
          <p className="mt-2 text-3xl font-bold text-slate-900">{pending.length}</p>
        </div>
        <div className="rounded-2xl border border-violet-500/20 bg-violet-500/10 p-5">
          <div className="flex items-center justify-between text-violet-600"><span className="text-sm font-medium">Pending amount</span><IndianRupee size={20} /></div>
          <p className="mt-2 text-3xl font-bold text-slate-900">{currency.format(pendingAmount)}</p>
        </div>
      </div>

      {notice && <div role="status" className="rounded-xl border border-emerald-700/50 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-300">{notice}</div>}
      {error && <div role="alert" className="rounded-xl border border-red-800/60 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap gap-2 border-b border-slate-200 p-4">
          {['pending', 'approved', 'rejected', 'all'].map((status) => (
            <button key={status} type="button" onClick={() => setFilter(status)}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold capitalize transition ${filter === status ? 'bg-violet-600 text-white shadow-sm' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900'}`}>
              {status}{status === 'pending' ? ` (${pending.length})` : ''}
            </button>
          ))}
        </div>

        {loading && advances.length === 0 ? (
          <div className="grid min-h-52 place-items-center text-sm text-slate-400"><RefreshCw className="mb-2 animate-spin" size={24} />Loading requests…</div>
        ) : visible.length === 0 ? (
          <div className="grid min-h-52 place-items-center px-4 text-center text-sm text-slate-400">
            {filter === 'pending' ? 'There are no advances waiting for approval.' : `There are no ${filter} advance requests.`}
          </div>
        ) : (
          <div className="divide-y divide-slate-200">
            {visible.map((advance) => {
              const status = String(advance.status || 'pending').toLowerCase();
              return (
                <article key={advance.id} className="grid gap-4 p-5 lg:grid-cols-[1.4fr_1fr_1fr_auto] lg:items-center">
                  <div>
                    <p className="font-semibold text-slate-900">{advance.name || advance.employee_name || 'Unknown employee'}</p>
                    <p className="mt-1 text-xs text-slate-500">Employee ID: {advance.display_id || '—'} · Requested {readableDate(advance.date || advance.created_at)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Amount</p>
                    <p className="mt-1 font-semibold text-slate-800">{currency.format(Number(advance.amount || 0))}</p>
                    <p className="mt-1 text-xs text-slate-500">Cash {currency.format(Number(advance.amount_cash || 0))} · Online {currency.format(Number(advance.amount_online || 0))}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Deduction month</p>
                    <p className="mt-1 text-sm text-slate-700">{advance.deduction_month || 'Not specified'}</p>
                    <span className={`mt-2 inline-flex rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${status === 'approved' ? 'bg-emerald-500/15 text-emerald-600' : status === 'rejected' ? 'bg-red-500/15 text-red-600' : 'bg-amber-500/15 text-amber-600'}`}>{status}</span>
                  </div>
                  {status === 'pending' && (
                    <div className="flex gap-2 lg:justify-end">
                      <button type="button" onClick={() => decide(advance, 'approve')} disabled={processingId === advance.id}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-600 disabled:opacity-50"><Check size={15} /> Approve</button>
                      <button type="button" onClick={() => decide(advance, 'reject')} disabled={processingId === advance.id}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-red-500/15 px-3 py-2 text-xs font-bold text-red-600 hover:bg-red-500/25 disabled:opacity-50"><X size={15} /> Reject</button>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
};

export default OwnerAdvances;
