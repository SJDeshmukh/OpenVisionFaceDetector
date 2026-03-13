import { KPIGrid } from '../components/KPI.js';
import { AreaChart, BarChart } from '../components/ChartWrappers.js';
import { StatusBadge } from '../components/StatusBadge.js';

export function DashboardPage({ tab = 'Overview' } = {}) {
  const container = document.createElement('div');
  container.className = 'grid gap-6';

  if (tab === 'Overview') {
    const kpis = KPIGrid([
      { title: 'Attendance Rate', value: '96.4%', subtext: 'vs last week +1.2%', color: '#2563eb' },
      { title: 'On-Time', value: '88.1%', subtext: 'avg arrival confidence', color: '#22c55e' },
      { title: 'Late', value: '6.7%', subtext: 'flagged events', color: '#ef4444' },
      { title: 'Absences', value: '12', subtext: 'past 7 days', color: '#f59e0b' }
    ]);
    container.appendChild(kpis);

    const charts = document.createElement('div');
    charts.style.display = 'grid';
    charts.style.gridTemplateColumns = '1fr 1fr';
    charts.style.gap = '24px';
    const area = AreaChart({ data: Array.from({ length: 24 }, (_, i) => ({ x: i, y: Math.round(60 + Math.sin(i / 3) * 25 + Math.random() * 10) })) });
    const bar = BarChart({ data: ['HR', 'Engineering', 'Operations', 'Sales', 'Design'].map((d, idx) => ({ x: d, y: 40 + idx * 10 + Math.round(Math.random() * 15) })) });
    charts.append(area, bar);
    container.appendChild(charts);

    const activity = document.createElement('div');
    activity.className = 'card';
    const h = document.createElement('div'); h.textContent = 'Recent Activity'; h.className = 'font-bold text-slate-800';
    const list = document.createElement('ul'); list.style.listStyle = 'none'; list.style.padding = '0'; list.style.margin = '12px 0 0';
    ['Jane Doe clocked in (HQ)', 'Camera 2 synced', 'Policy updated: Overtime', 'John Smith marked late'].forEach(item => {
      const li = document.createElement('li'); li.textContent = item; li.style.padding = '8px 0'; list.appendChild(li);
    });
    activity.append(h, list);
    container.appendChild(activity);
  } else {
    const card = document.createElement('div'); card.className = 'card';
    const header = document.createElement('div'); header.style.display = 'flex'; header.style.alignItems = 'center'; header.style.justifyContent = 'space-between';
    const left = document.createElement('div');
    const title = document.createElement('div'); title.className = 'font-bold text-slate-800'; title.textContent = 'Subscription: Enterprise Plan';
    const badge = StatusBadge('active', 'Active');
    left.append(title, badge);
    const right = document.createElement('div'); right.textContent = 'Renews: 2026-05-01'; right.className = 'text-slate-500';
    header.append(left, right);
    const progress = document.createElement('div'); progress.style.marginTop = '12px';
    const bar = document.createElement('div'); bar.style.height = '10px'; bar.style.borderRadius = '9999px'; bar.style.background = 'var(--slate-100)';
    const fill = document.createElement('div'); fill.style.height = '10px'; fill.style.width = '60%'; fill.style.borderRadius = '9999px'; fill.style.background = 'var(--primary-blue)';
    bar.appendChild(fill); progress.appendChild(bar);
    const chips = document.createElement('div'); chips.style.display = 'flex'; chips.style.flexWrap = 'wrap'; chips.style.gap = '8px'; chips.style.marginTop = '12px';
    ['Live Attendance', 'Audit Logs', 'System Health', 'Reports'].forEach(c => {
      const chip = document.createElement('span'); chip.className = 'filter-chip'; chip.textContent = c; chips.appendChild(chip);
    });
    const info = document.createElement('div'); info.className = 'card'; info.style.background = 'var(--blue-50)';
    const t = document.createElement('div'); t.className = 'font-bold text-slate-800'; t.textContent = 'Plan Info';
    const p = document.createElement('p'); p.className = 'text-slate-600'; p.textContent = 'You are on Enterprise plan with priority support.';
    info.append(t, p);
    card.append(header, progress, chips, info);
    container.appendChild(card);
  }
  return container;
}
