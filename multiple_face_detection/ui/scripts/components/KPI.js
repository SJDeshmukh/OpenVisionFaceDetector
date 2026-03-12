function iconSVG(color = '#2563eb') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '20'); svg.setAttribute('height', '20'); svg.setAttribute('viewBox', '0 0 24 24');
  const rect = document.createElementNS(svg.namespaceURI, 'rect');
  rect.setAttribute('x', '3'); rect.setAttribute('y', '3'); rect.setAttribute('width', '18'); rect.setAttribute('height', '18');
  rect.setAttribute('rx', '4'); rect.setAttribute('fill', color);
  rect.setAttribute('opacity', '0.15');
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', 'M7 14l3-3 3 3 4-4');
  path.setAttribute('stroke', color); path.setAttribute('stroke-width', '2'); path.setAttribute('fill', 'none'); path.setAttribute('stroke-linecap', 'round'); path.setAttribute('stroke-linejoin', 'round');
  svg.append(rect, path);
  return svg;
}

export function KPIGrid(items = []) {
  const grid = document.createElement('div');
  grid.className = 'kpi-grid';
  items.forEach(({ title, value, subtext, color }) => {
    const card = document.createElement('div');
    card.className = 'card kpi-card';
    const icon = document.createElement('div');
    icon.className = 'kpi-icon';
    icon.appendChild(iconSVG(color));
    const body = document.createElement('div');
    const t = document.createElement('div'); t.className = 'kpi-title'; t.textContent = title;
    const v = document.createElement('div'); v.className = 'kpi-number'; v.textContent = value;
    const s = document.createElement('div'); s.className = 'kpi-subtext'; s.textContent = subtext;
    body.append(t, v, s);
    card.append(icon, body);
    grid.appendChild(card);
  });
  return grid;
}
