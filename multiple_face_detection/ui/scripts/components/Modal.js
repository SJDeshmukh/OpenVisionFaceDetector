export function Modal({ title = 'Modal', content = null, actions = [], wide = false }) {
  const backdrop = document.createElement('div'); backdrop.className = 'modal-backdrop';
  const panel = document.createElement('div'); panel.className = 'modal-panel';
  if (wide) { panel.style.width = '90vw'; }
  const header = document.createElement('div'); header.className = 'modal-header';
  const h = document.createElement('div'); h.className = 'modal-title'; h.textContent = title;
  const close = document.createElement('button'); close.className = 'btn btn-outline'; close.textContent = 'Close';
  close.addEventListener('click', () => backdrop.remove());
  header.append(h, close);
  const body = document.createElement('div'); body.style.marginBottom = '12px';
  body.style.maxHeight = wide ? '75vh' : '70vh';
  body.style.overflowY = 'auto';
  if (content instanceof Node) body.appendChild(content); else body.textContent = content || '';
  const footer = document.createElement('div'); footer.className = 'modal-actions';
  actions.forEach(a => {
    const b = document.createElement('button'); b.className = a.variant === 'primary' ? 'btn btn-primary' : 'btn btn-outline'; b.textContent = a.label;
    b.addEventListener('click', () => a.onClick && a.onClick(backdrop));
    footer.appendChild(b);
  });
  panel.append(header, body, footer);
  backdrop.appendChild(panel);
  return backdrop;
}
