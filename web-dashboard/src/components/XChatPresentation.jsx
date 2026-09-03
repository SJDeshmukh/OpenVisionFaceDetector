import { useRef, useState } from 'react';
import { BarChart3, Download, FileDown } from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

const COLORS = ['#22d3ee', '#818cf8', '#f59e0b', '#34d399', '#fb7185', '#a78bfa', '#60a5fa', '#f472b6'];

const downloadBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
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

const InlineText = ({ text }) => String(text || '').split(/(\*\*[^*]+\*\*)/g).map((part, index) => (
  part.startsWith('**') && part.endsWith('**')
    ? <strong key={`${part}-${index}`} className="font-semibold text-slate-50">{part.slice(2, -2)}</strong>
    : <span key={`${part}-${index}`}>{part}</span>
));

export const FormattedText = ({ children }) => {
  const lines = String(children || '').split('\n');
  return (
    <div className="space-y-1.5 break-words">
      {lines.map((rawLine, index) => {
        const line = rawLine.trim();
        if (!line) return <div key={`space-${index}`} className="h-1" />;
        const bullet = line.match(/^[-*]\s+(.+)/);
        const numbered = line.match(/^(\d+)[.)]\s+(.+)/);
        if (bullet) return <div key={`${line}-${index}`} className="flex gap-2"><span className="text-cyan-400">•</span><span><InlineText text={bullet[1]} /></span></div>;
        if (numbered) return <div key={`${line}-${index}`} className="flex gap-2"><span className="min-w-5 text-right text-cyan-400">{numbered[1]}.</span><span><InlineText text={numbered[2]} /></span></div>;
        return <p key={`${line}-${index}`}><InlineText text={line.replace(/^#{1,3}\s+/, '')} /></p>;
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

const DataTable = ({ table }) => (
  <section className="mt-3 overflow-hidden rounded-xl border border-slate-700/70 bg-slate-950/55">
    <div className="flex items-center justify-between gap-2 border-b border-slate-800 px-3 py-2.5">
      <h4 className="min-w-0 truncate text-xs font-semibold text-slate-200" title={table.title}>{table.title}</h4>
      <button type="button" onClick={() => downloadCsv(table.columns, table.rows, table.download_name)}
        className="flex shrink-0 items-center gap-1 rounded-lg bg-cyan-950/70 px-2 py-1 text-[10px] font-medium text-cyan-300 hover:bg-cyan-900" title="Download indexed CSV">
        <FileDown size={13} /> CSV
      </button>
    </div>
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

const XChatPresentation = ({ presentation }) => {
  if (!presentation) return null;
  return (
    <div>
      <Metrics metrics={presentation.metrics} />
      {presentation.charts?.map((chart) => <ChartCard key={chart.id} chart={chart} />)}
      {presentation.tables?.map((table) => <DataTable key={table.id} table={table} />)}
    </div>
  );
};

export default XChatPresentation;
