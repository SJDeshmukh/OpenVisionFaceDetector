import { DataTable } from '../components/DataTable.js';
import { StatusBadge } from '../components/StatusBadge.js';
import { Modal } from '../components/Modal.js';

function Tag(label, bg = '#ede9ff', color = '#6b21a8') {
  const t = document.createElement('span');
  t.textContent = label;
  t.style.background = bg;
  t.style.color = color;
  t.style.padding = '6px 10px';
  t.style.borderRadius = '9999px';
  t.style.border = '1px solid var(--slate-200)';
  return t;
}

export function VendorsPage() {
  const container = document.createElement('div');
  container.className = 'grid gap-6';

  const actionBar = document.createElement('div'); actionBar.className = 'action-bar';
  const del = document.createElement('button'); del.className = 'btn-pastel red'; del.textContent = 'Delete';
  const sync = document.createElement('button'); sync.className = 'btn-pastel blue'; sync.textContent = 'Sync';
  const config = document.createElement('button'); config.className = 'btn-pastel indigo'; config.textContent = 'Architecture Config';
  config.addEventListener('click', () => {
    const content = document.createElement('div');
    content.style.display = 'grid'; content.style.gap = '8px';
    const label1 = document.createElement('label'); label1.textContent = 'Frontend bundle'; label1.className = 'text-slate-700';
    const sel1 = document.createElement('select'); sel1.className = 'select'; ['core', 'enterprise'].forEach(opt => { const o = document.createElement('option'); o.value = opt; o.textContent = opt; sel1.appendChild(o); });
    const label2 = document.createElement('label'); label2.textContent = 'Backend service'; label2.className = 'text-slate-700';
    const sel2 = document.createElement('select'); sel2.className = 'select'; ['api-v1', 'api-v2'].forEach(opt => { const o = document.createElement('option'); o.value = opt; o.textContent = opt; sel2.appendChild(o); });
    const features = document.createElement('div'); features.style.display = 'flex'; features.style.flexWrap = 'wrap'; features.style.gap = '8px';
    ['Attendance', 'Live Feed', 'Audit Logs', 'System Health', 'Reports'].forEach(f => features.appendChild(Tag(f, '#eaf1ff', '#1e40af')));
    content.append(label1, sel1, label2, sel2, features);
    const modal = Modal({
      title: 'Architecture Config',
      content,
      actions: [
        { label: 'Save', variant: 'primary', onClick: (backdrop) => backdrop.remove() },
        { label: 'Cancel', variant: 'outline', onClick: (backdrop) => backdrop.remove() }
      ]
    });
    document.getElementById('modalRoot').appendChild(modal);
  });
  actionBar.append(del, sync, config);
  container.appendChild(actionBar);

  const columns = [
    { key: 'name', label: 'Vendor' },
    { key: 'ui', label: 'UI' },
    { key: 'api', label: 'API' },
    { key: 'status', label: 'Status' }
  ];
  const rows = [
    { name: 'Alpha Inc.', ui: Tag('UI', '#ede9ff', '#6d28d9'), api: Tag('API', '#fff7ed', '#c2410c'), status: StatusBadge('active', 'Active') },
    { name: 'Beta LLC', ui: Tag('UI', '#ede9ff', '#6d28d9'), api: Tag('API', '#fff7ed', '#c2410c'), status: StatusBadge('suspended', 'Suspended') },
    { name: 'Gamma Co.', ui: Tag('UI', '#ede9ff', '#6d28d9'), api: Tag('API', '#fff7ed', '#c2410c'), status: StatusBadge('expired', 'Expired') }
  ];
  const table = DataTable({ columns, rows, selectable: true, rowActions: [{ label: 'Edit', onClick: () => {} }] });
  container.appendChild(table);
  return container;
}
