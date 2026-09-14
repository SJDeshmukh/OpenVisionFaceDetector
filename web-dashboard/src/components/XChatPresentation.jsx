import { useRef, useState } from 'react';
import axios from 'axios';
import { BarChart3, Download, FileDown, FileSpreadsheet, Loader2 } from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { API_URL } from '../config';

const COLORS = ['#22d3ee', '#818cf8', '#f59e0b', '#34d399', '#fb7185', '#a78bfa', '#60a5fa', '#f472b6'];

const downloadBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

const csvValue = (value) => {
  let safe = value == null ? '' : String(value);
  if (/^[=+\-@]/.test(safe)) safe = `'${safe}`;
  return `"${safe.replaceAll('"', '""')}"`;
};

const downloadCsv = (columns, rows, filename) => {
  const headers = [{ key: 'index', label: '#' }, ...columns];
  const content = [
    headers.map((column) => csvValue(column.label)).join(','),
    ...rows.map((row) => headers.map((column) => csvValue(row[column.key])).join(',')),
  ].join('\r\n');
  downloadBlob(new Blob([`\ufeff${content}`], { type: 'text/csv;charset=utf-8' }), filename || 'xchat-data.csv');
};

const formatValue = (value, column = {}) => {
  if (value == null || value === '') return '—';
  if (column.format === 'currency') {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: column.currency || 'INR', maximumFractionDigits: 2 }).format(Number(value));
  }
  if (column.format === 'percent') return `${Number(value).toLocaleString('en-IN')}%`;
  if (column.format === 'hours') return `${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })} h`;
  if (column.format === 'number') return Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  if (column.format === 'datetime') {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('en-IN');
  }
  return String(value);
};

const InlineText = ({ text }) => {
  if (!text) return null;
  // Support inline code (`...`), bold (**...**), italic (*...*)
  const parts = String(text).split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code key={index} className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-cyan-300">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={index} className="font-semibold text-slate-100">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return (
        <em key={index} className="italic text-slate-300">
          {part.slice(1, -1)}
        </em>
      );
    }
    return <span key={index}>{part}</span>;
  });
};

const parseCells = (rowStr) => {
  const trimmed = rowStr.trim();
  const parts = trimmed.split('|').map((p) => p.trim());
  if (parts.length > 0 && parts[0] === '') parts.shift();
  if (parts.length > 0 && parts[parts.length - 1] === '') parts.pop();
  return parts;
};

const isTableSeparator = (line) => {
  const trimmed = line.trim();
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(trimmed);
};

const isTableRow = (line) => {
  const trimmed = line.trim();
  return trimmed.includes('|') && !trimmed.startsWith('#');
};

export const FormattedText = ({ children }) => {
  const lines = String(children || '').split('\n');
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    const line = rawLine.trim();

    if (!line) {
      blocks.push({ type: 'spacer', key: `space-${i}` });
      i += 1;
      continue;
    }

    // 1. Table Detection
    if (isTableRow(line) && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const headers = parseCells(line);
      const sepCells = parseCells(lines[i + 1]);
      const alignments = sepCells.map((cell) => {
        if (cell.startsWith(':') && cell.endsWith(':')) return 'text-center';
        if (cell.endsWith(':')) return 'text-right';
        return 'text-left';
      });

      i += 2;
      const rows = [];
      while (i < lines.length && isTableRow(lines[i]) && !isTableSeparator(lines[i])) {
        const rowCells = parseCells(lines[i]);
        if (rowCells.length > 0) {
          rows.push(rowCells);
        }
        i += 1;
      }

      blocks.push({
        type: 'table',
        key: `table-${i}`,
        headers,
        alignments,
        rows,
      });
      continue;
    }

    // 2. Orphaned bullet character (e.g. • or - on its own line followed by text)
    if ((line === '•' || line === '-' || line === '*') && i + 1 < lines.length && lines[i + 1].trim()) {
      i += 1;
      blocks.push({
        type: 'bullet',
        key: `bullet-${i}`,
        text: lines[i].trim(),
      });
      i += 1;
      continue;
    }

    // 3. Regular bullet point (- item, * item, • item)
    const bulletMatch = line.match(/^[-*•]\s+(.+)/);
    if (bulletMatch) {
      blocks.push({
        type: 'bullet',
        key: `bullet-${i}`,
        text: bulletMatch[1],
      });
      i += 1;
      continue;
    }

    // 4. Numbered list (1. item or 1) item)
    const numberedMatch = line.match(/^(\d+)[.)]\s+(.+)/);
    if (numberedMatch) {
      blocks.push({
        type: 'numbered',
        key: `num-${i}`,
        num: numberedMatch[1],
        text: numberedMatch[2],
      });
      i += 1;
      continue;
    }

    // 5. Headings (# Title, ## Title, ### Title) or short section titles followed by table/spacer
    const isExplicitHeading = /^#{1,4}\s+/.test(line);
    const isImplicitHeading =
      line.length < 55 &&
      !line.endsWith('.') &&
      !line.endsWith(',') &&
      (line.endsWith(':') || (i + 1 < lines.length && isTableRow(lines[i + 1])));

    if (isExplicitHeading || isImplicitHeading) {
      blocks.push({
        type: 'heading',
        key: `head-${i}`,
        text: line.replace(/^#{1,4}\s+/, '').replace(/:$/, ''),
      });
      i += 1;
      continue;
    }

    // 6. Regular Paragraph
    blocks.push({
      type: 'paragraph',
      key: `p-${i}`,
      text: line,
    });
    i += 1;
  }

  return (
    <div className="space-y-1.5 text-xs leading-relaxed text-slate-200 break-words">
      {blocks.map((block) => {
        if (block.type === 'spacer') {
          return <div key={block.key} className="h-1.5" />;
        }

        if (block.type === 'table') {
          return (
            <div key={block.key} className="my-2.5 overflow-hidden rounded-xl border border-slate-700/80 bg-slate-950/75 shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full min-w-full border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-700/80 bg-slate-800/90 text-cyan-300">
                      {block.headers.map((header, hIdx) => (
                        <th
                          key={hIdx}
                          className={`whitespace-nowrap px-3 py-2 font-semibold tracking-wide ${block.alignments[hIdx] || 'text-left'}`}
                        >
                          <InlineText text={header} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70 text-slate-200">
                    {block.rows.map((row, rIdx) => (
                      <tr key={rIdx} className="transition-colors even:bg-slate-900/40 hover:bg-cyan-950/20">
                        {row.map((cell, cIdx) => (
                          <td
                            key={cIdx}
                            className={`whitespace-nowrap px-3 py-1.5 text-slate-200 ${block.alignments[cIdx] || 'text-left'}`}
                          >
                            <InlineText text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        }

        if (block.type === 'heading') {
          return (
            <div key={block.key} className="mt-3 mb-1 flex items-center gap-1.5 border-b border-slate-800/80 pb-1">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
              <h4 className="text-[11px] font-bold uppercase tracking-wider text-cyan-200">
                <InlineText text={block.text} />
              </h4>
            </div>
          );
        }

        if (block.type === 'bullet') {
          return (
            <div key={block.key} className="flex items-start gap-2 pl-0.5 text-xs">
              <span className="mt-0.5 font-bold text-cyan-400 leading-none">•</span>
              <span className="flex-1 text-slate-200">
                <InlineText text={block.text} />
              </span>
            </div>
          );
        }

        if (block.type === 'numbered') {
          return (
            <div key={block.key} className="flex items-start gap-2 pl-0.5 text-xs">
              <span className="min-w-4 text-right font-semibold text-cyan-400">{block.num}.</span>
              <span className="flex-1 text-slate-200">
                <InlineText text={block.text} />
              </span>
            </div>
          );
        }

        return (
          <p key={block.key} className="text-xs text-slate-200">
            <InlineText text={block.text} />
          </p>
        );
      })}
    </div>
  );
};

const Metrics = ({ metrics }) => {
  if (!metrics?.length) return null;
  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      {metrics.map((metric, index) => (
        <div key={`${metric.label}-${index}`} className="rounded-xl border border-slate-700/70 bg-slate-950/65 p-2.5">
          <p className="truncate text-[10px] uppercase tracking-wide text-slate-500">{metric.label}</p>
          <p className="mt-1 break-words text-sm font-semibold text-cyan-200">{formatValue(metric.value, metric)}</p>
        </div>
      ))}
    </div>
  );
};

const imageSource = (value) => {
  if (!value) return '';
  if (value.startsWith('data:') || value.startsWith('http://') || value.startsWith('https://')) return value;
  return `data:image/jpeg;base64,${value}`;
};

const ImageGallery = ({ images }) => {
  if (!images?.length) return null;
  return (
    <section className="mt-3 rounded-xl border border-slate-700/70 bg-slate-950/55 p-3">
      <h4 className="mb-2 text-xs font-semibold text-slate-200">Person images</h4>
      <div className="grid grid-cols-2 gap-2">
        {images.map((item, index) => (
          <figure key={`${item.display_id}-${item.kind}-${item.timestamp || index}`} className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
            <img src={imageSource(item.image)} alt={`${item.name || 'Person'} ${item.kind || 'image'}`} className="aspect-square w-full object-cover" loading="lazy" />
            <figcaption className="p-2 text-[10px] text-slate-400">
              <p className="truncate font-medium text-slate-200">{item.name || 'Unknown person'}</p>
              <p className="truncate">{item.kind}{item.timestamp ? ` · ${formatValue(item.timestamp, { format: 'datetime' })}` : ''}</p>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
};

const DataTable = ({ table, conversationId, messageId }) => {
  const [excelLoading, setExcelLoading] = useState(false);
  const [excelError, setExcelError] = useState('');
  const canDownloadExcel = Boolean(conversationId && /^\d+$/.test(String(messageId)));

  const downloadExcel = async () => {
    if (!canDownloadExcel || excelLoading) return;
    setExcelLoading(true);
    setExcelError('');
    try {
      const response = await axios.get(
        `${API_URL}/xchat/conversations/${encodeURIComponent(conversationId)}/messages/${messageId}/tables/${encodeURIComponent(table.id)}/excel`,
        { responseType: 'blob' },
      );
      const fallbackName = String(table.download_name || 'xchat-report.csv').replace(/\.csv$/i, '.xlsx');
      const disposition = response.headers?.['content-disposition'] || '';
      const headerName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
      downloadBlob(response.data, headerName || fallbackName);
    } catch (requestError) {
      setExcelError(requestError.response?.status === 404 ? 'Excel report expired.' : 'Excel download failed.');
    } finally {
      setExcelLoading(false);
    }
  };

  return (
    <section className="mt-3 overflow-hidden rounded-xl border border-slate-700/70 bg-slate-950/55">
      <div className="flex items-center justify-between gap-2 border-b border-slate-800 px-3 py-2.5">
        <h4 className="min-w-0 truncate text-xs font-semibold text-slate-200" title={table.title}>{table.title}</h4>
        <div className="flex shrink-0 gap-1">
          <button type="button" onClick={() => downloadCsv(table.columns, table.rows, table.download_name)}
            className="flex items-center gap-1 rounded-lg bg-cyan-950/70 px-2 py-1 text-[10px] font-medium text-cyan-300 hover:bg-cyan-900" title="Download indexed CSV">
            <FileDown size={13} /> CSV
          </button>
          {canDownloadExcel && (
            <button type="button" onClick={downloadExcel} disabled={excelLoading}
              className="flex items-center gap-1 rounded-lg bg-emerald-950/70 px-2 py-1 text-[10px] font-medium text-emerald-300 hover:bg-emerald-900 disabled:cursor-wait disabled:opacity-60" title="Download Excel report (.xlsx)">
              {excelLoading ? <Loader2 size={13} className="animate-spin" /> : <FileSpreadsheet size={13} />} Excel
            </button>
          )}
        </div>
      </div>
      {excelError && <p className="border-b border-red-900/60 bg-red-950/30 px-3 py-1 text-[10px] text-red-300">{excelError}</p>}
      <div className="max-h-64 overflow-auto">
        <table className="min-w-full border-collapse text-[11px]">
          <thead className="sticky top-0 z-10 bg-slate-900 text-slate-400">
            <tr><th className="px-2 py-2 text-right font-medium">#</th>{table.columns.map((column) => <th key={column.key} className="whitespace-nowrap px-2 py-2 text-left font-medium">{column.label}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-800/80">
            {table.rows.map((row) => (
              <tr key={`${table.id}-${row.index}`} className="hover:bg-slate-900/80">
                <td className="px-2 py-2 text-right tabular-nums text-slate-500">{row.index}</td>
                {table.columns.map((column) => <td key={column.key} className="max-w-48 whitespace-nowrap px-2 py-2 text-slate-300" title={formatValue(row[column.key], column)}>{formatValue(row[column.key], column)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-800 px-3 py-1.5 text-[10px] text-slate-500">{table.rows.length.toLocaleString('en-IN')} indexed row{table.rows.length === 1 ? '' : 's'}</div>
    </section>
  );
};

const ChartCard = ({ chart }) => {
  const [type, setType] = useState(chart.type || 'bar');
  const chartRef = useRef(null);
  const primary = chart.series?.[0];

  const downloadPng = () => {
    const svg = chartRef.current?.querySelector('svg');
    if (!svg) return;
    const clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const box = svg.getBoundingClientRect();
    const source = new XMLSerializer().serializeToString(clone);
    const image = new Image();
    const blobUrl = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }));
    image.onload = () => {
      const scale = 2;
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(box.width * scale));
      canvas.height = Math.max(1, Math.round(box.height * scale));
      const context = canvas.getContext('2d');
      context.scale(scale, scale);
      context.fillStyle = '#020617';
      context.fillRect(0, 0, box.width, box.height);
      context.drawImage(image, 0, 0, box.width, box.height);
      canvas.toBlob((blob) => blob && downloadBlob(blob, chart.download_name || 'xchat-chart.png'), 'image/png');
      URL.revokeObjectURL(blobUrl);
    };
    image.src = blobUrl;
  };

  const tooltipFormatter = (value, key) => {
    const series = chart.series?.find((item) => item.key === key) || {};
    return [Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 }), series.label || key];
  };

  return (
    <section className="mt-3 rounded-xl border border-slate-700/70 bg-slate-950/55 p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0"><h4 className="truncate text-xs font-semibold text-slate-200" title={chart.title}>{chart.title}</h4><p className="mt-0.5 text-[10px] text-slate-500">Index: {chart.index_label}</p></div>
        <div className="flex shrink-0 gap-1">
          {['bar', 'line', 'pie'].map((option) => <button key={option} type="button" onClick={() => setType(option)} className={`rounded px-1.5 py-1 text-[9px] uppercase ${type === option ? 'bg-cyan-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'}`}>{option}</button>)}
        </div>
      </div>
      <div ref={chartRef} className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {type === 'pie' ? (
            <PieChart>
              <Pie data={chart.data} dataKey={primary?.key} nameKey="label" cx="50%" cy="45%" outerRadius={70} label={({ index, percent }) => `${index + 1} · ${((percent || 0) * 100).toFixed(0)}%`} labelLine={false}>
                {chart.data.map((row, index) => <Cell key={`${row.label}-${row.index}`} fill={COLORS[index % COLORS.length]} />)}
              </Pie>
              <Tooltip formatter={tooltipFormatter} /><Legend wrapperStyle={{ fontSize: 10 }} />
            </PieChart>
          ) : type === 'line' ? (
            <LineChart data={chart.data} margin={{ top: 8, right: 10, left: -20, bottom: 28 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" /><XAxis dataKey="label" stroke="#64748b" fontSize={9} angle={-25} textAnchor="end" interval="preserveStartEnd" /><YAxis stroke="#64748b" fontSize={9} /><Tooltip formatter={tooltipFormatter} contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 11 }} /><Legend wrapperStyle={{ fontSize: 10 }} />
              {chart.series.map((series, index) => <Line key={series.key} type="monotone" dataKey={series.key} name={series.label} stroke={series.color || COLORS[index]} strokeWidth={2} dot={{ r: 2 }} />)}
            </LineChart>
          ) : (
            <BarChart data={chart.data} margin={{ top: 8, right: 10, left: -20, bottom: 28 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" /><XAxis dataKey="label" stroke="#64748b" fontSize={9} angle={-25} textAnchor="end" interval="preserveStartEnd" /><YAxis stroke="#64748b" fontSize={9} /><Tooltip formatter={tooltipFormatter} contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 11 }} /><Legend wrapperStyle={{ fontSize: 10 }} />
              {chart.series.map((series, index) => <Bar key={series.key} dataKey={series.key} name={series.label} fill={series.color || COLORS[index]} radius={[3, 3, 0, 0]} />)}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex justify-end gap-2 border-t border-slate-800 pt-2">
        <button type="button" onClick={() => downloadCsv([{ key: 'label', label: chart.index_label || 'Label' }, ...chart.series.map((series) => ({ key: series.key, label: series.label }))], chart.data, (chart.download_name || 'chart.png').replace(/\.png$/i, '.csv'))} className="flex items-center gap-1 rounded-lg bg-slate-800 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-700"><Download size={12} /> Data CSV</button>
        <button type="button" onClick={downloadPng} className="flex items-center gap-1 rounded-lg bg-cyan-950/70 px-2 py-1 text-[10px] text-cyan-300 hover:bg-cyan-900"><BarChart3 size={12} /> Chart PNG</button>
      </div>
    </section>
  );
};

const XChatPresentation = ({ presentation, conversationId, messageId }) => {
  if (!presentation) return null;
  return (
    <div>
      <Metrics metrics={presentation.metrics} />
      <ImageGallery images={presentation.images} />
      {presentation.charts?.map((chart) => <ChartCard key={chart.id} chart={chart} />)}
      {presentation.tables?.map((table) => <DataTable key={table.id} table={table} conversationId={conversationId} messageId={messageId} />)}
    </div>
  );
};

export default XChatPresentation;
