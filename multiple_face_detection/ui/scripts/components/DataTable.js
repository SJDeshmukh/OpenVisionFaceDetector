export function DataTable({ columns = [], rows = [], selectable = false, rowActions = [] }) {
  const table = document.createElement('table');
  table.className = 'table';
  const thead = document.createElement('thead');
  const trh = document.createElement('tr');
  if (selectable) {
    const th = document.createElement('th');
    th.style.width = '36px';
    const cb = document.createElement('input'); cb.type = 'checkbox';
    th.appendChild(cb);
    trh.appendChild(th);
  }
  columns.forEach(c => {
    const th = document.createElement('th'); th.textContent = c.label.toUpperCase(); trh.appendChild(th);
  });
  if (rowActions.length > 0) {
    const th = document.createElement('th'); th.textContent = 'ACTIONS'; trh.appendChild(th);
  }
  thead.appendChild(trh);
  const tbody = document.createElement('tbody');
  rows.forEach(r => {
    const tr = document.createElement('tr');
    if (selectable) {
      const td = document.createElement('td');
      const cb = document.createElement('input'); cb.type = 'checkbox';
      td.appendChild(cb);
      tr.appendChild(td);
    }
    columns.forEach(c => {
      const td = document.createElement('td');
      const val = r[c.key];
      if (val instanceof Node) td.appendChild(val);
      else td.textContent = val;
      tr.appendChild(td);
    });
    if (rowActions.length > 0) {
      const td = document.createElement('td');
      const actions = document.createElement('div'); actions.className = 'table-actions';
      rowActions.forEach(action => {
        const b = document.createElement('button'); b.className = 'btn btn-outline'; b.textContent = action.label;
        b.addEventListener('click', () => action.onClick && action.onClick(r));
        actions.appendChild(b);
      });
      td.appendChild(actions);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
  return table;
}
