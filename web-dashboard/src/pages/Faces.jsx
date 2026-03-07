import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Search, Filter, SlidersHorizontal } from 'lucide-react';

const Faces = () => {
  const { user } = useAuth();
  const [persons, setPersons] = useState([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState({
    department: '',
    designation: '',
    shift: '',
    dynamicKey: '',
    dynamicValue: ''
  });
  const [classes, setClasses] = useState([]);
  const [selectedClass, setSelectedClass] = useState({ class_year: '', division: '', branch: '' });
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [searchPreview, setSearchPreview] = useState('');
  const [minSim, setMinSim] = useState(0.5);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await axios.get(`${API_URL}/persons`, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        const items = (res.data?.persons || []).map(p => {
          let image = p.face_image || '';
          if (!image && p.image_url) image = p.image_url;
          if (image && !image.startsWith('data:') && !image.startsWith('http')) {
            image = `data:image/jpeg;base64,${image}`;
          }
          let custom = {};
          try {
            custom = p.custom_data || {};
          } catch (_) {}
          return {
            id: p.person_id || p.id,
            name: p.name || '',
            department: p.department || '',
            designation: p.designation || '',
            shift: p.shift || '',
            phone: p.phone || '',
            image,
            custom
          };
        });
        setPersons(items);
      } catch (_) {
        setPersons([]);
      } finally {
        setLoading(false);
      }
    };
    load();
    (async () => {
      try {
        const r = await axios.get(`${API_URL}/classes`, { headers: { Authorization: `Bearer ${user?.token}` } });
        setClasses(r.data?.classes || []);
      } catch (_) { /* ignore */ }
    })();
  }, [user]);

  const dynamicKeys = useMemo(() => {
    const keys = new Set();
    persons.forEach(p => {
      if (p.custom && typeof p.custom === 'object') {
        Object.keys(p.custom).forEach(k => {
          // Common useful keys first
          if (['student_number', 'class_section', 'class_year', 'division', 'branch'].includes(k)) {
            keys.add(k);
          } else if (keys.size < 20) {
            keys.add(k);
          }
        });
      }
    });
    return Array.from(keys);
  }, [persons]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return persons.filter(p => {
      // Class scope first (custom_data)
      const cd = p.custom || {};
      if (selectedClass.class_year && String(cd.class_year || '') !== String(selectedClass.class_year)) return false;
      if (selectedClass.division && String(cd.division || '') !== String(selectedClass.division)) return false;
      if (selectedClass.branch && String(cd.branch || '') !== String(selectedClass.branch)) return false;
      if (filters.department && p.department !== filters.department) return false;
      if (filters.designation && p.designation !== filters.designation) return false;
      if (filters.shift && p.shift !== filters.shift) return false;
      if (filters.dynamicKey) {
        const v = (p.custom?.[filters.dynamicKey] ?? '').toString();
        if (filters.dynamicValue && v !== filters.dynamicValue) return false;
      }
      if (!q) return true;
      const pool = [
        p.name, p.department, p.designation, p.shift, p.phone,
        cd.student_number, cd.class_section, cd.class_year, cd.division, cd.branch
      ].map(x => (x || '').toString().toLowerCase());
      return pool.some(s => s.includes(q));
    });
  }, [persons, query, filters]);

  const depts = useMemo(() => Array.from(new Set(persons.map(p => p.department).filter(Boolean))).sort(), [persons]);
  const desigs = useMemo(() => Array.from(new Set(persons.map(p => p.designation).filter(Boolean))).sort(), [persons]);
  const shifts = useMemo(() => Array.from(new Set(persons.map(p => p.shift).filter(Boolean))).sort(), [persons]);
  const dynVals = useMemo(() => {
    if (!filters.dynamicKey) return [];
    const vals = new Set();
    persons.forEach(p => {
      const v = p.custom?.[filters.dynamicKey];
      if (v !== undefined && v !== null && `${v}`.trim() !== '') vals.add(`${v}`);
    });
    return Array.from(vals).sort();
  }, [persons, filters.dynamicKey]);

  const personById = useMemo(() => {
    const m = new Map();
    persons.forEach(p => m.set(String(p.id), p));
    return m;
  }, [persons]);

  const onSearchByImage = async (files) => {
    const arr = Array.from(files || []).filter(f => f.type.startsWith('image/'));
    if (arr.length === 0) return;
    const file = arr[0];
    setSearching(true);
    setSearchResults([]);
    try {
      // Convert to data URI so we can send JSON with class scope
      const toDataURL = (f) => new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result);
        r.onerror = reject;
        r.readAsDataURL(f);
      });
      const dataUrl = await toDataURL(file);
      setSearchPreview(dataUrl);
      const body = {
        image: dataUrl,
        class_year: selectedClass.class_year || '',
        division: selectedClass.division || '',
        branch: selectedClass.branch || '',
        topk: 5
      };
      const res = await axios.post(`${API_URL}/utils/search-embedding`, body, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const faces = res.data?.faces || [];
      setSearchResults(faces);
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Search failed');
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">Faces</h1>
      </div>

      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="p-2 border rounded-lg bg-white"
            value={`${selectedClass.class_year}|${selectedClass.division}|${selectedClass.branch}`}
            onChange={(e) => {
              const [y, d, b] = e.target.value.split('|');
              setSelectedClass({ class_year: y || '', division: d || '', branch: b || '' });
            }}
          >
            <option value="||">Class Scope (Optional)</option>
            {classes.map(c => (
              <option key={c.id} value={`${c.class_year}|${c.division}|${c.branch}`}>
                {c.label || `${c.class_year} ${c.branch} ${c.division}`}
              </option>
            ))}
          </select>
          <label className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 cursor-pointer disabled:opacity-50">
            {searching ? 'Searching...' : <>Search by Image</>}
            <input
              type="file"
              accept="image/*"
              className="hidden"
              disabled={searching}
              onChange={(e) => {
                if (e.target.files?.length > 0) onSearchByImage(e.target.files);
              }}
            />
          </label>
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-sm text-slate-600">Min Similarity</span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={Math.round(minSim * 100)}
              onChange={(e) => {
                const v = Math.max(0, Math.min(100, parseInt(e.target.value || '0', 10)));
                setMinSim(v / 100);
              }}
              className="w-20 p-2 border rounded-lg"
              title="Minimum match percentage to display"
            />
            <span className="text-sm text-slate-600">%</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search className="absolute left-2 top-2.5 text-slate-400" size={16} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search name, student no., class, phone…"
              className="pl-8 pr-3 py-2 border rounded-lg bg-white"
            />
          </div>
          <div className="inline-flex items-center gap-2">
            <Filter size={16} className="text-slate-500" />
            <select
              className="p-2 border rounded-lg bg-white"
              value={filters.department}
              onChange={e => setFilters(prev => ({ ...prev, department: e.target.value }))}
            >
              <option value="">Department</option>
              {depts.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
            <select
              className="p-2 border rounded-lg bg-white"
              value={filters.designation}
              onChange={e => setFilters(prev => ({ ...prev, designation: e.target.value }))}
            >
              <option value="">Designation</option>
              {desigs.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
            <select
              className="p-2 border rounded-lg bg-white"
              value={filters.shift}
              onChange={e => setFilters(prev => ({ ...prev, shift: e.target.value }))}
            >
              <option value="">Shift</option>
              {shifts.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="inline-flex items-center gap-2">
            <SlidersHorizontal size={16} className="text-slate-500" />
            <select
              className="p-2 border rounded-lg bg-white"
              value={filters.dynamicKey}
              onChange={e => setFilters(prev => ({ ...prev, dynamicKey: e.target.value, dynamicValue: '' }))}
            >
              <option value="">Filter Field</option>
              {dynamicKeys.map(k => <option key={k} value={k}>{k}</option>)}
            </select>
            <select
              className="p-2 border rounded-lg bg-white"
              value={filters.dynamicValue}
              onChange={e => setFilters(prev => ({ ...prev, dynamicValue: e.target.value }))}
              disabled={!filters.dynamicKey}
            >
              <option value="">Value</option>
              {dynVals.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <button
            onClick={() => setFilters({ department: '', designation: '', shift: '', dynamicKey: '', dynamicValue: '' })}
            className="px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200"
          >
            Clear Filters
          </button>
        </div>
      </div>

      {searchPreview || (searchResults && searchResults.length > 0) ? (
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-4">
          <div className="flex items-center gap-2">
            <h2 className="font-semibold text-slate-800">Search Results</h2>
          </div>
          {searchPreview && (
            <div className="flex items-start gap-4">
              <div className="w-48 h-48 bg-slate-100 border rounded-lg overflow-hidden flex items-center justify-center">
                <img src={searchPreview} alt="query" className="object-contain w-full h-full" />
              </div>
              <div className="flex-1">
                {searching ? (
                  <div className="text-slate-500">Searching…</div>
                ) : (searchResults || []).length === 0 ? (
                  <div className="text-slate-500">No faces detected.</div>
                ) : (
                  <div className="space-y-4">
                    {(searchResults || []).map((f, idx) => (
                      <div key={idx} className="border rounded-lg p-3">
                        <div className="text-sm font-semibold text-slate-700 mb-2">
                          Face #{f.index + 1}
                        </div>
                        {f.face_thumb ? (
                          <div className="mb-3">
                            <img src={f.face_thumb} alt={`face-${idx}`} className="w-24 h-24 object-contain border rounded" />
                          </div>
                        ) : null}
                        {Array.isArray(f.suggestions) && f.suggestions.length > 0 ? (
                          <div className="text-xs text-slate-600 mb-2">
                            Top suggestion: {f.suggestions[0].name} {(f.suggestions[0].similarity * 100).toFixed(1)}%
                          </div>
                        ) : null}
                        {Array.isArray(f.suggestions) && f.suggestions.length > 0 ? (
                          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                            {f.suggestions.filter(s => (s.similarity ?? 0) >= minSim).map((s, i) => {
                              const key = String(s.person_id ?? '');
                              const person = personById.get(key);
                              const img = s.face_thumb || person?.image;
                              return (
                                <div key={`${idx}-${i}`} className="border rounded-lg overflow-hidden bg-white">
                                  <div className="w-full aspect-square bg-slate-100 flex items-center justify-center">
                                    {img ? (
                                      <img src={img} alt={s.name} className="w-full h-full object-contain p-1" />
                                    ) : (
                                      <div className="text-xs text-slate-400 p-2">No Image</div>
                                    )}
                                  </div>
                                  <div className="p-2">
                                    <div className="text-xs font-semibold text-slate-700 truncate" title={s.name}>{s.name}</div>
                                    <div className="text-[10px] text-slate-500">{(s.similarity * 100).toFixed(1)}%</div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="text-xs text-slate-500">No registered match above threshold.</div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : null}

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {loading ? (
          <div className="col-span-full text-center text-slate-500">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="col-span-full text-center text-slate-500">No faces found</div>
        ) : (
          filtered.map(p => (
            <div key={p.id} className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
              <div className="relative bg-slate-100 aspect-square flex items-center justify-center overflow-hidden">
                {p.image ? (
                  <img src={p.image} alt={p.name} className="w-full h-full object-contain p-2" />
                ) : (
                  <div className="text-slate-400">No Image</div>
                )}
              </div>
              <div className="p-3 space-y-1">
                <div className="font-semibold text-slate-800 truncate" title={p.name}>{p.name}</div>
                <div className="text-xs text-slate-600">
                  {p.custom?.student_number && <span>Student #: {p.custom.student_number}</span>}
                  {p.custom?.class_section && <span> • Class: {p.custom.class_section}</span>}
                  {p.custom?.class_year && <span> • Year: {p.custom.class_year}</span>}
                  {p.custom?.division && <span> • Div: {p.custom.division}</span>}
                  {p.custom?.branch && <span> • Branch: {p.custom.branch}</span>}
                </div>
                <div className="text-xs text-slate-500">
                  {[p.department, p.designation, p.shift].filter(Boolean).join(' • ')}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default Faces;
