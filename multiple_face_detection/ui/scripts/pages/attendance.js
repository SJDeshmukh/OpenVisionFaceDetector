import { FilterBar } from '../components/FilterBar.js';
import { DataTable } from '../components/DataTable.js';
import { StatusBadge } from '../components/StatusBadge.js';
import { Modal } from '../components/Modal.js';

export function AttendancePage() {
  const container = document.createElement('div');
  container.className = 'grid gap-6';

  const preview = document.createElement('div');
  preview.className = 'card glass';
  const canvas = document.createElement('canvas');
  canvas.style.width = '100%';
  canvas.style.height = '320px';
  canvas.width = 960;
  canvas.height = 320;
  const ctx = canvas.getContext('2d');
  let imgEl = null;
  let imgLoaded = false;
  let boxesData = [];
  let ox = 0, oy = 0, scale = 1;
  let zoomPlaying = false;
  let zoomIndex = 0;
  let zoomStart = 0;
  let holdStart = 0;
  let startRect = { x1: 0, y1: 0, x2: 0, y2: 0 };
  let targetRect = { x1: 0, y1: 0, x2: 0, y2: 0 };
  const ZOOM_DURATION = 0.5;
  const HOLD_DURATION = 0.8;
  const palette = ['#2563eb', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6'];
  function loadData() {
    if (!(window.detResults && window.detResults.image)) return;
    imgEl = new Image();
    imgLoaded = false;
    imgEl.onload = () => {
      scale = Math.min(canvas.width / imgEl.width, canvas.height / imgEl.height);
      const iw = imgEl.width * scale, ih = imgEl.height * scale;
      ox = (canvas.width - iw) / 2; oy = (canvas.height - ih) / 2;
      imgLoaded = true;
      startRect = { x1: 0, y1: 0, x2: imgEl.width, y2: imgEl.height };
      targetRect = { x1: 0, y1: 0, x2: imgEl.width, y2: imgEl.height };
    };
    imgEl.src = window.detResults.image;
    boxesData = Array.isArray(window.detResults.boxes) ? window.detResults.boxes : [];
  }
  loadData();
  let lastHash = JSON.stringify(window.detResults || {});
  function animate() {
    const now = performance.now() / 1000;
    const currentHash = JSON.stringify(window.detResults || {});
    if (currentHash !== lastHash) {
      lastHash = currentHash;
      loadData();
    }
    ctx.clearRect(0,0,canvas.width,canvas.height);
    if (imgLoaded) {
      let sx = 0, sy = 0, sw = imgEl.width, sh = imgEl.height;
      if (zoomPlaying && boxesData.length > 0) {
        const tRaw = Math.min((now - zoomStart) / ZOOM_DURATION, 1);
        const t = tRaw * tRaw * (3 - 2 * tRaw);
        sx = Math.round((1 - t) * startRect.x1 + t * targetRect.x1);
        sy = Math.round((1 - t) * startRect.y1 + t * targetRect.y1);
        sw = Math.max(1, Math.round((1 - t) * (startRect.x2 - startRect.x1) + t * (targetRect.x2 - targetRect.x1)));
        sh = Math.max(1, Math.round((1 - t) * (startRect.y2 - startRect.y1) + t * (targetRect.y2 - targetRect.y1)));
        if (tRaw >= 1) {
          if (holdStart === 0) holdStart = now;
          if (now - holdStart >= HOLD_DURATION) {
            zoomIndex = (zoomIndex + 1) % boxesData.length;
            const b = boxesData[zoomIndex];
            const sw0 = b.x2 - b.x1, sh0 = b.y2 - b.y1;
            const padX = Math.round(sw0 * 0.25), padY = Math.round(sh0 * 0.25);
            const nx1 = Math.max(0, b.x1 - padX);
            const ny1 = Math.max(0, b.y1 - padY);
            const nx2 = Math.min(imgEl.width, b.x2 + padX);
            const ny2 = Math.min(imgEl.height, b.y2 + padY);
            startRect = { x1: sx, y1: sy, x2: sx + sw, y2: sy + sh };
            targetRect = { x1: nx1, y1: ny1, x2: nx2, y2: ny2 };
            zoomStart = now;
            holdStart = 0;
          }
        }
      } else {
        sx = 0; sy = 0; sw = imgEl.width; sh = imgEl.height;
      }
      ctx.drawImage(imgEl, sx, sy, sw, sh, ox, oy, imgEl.width * scale, imgEl.height * scale);
      ctx.setLineDash([8, 6]);
      ctx.shadowColor = 'rgba(79,140,255,0.6)';
      ctx.lineDashOffset = -now * 40;
      boxesData.forEach((b, i) => {
        const c = palette[i % palette.length];
        const pulse = 0.5 + 0.5 * Math.sin(now * 1.2 + i);
        ctx.globalAlpha = 0.6 + 0.4 * pulse;
        ctx.lineWidth = 2 + 2 * pulse;
        ctx.shadowBlur = 6 + 6 * pulse;
        ctx.strokeStyle = c;
        const x = ox + b.x1 * scale, y = oy + b.y1 * scale, w = (b.x2 - b.x1) * scale, h = (b.y2 - b.y1) * scale;
        ctx.strokeRect(x, y, w, h);
        if (window.detResults && Array.isArray(window.detResults.mesh) && window.detResults.mesh[i] && window.detResults.mesh[i].length > 0) {
          ctx.fillStyle = c;
          ctx.globalAlpha = 0.9;
          const pts = window.detResults.mesh[i];
          for (let k = 0; k < pts.length; k += 6) {
            const px = ox + pts[k].x * scale;
            const py = oy + pts[k].y * scale;
            ctx.beginPath();
            ctx.arc(px, py, 2, 0, Math.PI * 2);
            ctx.fill();
          }
          ctx.globalAlpha = 1.0;
        }
      });
      ctx.globalAlpha = 1.0;
      ctx.setLineDash([]);
      ctx.shadowBlur = 0;
    }
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
  preview.appendChild(canvas);
  container.appendChild(preview);

  const actionBar = document.createElement('div');
  actionBar.className = 'action-bar';
  const exportBtn = document.createElement('button'); exportBtn.className = 'btn-pastel blue'; exportBtn.textContent = 'Export';
  const markLate = document.createElement('button'); markLate.className = 'btn-pastel orange'; markLate.textContent = 'Mark Late';
  const markPresent = document.createElement('button'); markPresent.className = 'btn-pastel green'; markPresent.textContent = 'Mark Present';
  const zoomBtn = document.createElement('button'); zoomBtn.className = 'btn-pastel purple'; zoomBtn.textContent = 'Play Zoom';
  zoomBtn.addEventListener('click', () => {
    if (!imgLoaded || boxesData.length === 0) return;
    if (!zoomPlaying) {
      zoomPlaying = true;
      zoomIndex = 0;
      const b = boxesData[zoomIndex];
      const sw0 = b.x2 - b.x1, sh0 = b.y2 - b.y1;
      const padX = Math.round(sw0 * 0.25), padY = Math.round(sh0 * 0.25);
      const nx1 = Math.max(0, b.x1 - padX);
      const ny1 = Math.max(0, b.y1 - padY);
      const nx2 = Math.min(imgEl.width, b.x2 + padX);
      const ny2 = Math.min(imgEl.height, b.y2 + padY);
      startRect = { x1: 0, y1: 0, x2: imgEl.width, y2: imgEl.height };
      targetRect = { x1: nx1, y1: ny1, x2: nx2, y2: ny2 };
      zoomStart = performance.now() / 1000;
      holdStart = 0;
      zoomBtn.textContent = 'Stop Zoom';
    } else {
      zoomPlaying = false;
      zoomBtn.textContent = 'Play Zoom';
      startRect = { x1: 0, y1: 0, x2: imgEl.width, y2: imgEl.height };
      targetRect = { x1: 0, y1: 0, x2: imgEl.width, y2: imgEl.height };
    }
  });
  actionBar.append(exportBtn, markLate, markPresent, zoomBtn);
  container.appendChild(actionBar);

  const filters = FilterBar([
    { label: 'Department', type: 'select', options: [{ value: '', label: 'All' }, { value: 'eng', label: 'Engineering' }, { value: 'ops', label: 'Operations' }] },
    { label: 'Date', type: 'input', placeholder: 'YYYY-MM-DD' },
    { label: 'Shift', type: 'select', options: [{ value: '', label: 'Any' }, { value: 'morning', label: 'Morning' }, { value: 'evening', label: 'Evening' }] }
  ], () => {});
  container.appendChild(filters);

  const columns = [
    { key: 'employee', label: 'ID' },
    { key: 'name', label: 'Name' },
    { key: 'status', label: 'Status' },
    { key: 'liveness', label: 'Liveness' },
    { key: 'confidence', label: 'Confidence' },
    { key: 'label', label: 'Label' },
    { key: 'face', label: 'Face' }
  ];
  let rows = [
    { employee: 'Jane Doe', date: '2026-03-01', time: '09:01', activity: 'Clock In', status: StatusBadge('active', 'Present'), confidence: '0.97' }
  ];
  function showRelabelToast(idx, currentName, triggerEl) {
    const content = document.createElement('div');
    content.style.display = 'grid';
    content.style.gap = '8px';
    const previewWrap = document.createElement('div');
    previewWrap.style.display = 'flex';
    previewWrap.style.alignItems = 'center';
    previewWrap.style.gap = '12px';
    const previewImg = document.createElement('img');
    const latestName = (window.detResults && window.detResults.names && window.detResults.names[idx]) ? window.detResults.names[idx] : currentName;
    previewImg.alt = latestName || 'Face';
    previewImg.style.width = '72px';
    previewImg.style.height = '72px';
    previewImg.style.objectFit = 'cover';
    previewImg.style.borderRadius = '10px';
    previewImg.style.border = '1px solid var(--slate-200)';
    let srcSet = false;
    if (triggerEl && triggerEl.tagName === 'IMG' && triggerEl.src) {
      previewImg.src = triggerEl.src;
      srcSet = true;
    }
    if (!srcSet && window.detResults && window.detResults.crops && window.detResults.crops[idx]) {
      previewImg.src = window.detResults.crops[idx];
      srcSet = true;
    }
    if (!srcSet && window.detResults && window.detResults.image && window.detResults.boxes && window.detResults.boxes[idx]) {
      try {
        const baseImg = new Image();
        baseImg.onload = () => {
          const b = window.detResults.boxes[idx];
          const off = document.createElement('canvas');
          const sx = b.x1, sy = b.y1, sw = b.x2 - b.x1, sh = b.y2 - b.y1;
          off.width = Math.max(1, sw); off.height = Math.max(1, sh);
          const octx = off.getContext('2d');
          octx.drawImage(baseImg, sx, sy, sw, sh, 0, 0, sw, sh);
          previewImg.src = off.toDataURL('image/jpeg', 0.85);
        };
        baseImg.src = window.detResults.image;
        srcSet = true;
      } catch (e) {}
    }
    previewWrap.appendChild(previewImg);
    const title = document.createElement('div');
    title.className = 'font-bold text-slate-800';
    title.textContent = ((window.detResults && window.detResults.names && window.detResults.names[idx]) ? window.detResults.names[idx] : currentName) || 'Unknown';
    const input = document.createElement('input');
    input.className = 'input';
    input.placeholder = 'Enter name';
    input.value = ((window.detResults && window.detResults.names && window.detResults.names[idx]) ? window.detResults.names[idx] : currentName) || '';
    content.append(previewWrap, title, input);
    const modal = Modal({
      title: 'Relabel Face',
      content,
      actions: [
        { label: 'Save', variant: 'primary', onClick: async (backdrop) => {
            const val = input.value.trim();
            if (!val) return;
            try {
              if (!window.detResults.names) window.detResults.names = [];
              window.detResults.names[idx] = val;
              try {
                const tr = triggerEl && triggerEl.closest('tr');
                if (tr) {
                  const tds = tr.querySelectorAll('td');
                  if (tds && tds[1]) tds[1].textContent = val;
                  if (tds && tds[5]) {
                    tds[5].innerHTML = '';
                    const pill = document.createElement('span');
                    pill.className = 'filter-chip';
                    pill.textContent = val;
                    pill.style.cursor = 'pointer';
                    pill.addEventListener('click', () => showRelabelToast(idx, val, pill));
                    tds[5].appendChild(pill);
                  }
                }
              } catch (e) {}
            } catch (e) {}
            backdrop.remove();
          } },
        { label: 'Cancel', variant: 'outline', onClick: (backdrop) => backdrop.remove() }
      ]
    });
    document.getElementById('modalRoot').appendChild(modal);
  }
  if (window.detResults && Array.isArray(window.detResults.boxes)) {
    rows = window.detResults.boxes.map((b, i) => {
      const conf = b.score || 0.9;
      const st = conf > 0.8 ? StatusBadge('active', 'Present') : StatusBadge('expired', 'Uncertain');
      const name = (window.detResults.names && window.detResults.names[i]) ? window.detResults.names[i] : 'Unknown';
      let live = null;
      if (window.detResults && Array.isArray(window.detResults.spoof) && typeof window.detResults.spoof[i] === 'number') {
        const s = window.detResults.spoof[i];
        live = s >= 0.65 ? StatusBadge('active', 'Live') : StatusBadge('expired', 'Suspect');
      } else {
        live = StatusBadge('expired', 'Unknown');
      }
      const labelBox = document.createElement('div');
      if (name === 'Unknown') {
        const input = document.createElement('input'); input.className = 'input'; input.placeholder = 'Enter name';
        const save = document.createElement('button'); save.className = 'btn btn-primary'; save.textContent = 'Save';
        save.addEventListener('click', async () => {
          const val = input.value.trim();
          if (!val) return;
          if (!window.detResults.names) window.detResults.names = [];
          window.detResults.names[i] = val;
          input.disabled = true; save.disabled = true; save.textContent = 'Saved';
          try {
            const tr = save.closest('tr');
            if (tr) {
              const tds = tr.querySelectorAll('td');
              if (tds && tds[1]) tds[1].textContent = val; // update Name cell
              if (tds && tds[5]) {
                tds[5].innerHTML = '';
                const pill = document.createElement('span');
                pill.className = 'filter-chip';
                pill.textContent = val;
                pill.style.cursor = 'pointer';
                pill.addEventListener('click', () => showRelabelToast(i, val, pill));
                tds[5].appendChild(pill);
              }
            }
          } catch (e) {}
        });
        labelBox.append(input, save);
      } else {
        const pill = document.createElement('span'); pill.className = 'filter-chip'; pill.textContent = name;
        pill.style.cursor = 'pointer';
        pill.addEventListener('click', () => showRelabelToast(i, undefined, pill));
        const editBtn = document.createElement('button');
        editBtn.className = 'btn-pastel blue';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', () => showRelabelToast(i, undefined, editBtn));
        labelBox.appendChild(pill);
        labelBox.appendChild(editBtn);
      }
      let faceNode = document.createElement('div');
      if (window.detResults && window.detResults.image) {
        try {
          const baseImg = new Image();
          baseImg.onload = () => {
            const off = document.createElement('canvas');
            const sw0 = b.x2 - b.x1, sh0 = b.y2 - b.y1;
            const padX = Math.round(sw0 * 0.25), padY = Math.round(sh0 * 0.25);
            const sx = Math.max(0, b.x1 - padX);
            const sy = Math.max(0, b.y1 - padY);
            const ex = Math.min(baseImg.width, b.x2 + padX);
            const ey = Math.min(baseImg.height, b.y2 + padY);
            const sw = Math.max(1, ex - sx), sh = Math.max(1, ey - sy);
            off.width = sw; off.height = sh;
            const octx = off.getContext('2d');
            octx.drawImage(baseImg, sx, sy, sw, sh, 0, 0, sw, sh);
            const dataUrl = off.toDataURL('image/jpeg', 0.85);
            const img = document.createElement('img');
            img.src = dataUrl;
            img.alt = (window.detResults.names && window.detResults.names[i]) ? window.detResults.names[i] : name;
            img.style.width = '48px';
            img.style.height = '48px';
            img.style.objectFit = 'cover';
            img.style.borderRadius = '8px';
            img.style.border = '1px solid var(--slate-200)';
            img.style.cursor = 'pointer';
            img.addEventListener('click', () => showRelabelToast(i, undefined, img));
            faceNode.appendChild(img);
          };
          baseImg.src = window.detResults.image;
        } catch (e) {}
      }
      const idText = (window.detResults.tracks && window.detResults.tracks[i]) ? `#${window.detResults.tracks[i]}` : `Face ${i+1}`;
      return { employee: idText, name, status: st, liveness: live, confidence: conf.toFixed(2), label: labelBox, face: faceNode };
    });
  }

  const table = DataTable({ columns, rows, selectable: false, rowActions: [] });
  container.appendChild(table);
  if (window.detResults && Array.isArray(window.detResults.boxes) && window.detResults.boxes.length > 0) {
    const banner = document.createElement('div');
    banner.textContent = 'Press Complete to save all the things';
    banner.style.width = '100%';
    banner.style.background = '#0ea5e9';
    banner.style.color = '#ffffff';
    banner.style.fontSize = '12px';
    banner.style.padding = '6px 12px';
    banner.style.borderBottom = '1px solid var(--slate-300)';
    banner.style.boxShadow = '0 1px 0 rgba(0,0,0,0.05)';
    container.insertBefore(banner, container.firstChild);
  }
  const completeBar = document.createElement('div');
  completeBar.style.display = 'flex';
  completeBar.style.justifyContent = 'flex-end';
  completeBar.style.padding = '8px';
  const completeBtn = document.createElement('button');
  completeBtn.textContent = 'Complete';
  completeBtn.className = 'btn';
  completeBtn.style.background = '#16a34a';
  completeBtn.style.color = '#fff';
  completeBtn.style.borderColor = 'transparent';
  completeBtn.addEventListener('click', async () => {
    try {
      const { finalizeChunk, labelEmbedding } = await import('../api.js');
      const r = window.detResults || {};
      const cid = r && r.chunk ? r.chunk : null;
      if (cid) {
        await finalizeChunk(cid, Array.isArray(r.names) ? r.names : []);
      } else {
        for (let i = 0; i < (r.embeddings || []).length; i++) {
          const nm = (r.names && r.names[i]) ? r.names[i] : '';
          if (!nm || nm === 'Unknown') continue;
          const thumb = (r.crops && r.crops[i]) ? r.crops[i] : '';
          try { await labelEmbedding(i, nm, thumb); } catch (e) {}
        }
      }
      const modal = Modal({ title: 'Complete', content: 'Embeddings stored and model updated.', actions: [{ label: 'Close', variant: 'outline', onClick: (b) => b.remove() }] });
      document.getElementById('modalRoot').appendChild(modal);
    } catch (e) {}
  });
  completeBar.appendChild(completeBtn);
  container.appendChild(completeBar);
  if (window.detResults && Array.isArray(window.detResults.boxes) && window.detResults.boxes.length > 0) {
    try {
      document.querySelectorAll('button').forEach(b => {
        if (b !== completeBtn) {
          b.disabled = true;
          b.style.opacity = '0.6';
          b.style.cursor = 'not-allowed';
        }
      });
    } catch (e) {}
  }
  return container;
}
