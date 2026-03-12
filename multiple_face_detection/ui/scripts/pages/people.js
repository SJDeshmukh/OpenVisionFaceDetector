import { FilterBar } from '../components/FilterBar.js';
import { DataTable } from '../components/DataTable.js';
import { StatusBadge } from '../components/StatusBadge.js';
import { Modal } from '../components/Modal.js';

export function PeoplePage() {
  const container = document.createElement('div');
  container.className = 'grid gap-6';

  const filters = FilterBar([
    { label: 'Search', type: 'input', placeholder: 'Name' }
  ], () => {});
  container.appendChild(filters);

  const columns = [
    { key: 'name', label: 'Name' },
    { key: 'dim', label: 'Dim' },
    { key: 'status', label: 'Status' },
    { key: 'face', label: 'Face' }
  ];
  let rows = [];
  async function refresh() {
    try {
      const { listLabels } = await import('../api.js');
      const data = await listLabels();
      rows = (data.items || []).map(it => {
        const wrap = document.createElement('div');
        wrap.style.display = 'flex';
        wrap.style.alignItems = 'center';
        const img = document.createElement('img');
        img.src = it.thumb || '';
        img.alt = it.name || '';
        img.style.width = '64px';
        img.style.height = '64px';
        img.style.objectFit = 'contain';
        img.style.background = '#0f172a';
        img.style.padding = '2px';
        img.style.borderRadius = '8px';
        img.style.border = '1px solid var(--slate-200)';
        img.style.cursor = 'pointer';
        img.addEventListener('click', () => {
          const view = document.createElement('div');
          const big = document.createElement('img');
          big.src = img.src;
          big.alt = it.name || '';
          big.style.width = '256px';
          big.style.height = '256px';
          big.style.objectFit = 'contain';
          big.style.borderRadius = '12px';
          big.style.border = '1px solid var(--slate-200)';
          big.style.background = '#0f172a';
          view.appendChild(big);
          const modal = Modal({
            title: it.name || 'Face',
            content: view,
            actions: [
              { label: 'Close', variant: 'outline', onClick: (backdrop) => backdrop.remove() }
            ]
          });
          document.getElementById('modalRoot').appendChild(modal);
        });
        const fallback = document.createElement('div');
        fallback.textContent = (it.name || '?').slice(0,1).toUpperCase();
        fallback.style.width = '48px';
        fallback.style.height = '48px';
        fallback.style.display = 'inline-flex';
        fallback.style.alignItems = 'center';
        fallback.style.justifyContent = 'center';
        fallback.style.borderRadius = '8px';
        fallback.style.background = 'linear-gradient(135deg, #1e293b, #334155)';
        fallback.style.color = '#e5e7eb';
        fallback.style.border = '1px solid var(--slate-200)';
        img.addEventListener('error', () => { img.style.display = 'none'; wrap.appendChild(fallback); });
        wrap.appendChild(img);
        return { name: it.name, dim: String(it.dim || 0), status: StatusBadge('active', 'Registered'), face: wrap };
      });
      render();
    } catch (e) {
      rows = [];
      render();
    }
  }
  function render() {
    container.querySelectorAll('.table').forEach(t => t.remove());
    const table = DataTable({ columns, rows, selectable: true, rowActions: [
      { label: 'Delete', onClick: async (row) => {
        const content = document.createElement('div'); content.textContent = `Delete '${row.name}'?`;
        const modal = Modal({
          title: 'Confirm Delete',
          content,
          actions: [
            { label: 'Delete', variant: 'primary', onClick: async (backdrop) => {
              try {
                const { deleteLabel } = await import('../api.js');
                await deleteLabel(row.name);
              } catch (e) {}
              backdrop.remove();
              refresh();
            } },
            { label: 'Cancel', variant: 'outline', onClick: (backdrop) => backdrop.remove() }
          ]
        });
        document.getElementById('modalRoot').appendChild(modal);
      } },
      { label: 'Edit', onClick: async (row) => {
        const wrap = document.createElement('div');
        const input = document.createElement('input'); input.className = 'input'; input.value = row.name;
        wrap.appendChild(input);
        const modal = Modal({
          title: 'Edit Name',
          content: wrap,
          actions: [
            { label: 'Save', variant: 'primary', onClick: async (backdrop) => {
              const val = input.value.trim();
              if (!val) { backdrop.remove(); return; }
              try {
                const { renameLabel } = await import('../api.js');
                await renameLabel(row.name, val);
              } catch (e) {}
              backdrop.remove();
              refresh();
            } },
            { label: 'Cancel', variant: 'outline', onClick: (backdrop) => backdrop.remove() }
          ]
        });
        document.getElementById('modalRoot').appendChild(modal);
      } },
      { label: 'Chunks', onClick: async (row) => {
        try {
          const { listChunks, getChunkImages } = await import('../api.js');
          const data = await listChunks();
          const items = (data.items || []).filter(it => (it.names || []).includes(row.name));
          const body = document.createElement('div');
          body.style.display = 'grid';
          body.style.gridTemplateColumns = '280px 1fr';
          body.style.gap = '12px';
          const left = document.createElement('div');
          left.style.display = 'flex';
          left.style.flexDirection = 'column';
          left.style.gap = '8px';
          const right = document.createElement('div');
          right.style.display = 'grid';
          right.style.gridTemplateColumns = 'repeat(5, 1fr)';
          right.style.gap = '8px';
          right.style.paddingRight = '6px';
          function loadChunk(id) {
            getChunkImages(id).then(r => {
              const items = r.items || [];
              const names = r.names || [];
              const portraits = r.portraits || [];
              const pnames = r.portraits_names || names || [];
              const aug = r.augments || [];
              const anames = r.augments_names || [];
              right.innerHTML = '';
              const header = document.createElement('div');
              header.style.display = 'flex';
              header.style.justifyContent = 'flex-end';
              header.style.gap = '8px';
              const delBtn = document.createElement('button');
              delBtn.className = 'btn btn-primary';
              delBtn.textContent = 'Delete Selected';
              delBtn.disabled = true;
              header.appendChild(delBtn);
              right.appendChild(header);
              const selected = new Set();
              function add(imgSrc, opts = {}) {
                const img = document.createElement('img');
                img.src = imgSrc;
                img.style.width = '100%';
                img.style.height = (opts.height || 160) + 'px';
                img.style.objectFit = opts.objectFit || 'cover';
                img.style.background = '#0f172a';
                img.style.borderRadius = '8px';
                img.style.border = '1px solid var(--slate-200)';
                right.appendChild(img);
              }
              // portraits first (whole face)
              for (let i = 0; i < portraits.length; i++) {
                if (pnames[i] && pnames[i] !== row.name) continue;
                if (portraits[i]) add(portraits[i], { height: 220, objectFit: 'contain' });
              }
              // original crops
              for (let i = 0; i < items.length; i++) {
                if (names[i] && names[i] !== row.name) continue;
                if (items[i]) {
                  const img = document.createElement('img');
                  img.src = items[i];
                  img.style.width = '100%';
                  img.style.height = '160px';
                  img.style.objectFit = 'cover';
                  img.style.background = '#0f172a';
                  img.style.borderRadius = '8px';
                  img.style.border = '1px solid var(--slate-200)';
                  img.style.cursor = 'pointer';
                  img.addEventListener('click', () => {
                    if (selected.has(i)) { selected.delete(i); img.style.outline = 'none'; }
                    else { selected.add(i); img.style.outline = '3px solid #ef4444'; }
                    delBtn.disabled = selected.size === 0;
                  });
                  right.appendChild(img);
                }
              }
              // augmentations
              for (let i = 0; i < aug.length; i++) {
                if (anames[i] && anames[i] !== row.name) continue;
                if (aug[i]) add(aug[i], { height: 160, objectFit: 'cover' });
              }
              delBtn.addEventListener('click', async () => {
                if (selected.size === 0) return;
                try {
                  const { deleteByChunk } = await import('../api.js');
                  const res = await deleteByChunk(id, row.name, Array.from(selected));
                  delBtn.disabled = true;
                  selected.clear();
                  // Reload to reflect changes
                  loadChunk(id);
                } catch (e) {
                  delBtn.disabled = false;
                }
              });
            }).catch(() => { right.innerHTML = ''; });
          }
          items.forEach(it => {
            const b = document.createElement('button');
            b.className = 'btn btn-outline';
            const t = new Date((it.ts || 0) * 1000);
            const label = `${t.toLocaleTimeString()} • ${it.count || 0}`;
            b.textContent = label;
            b.addEventListener('click', () => loadChunk(it.id));
            left.appendChild(b);
          });
          if (items[0]) loadChunk(items[0].id);
          body.append(left, right);
          const modal = Modal({
            title: `Chunks: ${row.name}`,
            content: body,
            actions: [{ label: 'Close', variant: 'outline', onClick: (backdrop) => backdrop.remove() }],
            wide: true
          });
          document.getElementById('modalRoot').appendChild(modal);
        } catch (e) {}
      } },
      { label: 'Augments', onClick: async (row) => {
        try {
          const { getLabelAugments } = await import('../api.js');
          const data = await getLabelAugments(row.name);
          const grid = document.createElement('div');
          grid.style.display = 'grid';
          grid.style.gridTemplateColumns = 'repeat(auto-fill, minmax(140px, 1fr))';
          grid.style.gap = '8px';
          (data.items || []).forEach(src => {
            const img = document.createElement('img');
            img.src = src;
            img.style.width = '100%';
            img.style.height = '120px';
            img.style.objectFit = 'contain';
            img.style.border = '1px solid var(--slate-200)';
            img.style.borderRadius = '8px';
            grid.appendChild(img);
          });
          const modal = Modal({
            title: `Augments: ${row.name}`,
            content: grid,
            actions: [{ label: 'Close', variant: 'outline', onClick: (backdrop) => backdrop.remove() }],
            wide: true
          });
          document.getElementById('modalRoot').appendChild(modal);
        } catch (e) {}
      } }
    ] });
    container.appendChild(table);
  }
  refresh();
  return container;
}
