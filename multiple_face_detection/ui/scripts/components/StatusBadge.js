export function StatusBadge(state = 'active', label = 'Active') {
  const badge = document.createElement('span');
  badge.className = `status-badge ${state === 'active' ? 'status-active' : state === 'suspended' ? 'status-suspended' : 'status-expired'}`;
  badge.textContent = label;
  return badge;
}
