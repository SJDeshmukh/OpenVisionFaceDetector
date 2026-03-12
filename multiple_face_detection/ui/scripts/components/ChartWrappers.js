function createSVG(width, height) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', width); svg.setAttribute('height', height); svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  return svg;
}

function drawGrid(svg, width, height, step = 40) {
  for (let x = step; x < width; x += step) {
    const line = document.createElementNS(svg.namespaceURI, 'line');
    line.setAttribute('x1', x); line.setAttribute('y1', 0);
    line.setAttribute('x2', x); line.setAttribute('y2', height);
    line.setAttribute('stroke', '#e2e8f0'); line.setAttribute('stroke-width', '1');
    svg.appendChild(line);
  }
  for (let y = step; y < height; y += step) {
    const line = document.createElementNS(svg.namespaceURI, 'line');
    line.setAttribute('x1', 0); line.setAttribute('y1', y);
    line.setAttribute('x2', width); line.setAttribute('y2', y);
    line.setAttribute('stroke', '#e2e8f0'); line.setAttribute('stroke-width', '1');
    svg.appendChild(line);
  }
}

export function AreaChart({ data = [] }) {
  const card = document.createElement('div'); card.className = 'chart-card';
  const svg = createSVG(600, 240); svg.classList.add('chart');
  drawGrid(svg, 600, 240);
  const grad = document.createElementNS(svg.namespaceURI, 'linearGradient'); grad.setAttribute('id', 'areaGrad'); grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0'); grad.setAttribute('x2', '0'); grad.setAttribute('y2', '1');
  const stop1 = document.createElementNS(svg.namespaceURI, 'stop'); stop1.setAttribute('offset', '0%'); stop1.setAttribute('stop-color', 'rgba(37,99,235,0.35)');
  const stop2 = document.createElementNS(svg.namespaceURI, 'stop'); stop2.setAttribute('offset', '100%'); stop2.setAttribute('stop-color', 'rgba(37,99,235,0.05)');
  grad.append(stop1, stop2);
  const defs = document.createElementNS(svg.namespaceURI, 'defs'); defs.appendChild(grad); svg.appendChild(defs);
  const path = document.createElementNS(svg.namespaceURI, 'path');
  const maxY = Math.max(...data.map(d => d.y), 1);
  const scaleX = 600 / Math.max(data.length - 1, 1);
  const scaleY = 200 / maxY;
  let d = `M 0 ${240 - data[0].y * scaleY}`;
  data.forEach((p, i) => { d += ` L ${i * scaleX} ${240 - p.y * scaleY}`; });
  d += ` L 600 240 L 0 240 Z`;
  path.setAttribute('d', d);
  path.setAttribute('fill', 'url(#areaGrad)');
  path.setAttribute('stroke', '#2563eb'); path.setAttribute('stroke-width', '2'); path.setAttribute('fill-opacity', '1');
  svg.appendChild(path);
  card.appendChild(svg);
  return card;
}

export function BarChart({ data = [] }) {
  const card = document.createElement('div'); card.className = 'chart-card';
  const svg = createSVG(600, 240); svg.classList.add('chart');
  drawGrid(svg, 600, 240);
  const maxY = Math.max(...data.map(d => d.y), 1);
  const barW = Math.max(20, Math.floor(500 / data.length));
  const gap = 10;
  data.forEach((p, i) => {
    const h = (p.y / maxY) * 200;
    const rect = document.createElementNS(svg.namespaceURI, 'rect');
    rect.setAttribute('x', 40 + i * (barW + gap)); rect.setAttribute('y', 240 - h);
    rect.setAttribute('width', barW); rect.setAttribute('height', h);
    rect.setAttribute('rx', '4');
    rect.setAttribute('fill', '#f59e0b');
    svg.appendChild(rect);
  });
  card.appendChild(svg);
  return card;
}
