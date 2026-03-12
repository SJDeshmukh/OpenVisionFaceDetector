import { FilterBar } from '../components/FilterBar.js';
import { DataTable } from '../components/DataTable.js';

export function TimetablePage() {
  const container = document.createElement('div');
  container.className = 'grid gap-6';

  const filters = FilterBar([
    { label: 'Week', type: 'select', options: [{ value: '2026-03-02', label: 'Mar 2–8' }, { value: '2026-03-09', label: 'Mar 9–15' }] },
    { label: 'Department', type: 'select', options: [{ value: '', label: 'All' }, { value: 'eng', label: 'Engineering' }, { value: 'ops', label: 'Operations' }] }
  ], () => {});
  container.appendChild(filters);

  const columns = [
    { key: 'employee', label: 'Employee' },
    { key: 'shift', label: 'Shift' },
    { key: 'start', label: 'Start' },
    { key: 'end', label: 'End' },
    { key: 'location', label: 'Location' }
  ];
  const rows = [
    { employee: 'Jane Doe', shift: 'Morning', start: '09:00', end: '17:00', location: 'HQ' },
    { employee: 'John Smith', shift: 'Evening', start: '13:00', end: '21:00', location: 'Warehouse' },
    { employee: 'Alice Lee', shift: 'Morning', start: '09:00', end: '17:00', location: 'HQ' }
  ];

  const table = DataTable({ columns, rows, selectable: false, rowActions: [{ label: 'Edit', onClick: () => {} }] });
  container.appendChild(table);
  return container;
}
