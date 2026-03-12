export function FilterBar(filters = [], onApply = () => {}) {
  const bar = document.createElement('div');
  bar.className = 'filter-bar';
  filters.forEach(f => {
    const group = document.createElement('div');
    group.style.display = 'flex';
    group.style.flexWrap = 'nowrap';
    group.style.alignItems = 'center';
    group.style.gap = '6px';
    const label = document.createElement('label');
    label.textContent = f.label;
    label.className = 'text-slate-700';
    let control;
    if (f.type === 'select') {
      control = document.createElement('select');
      control.className = 'select';
      f.options.forEach(opt => {
        const o = document.createElement('option'); o.value = opt.value; o.textContent = opt.label;
        control.appendChild(o);
      });
    } else {
      control = document.createElement('input');
      control.className = 'input';
      control.placeholder = f.placeholder || '';
    }
    control.value = f.value || '';
    control.addEventListener('change', e => f.onChange && f.onChange(e.target.value));
    group.append(label, control);
    bar.appendChild(group);
  });
  const apply = document.createElement('button');
  apply.className = 'filter-action';
  apply.textContent = 'Apply';
  apply.addEventListener('click', () => onApply());
  bar.appendChild(apply);
  return bar;
}
