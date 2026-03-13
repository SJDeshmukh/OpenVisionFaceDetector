function showLoader(show) {
  const l = document.getElementById('loader');
  if (show) l.classList.remove('hidden'); else l.classList.add('hidden');
}
const API_BASE = (() => {
  if (typeof window !== 'undefined' && window.API_BASE) return window.API_BASE;
  if (typeof window !== 'undefined') {
    const proto = (window.location.protocol || '').startsWith('http') ? window.location.protocol : 'http:';
    let host = window.location.hostname || '127.0.0.1';
    if (host.includes(':')) host = '127.0.0.1'; // avoid IPv6 literal in URL without brackets
    return `${proto}//${host}:5001`;
  }
  return 'http://127.0.0.1:5001';
})();
function _getToken() {
  try { return localStorage.getItem('ADMIN_TOKEN') || ''; } catch (e) { return ''; }
}
function _setToken(t) {
  try { localStorage.setItem('ADMIN_TOKEN', t || ''); } catch (e) {}
}
async function _ensureAuth() {
  const t = _getToken();
  if (t) return t;
  let email = '';
  let password = '';
  try { email = window.prompt('Admin email'); } catch (e) {}
  try { password = window.prompt('Password'); } catch (e) {}
  if (!email || !password) return '';
  try {
    const r = await fetch(`${API_BASE}/auth_login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
    if (!r.ok) return '';
    const j = await r.json();
    const tok = j && j.token ? j.token : '';
    if (tok) _setToken(tok);
    return tok;
  } catch (e) {
    return '';
  }
}
async function authFetch(url, opts = {}) {
  return fetch(url, Object.assign({}, opts));
}
async function sendImageToBackend(file, options = {}) {
  const form = new FormData();
  form.append('image', file);
  form.append('enhancer', options.enhancer || 'GFPGAN');
  form.append('preclean', String(!!options.preclean));
  form.append('preclean_level', String(options.preclean_level || 0.4));
  form.append('mode', options.mode || 'fast');
  const res = await fetch(`${API_BASE}/detect`, { method: 'POST', body: form });
  if (!res.ok) throw new Error('Request failed');
  const json = await res.json();
  window.detResults = json;
  return json;
}
export async function labelEmbedding(index, name, thumb) {
  if (!window.detResults || !Array.isArray(window.detResults.embeddings)) throw new Error('No embeddings');
  const vec = window.detResults.embeddings[index];
  const res = await authFetch(`${API_BASE}/merge_label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, vector: vec, thumb: thumb || '' })
  });
  if (!res.ok) throw new Error('Label request failed');
  const json = await res.json();
  return json;
}
export async function listLabels() {
  const res = await fetch(`${API_BASE}/labels`);
  if (!res.ok) throw new Error('Labels request failed');
  return res.json();
}
export async function deleteLabel(name) {
  const res = await authFetch(`${API_BASE}/delete_label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  });
  if (!res.ok) throw new Error('Delete label failed');
  return res.json();
}
export async function renameLabel(oldName, newName, vector, thumb) {
  const res = await authFetch(`${API_BASE}/rename_label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old: oldName, new: newName, vector: vector || [], thumb: thumb || '' })
  });
  if (!res.ok) throw new Error('Rename label failed');
  return res.json();
}
export async function getLabelAugments(name) {
  const res = await fetch(`${API_BASE}/label_aug?name=${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error('Label augments failed');
  return res.json();
}
export async function listChunks() {
  const res = await fetch(`${API_BASE}/chunks`);
  if (!res.ok) throw new Error('Chunks request failed');
  return res.json();
}
export async function getChunkImages(id) {
  const res = await fetch(`${API_BASE}/chunk_images?id=${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error('Chunk images request failed');
  return res.json();
}
export async function deleteByChunk(id, name, indices, thr=0.995) {
  const res = await authFetch(`${API_BASE}/delete_by_chunk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, name, indices, thr })
  });
  if (!res.ok) throw new Error('Delete by chunk failed');
  return res.json();
}
export async function approveDetected(threshold = 0.85) {
  const r = window.detResults || {};
  if (!r || !Array.isArray(r.embeddings) || !Array.isArray(r.boxes)) return;
  const names = Array.isArray(r.names) ? r.names : [];
  const imgUrl = r.image || '';
  const baseImg = imgUrl ? await new Promise((resolve) => { const im = new Image(); im.onload = () => resolve(im); im.src = imgUrl; }) : null;
  for (let i = 0; i < r.embeddings.length; i++) {
    const name = names[i] || 'Unknown';
    const b = r.boxes[i];
    const conf = (b && typeof b.score === 'number') ? b.score : 0.0;
    if (!name || name === 'Unknown') continue;
    if (conf < threshold) continue;
    let thumb = '';
    try {
      if (Array.isArray(r.crops) && r.crops[i]) {
        thumb = r.crops[i];
      } else if (baseImg && b) {
        const off = document.createElement('canvas');
        const sx = Math.max(0, b.x1), sy = Math.max(0, b.y1), sw = Math.max(1, b.x2 - b.x1), sh = Math.max(1, b.y2 - b.y1);
        off.width = sw; off.height = sh;
        const octx = off.getContext('2d');
        octx.drawImage(baseImg, sx, sy, sw, sh, 0, 0, sw, sh);
        thumb = off.toDataURL('image/jpeg', 0.85);
      }
    } catch (e) {}
    try {
      const res = await authFetch(`${API_BASE}/merge_label`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, vector: r.embeddings[i], thumb })
      });
      if (!res.ok) { /* ignore */ }
    } catch (e) {}
  }
}
export async function finalizeChunk(id, names) {
  const res = await fetch(`${API_BASE}/finalize_chunk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, names })
  });
  if (!res.ok) throw new Error('Finalize chunk failed');
  return res.json();
}
function initUpload() {
  const input = document.getElementById('uploadInput');
  const btn = document.getElementById('uploadSend');
  if (!input || !btn) return;
  btn.addEventListener('click', async () => {
    if (!input.files || input.files.length === 0) return;
    showLoader(true);
    try {
      await sendImageToBackend(input.files[0], { enhancer: 'GFPGAN', preclean: false, preclean_level: 0.4, mode: 'quality_plus' });
      window.location.hash = '#/attendance';
    } catch (e) {
      try { console.error(e); } catch (_){}
      try { alert('Analyze failed. Ensure the backend is running on port 5001.'); } catch (_){}
    } finally {
      showLoader(false);
    }
  });
}
if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', initUpload);
} else {
  initUpload();
}
