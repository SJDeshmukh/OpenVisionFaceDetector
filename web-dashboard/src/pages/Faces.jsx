import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Search, Filter, SlidersHorizontal, Loader2, Upload, X, Check, ArrowRight } from 'lucide-react';

const Faces = () => {
  const { user } = useAuth();
  const schoolFlow = Boolean(user?.vertical && ['school', 'hostel'].includes(String(user.vertical).toLowerCase()));
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
  const [selectedClass, setSelectedClass] = useState({ id: '', class_year: '', division: '', branch: '' });
  
  const [batchId, setBatchId] = useState('');
  const [batchItems, setBatchItems] = useState([]);
  const [registrationMode, setRegistrationMode] = useState(false);
  const [assignments, setAssignments] = useState({}); // itemId:faceIndex -> { name, student_number, ... }
  const [showMeshFaces, setShowMeshFaces] = useState({});
  const [uploading, setUploading] = useState(false);

  const batchStorageKey = user?.vendor_id ? `registration_batch_id_${user.vendor_id}` : null;

  useEffect(() => {
    setBatchId(batchStorageKey ? (localStorage.getItem(batchStorageKey) || '') : '');
    setBatchItems([]);
    setAssignments({});
    setShowMeshFaces({});
    setRegistrationMode(false);
  }, [batchStorageKey]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await axios.get(`${API_URL}/persons`, {
          params: schoolFlow ? { person_type: 'student' } : {},
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
            if (p.custom_data) {
                custom = typeof p.custom_data === 'string' ? JSON.parse(p.custom_data) : p.custom_data;
            }
          } catch (_) { }
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
  }, [user, schoolFlow]);

  // Polling logic for registration batch
  useEffect(() => {
    let interval;
    const poll = async () => {
      if (batchId && user?.vendor_id) {
        try {
          const res = await axios.get(`${API_URL}/registration-batch/status?batch_id=${batchId}`, {
            headers: { Authorization: `Bearer ${user?.token}` }
          });
          setBatchItems(res.data?.items || []);
        } catch (e) {
          if (e.response?.status === 404) {
            if (batchStorageKey) localStorage.removeItem(batchStorageKey);
            setBatchId('');
          }
        }
      }
    };

    if (batchId) {
      poll();
      interval = setInterval(poll, 3000);
    }
    return () => clearInterval(interval);
  }, [batchId, batchStorageKey, user?.vendor_id, user?.token]);

  const dynamicKeys = useMemo(() => {
    const keys = new Set();
    persons.forEach(p => {
      if (p.custom && typeof p.custom === 'object') {
        Object.keys(p.custom).forEach(k => {
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
      const cd = p.custom || {};
      if (selectedClass.id) {
        if (cd.class_id) {
          if (String(cd.class_id) !== String(selectedClass.id)) return false;
        } else {
          if (String(cd.class_year || '') !== String(selectedClass.class_year)) return false;
          if (String(cd.division || '') !== String(selectedClass.division)) return false;
          if (String(cd.branch || '') !== String(selectedClass.branch || '')) return false;
        }
      }
      if (filters.department && p.department !== filters.department) return false;
      if (filters.designation && p.designation !== filters.designation) return false;
      if (filters.shift && p.shift !== filters.shift) return false;
      if (filters.dynamicKey) {
        const v = (cd[filters.dynamicKey] ?? '').toString();
        if (filters.dynamicValue && v !== filters.dynamicValue) return false;
      }
      if (!q) return true;
      const pool = [
        p.name, p.department, p.designation, p.shift, p.phone,
        cd.student_number, cd.class_section, cd.class_year, cd.division, cd.branch
      ].map(x => (x || '').toString().toLowerCase());
      return pool.some(s => s.includes(q));
    });
  }, [persons, query, filters, selectedClass]);

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

  const onUploadImages = async (files) => {
    const arr = Array.from(files || []).filter(f => f.type.startsWith('image/'));
    if (arr.length === 0) return;
    
    setUploading(true);
    try {
      let currentBatchId = batchId;
      if (!currentBatchId) {
        const startRes = await axios.post(`${API_URL}/registration-batch/start`, {}, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        currentBatchId = startRes.data.batch_id;
        setBatchId(currentBatchId);
        if (batchStorageKey) localStorage.setItem(batchStorageKey, currentBatchId);
      }

      const fd = new FormData();
      fd.append('batch_id', currentBatchId);
      for (const f of arr) {
        fd.append('images', f);
      }

      await axios.post(`${API_URL}/registration-batch/add`, fd, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setRegistrationMode(true);
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const commitRegistration = async () => {
    if (!batchId) return;
    const keys = Object.keys(assignments);
    if (keys.length === 0) {
      alert('No faces assigned for registration');
      return;
    }
    const incomplete = keys.find(key => {
      const assignment = assignments[key] || {};
      return !String(assignment.name || '').trim() || (schoolFlow && !assignment.class_id);
    });
    if (incomplete) {
      alert(schoolFlow
        ? 'Every student needs a name and a class/section before registration.'
        : 'Every person needs a name before registration.');
      return;
    }

    const payload = {
      batch_id: batchId,
      assignments: keys.map(k => {
        const [itemId, faceIndex] = k.split(':');
        return {
          item_id: itemId,
          face_index: parseInt(faceIndex),
          ...(schoolFlow ? { person_type: 'student' } : {}),
          ...assignments[k]
        };
      })
    };

    setLoading(true);
    try {
      await axios.post(`${API_URL}/registration-batch/commit`, payload, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      alert('Successfully registered!');
      onClearBatch();
      window.location.reload(); 
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  const onClearBatch = async () => {
    if (batchId) {
      try {
        await axios.post(`${API_URL}/registration-batch/clear`, { batch_id: batchId }, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
      } catch (_) {}
    }
    if (batchStorageKey) localStorage.removeItem(batchStorageKey);
    setBatchId('');
    setBatchItems([]);
    setRegistrationMode(false);
    setAssignments({});
    setShowMeshFaces({});
  };

  const applySuggestion = (assignmentKey, sug) => {
    setAssignments(prev => ({
      ...prev,
      [assignmentKey]: {
        ...prev[assignmentKey],
        name: sug.name,
        student_number: sug.student_number || prev[assignmentKey]?.student_number,
      }
    }));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">People Management</h1>
        {batchId && (
          <button 
            onClick={() => setRegistrationMode(!registrationMode)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${registrationMode ? 'bg-indigo-100 text-indigo-700' : 'bg-indigo-600 text-white hover:bg-indigo-700'}`}
          >
            {registrationMode ? 'View People Gallery' : 'View Upload Progress'}
          </button>
        )}
      </div>

      {!registrationMode && (
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <select
              className="p-2 border rounded-lg bg-white min-w-[200px]"
              value={selectedClass.id || ''}
              onChange={(e) => {
                const selected = classes.find(item => String(item.id) === e.target.value);
                setSelectedClass(selected || { id: '', class_year: '', division: '', branch: '' });
              }}
            >
              <option value="">Filter by Class (Optional)</option>
              {classes.map(c => (
                <option key={c.id} value={c.id}>
                  {c.label || `${c.class_year} ${c.branch} ${c.division}`}
                </option>
              ))}
            </select>

            <label className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 cursor-pointer disabled:opacity-50 transition-colors">
              {uploading ? <Loader2 className="animate-spin" size={18} /> : <Upload size={18} />}
              <span>{uploading ? 'Uploading...' : 'Bulk Register Faces'}</span>
              <input
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                disabled={uploading}
                onChange={(e) => {
                  if (e.target.files?.length > 0) onUploadImages(e.target.files);
                }}
              />
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2 border-t">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 text-slate-400" size={16} />
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search name, ID, phone..."
                className="pl-9 pr-3 py-2 border rounded-lg bg-slate-50 focus:bg-white focus:ring-2 focus:ring-indigo-500 outline-none transition-all w-[240px]"
              />
            </div>
            <div className="inline-flex items-center gap-2">
              <Filter size={16} className="text-slate-400" />
              <select
                className="p-2 border rounded-lg bg-white text-sm"
                value={filters.department}
                onChange={e => setFilters(prev => ({ ...prev, department: e.target.value }))}
              >
                <option value="">Dept</option>
                {depts.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
              <select
                className="p-2 border rounded-lg bg-white text-sm"
                value={filters.designation}
                onChange={e => setFilters(prev => ({ ...prev, designation: e.target.value }))}
              >
                <option value="">Desig</option>
                {desigs.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
              <select
                className="p-2 border rounded-lg bg-white text-sm"
                value={filters.shift}
                onChange={e => setFilters(prev => ({ ...prev, shift: e.target.value }))}
              >
                <option value="">Shift</option>
                {shifts.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            
            <div className="inline-flex items-center gap-2">
              <SlidersHorizontal size={16} className="text-slate-400" />
              <select
                className="p-2 border rounded-lg bg-white text-sm w-[120px]"
                value={filters.dynamicKey}
                onChange={e => setFilters(prev => ({ ...prev, dynamicKey: e.target.value, dynamicValue: '' }))}
              >
                <option value="">Custom Key</option>
                {dynamicKeys.map(k => <option key={k} value={k}>{k}</option>)}
              </select>
              <select
                className="p-2 border rounded-lg bg-white text-sm w-[120px]"
                value={filters.dynamicValue}
                onChange={e => setFilters(prev => ({ ...prev, dynamicValue: e.target.value }))}
                disabled={!filters.dynamicKey}
              >
                <option value="">Value</option>
                {dynVals.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>

            <button
              onClick={() => {
                setFilters({ department: '', designation: '', shift: '', dynamicKey: '', dynamicValue: '' });
                setQuery('');
                setSelectedClass({ id: '', class_year: '', division: '', branch: '' });
              }}
              className="px-3 py-2 text-sm text-slate-500 hover:text-indigo-600 transition-colors"
            >
              Reset Filters
            </button>
          </div>
        </div>
      )}

      {registrationMode && batchId ? (
        <div className="space-y-6">
          <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-slate-800">Batch Registration</h2>
              <p className="text-sm text-slate-500">Assign names and details to detected faces from your uploads.</p>
            </div>
            <div className="flex gap-3">
              <button 
                onClick={onClearBatch}
                className="px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors flex items-center gap-2"
              >
                <X size={18} />
                <span>Discard Batch</span>
              </button>
              <button 
                onClick={commitRegistration}
                disabled={loading || Object.keys(assignments).length === 0}
                className="px-6 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 shadow-sm transition-all font-medium"
              >
                Register {Object.keys(assignments).length} Person(s)
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6">
            {batchItems.map((item) => (
              <div key={item.id} className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm flex flex-col">
                <div className="p-3 bg-slate-50 border-b flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Image #{item.seq}</span>
                    {item.image && (
                      <div className="h-10 w-16 bg-slate-200 rounded overflow-hidden">
                        <img src={item.image} alt="original" className="w-full h-full object-cover" />
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {item.status === 'processing' && <Loader2 className="animate-spin text-amber-500" size={14} />}
                    <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase ${
                      item.status === 'done' ? 'bg-emerald-100 text-emerald-700' :
                      item.status === 'processing' ? 'bg-amber-100 text-amber-700' :
                      'bg-slate-200 text-slate-600'
                    }`}>
                      {item.status}
                    </span>
                  </div>
                </div>
                
                <div className="p-4 flex-1">
                  {item.status === 'done' && item.faces?.length > 0 ? (
                    <div className="space-y-6">
                      {item.faces.map((f, idx) => {
                        const assignmentKey = `${item.id}:${f.index}`;
                        const currentAssign = assignments[assignmentKey] || {};
                        const topSug = f.suggestions?.[0];
                        const landmarkCount = Array.isArray(f.landmarks_3d) ? f.landmarks_3d.length : 0;
                        const meshImage = landmarkCount >= 68 ? f.thumbs?.lmk : null;
                        const showingMesh = Boolean(showMeshFaces[assignmentKey] && meshImage);
                        
                        return (
                          <div key={idx} className="bg-slate-50 p-5 rounded-2xl border border-slate-100 space-y-4">
                            <div className="flex flex-col lg:flex-row gap-6">
                              {/* Visual Match Section */}
                              <div className="flex items-center gap-4 bg-white p-3 rounded-xl border border-slate-100 shadow-sm">
                                <div className="text-center space-y-1">
                                  <div className="text-[10px] font-bold text-slate-400 uppercase">
                                    {showingMesh ? `3D · ${landmarkCount} points` : 'Detected'}
                                  </div>
                                  <div className="relative w-24 h-24">
                                    <img
                                      src={showingMesh ? meshImage : (f.thumbs?.face || f.thumb)}
                                      className="w-24 h-24 rounded-lg object-cover border-2 border-indigo-100"
                                      alt={showingMesh ? '3D facial landmark coordinates' : 'detected'}
                                    />
                                    {meshImage ? (
                                      <button
                                        type="button"
                                        onClick={() => setShowMeshFaces(prev => ({ ...prev, [assignmentKey]: !prev[assignmentKey] }))}
                                        className={`absolute top-1 right-1 px-1.5 py-0.5 text-[9px] font-bold rounded shadow ${showingMesh ? 'bg-emerald-600 text-white' : 'bg-black/60 text-emerald-300'}`}
                                        title={showingMesh ? 'Show face photo' : 'Show 3D facial coordinates'}
                                      >
                                        {showingMesh ? 'PHOTO' : '3D'}
                                      </button>
                                    ) : (
                                      <span
                                        className="absolute bottom-1 left-1 right-1 rounded bg-slate-900/65 px-1 py-0.5 text-[8px] font-semibold text-slate-200"
                                        title="The 3D landmark engine did not return coordinates for this detection"
                                      >
                                        3D unavailable
                                      </span>
                                    )}
                                  </div>
                                </div>
                                
                                <ArrowRight className="text-slate-300" size={20} />

                                {topSug ? (
                                  <div className="text-center space-y-1 group relative">
                                    <div className="text-[10px] font-bold text-emerald-500 uppercase flex items-center justify-center gap-1">
                                      <span>Best Match</span>
                                      <span className="bg-emerald-100 px-1 rounded text-[9px]">{(topSug.similarity * 100).toFixed(1)}%</span>
                                    </div>
                                    <div className="relative">
                                      <img 
                                        src={topSug.face_image || (persons.find(p => p.id === topSug.person_id)?.image)} 
                                        className="w-24 h-24 rounded-lg object-cover border-2 border-emerald-100 bg-slate-50" 
                                        alt="match"
                                      />
                                      {(!currentAssign.name) && (
                                        <button 
                                          onClick={() => applySuggestion(assignmentKey, topSug)}
                                          className="absolute inset-0 bg-emerald-600/80 text-white flex flex-col items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity rounded-lg"
                                        >
                                          <Check size={24} />
                                          <span className="text-[10px] font-bold mt-1">Use This</span>
                                        </button>
                                      )}
                                    </div>
                                    <div className="text-[10px] font-bold text-slate-700 truncate w-24" title={topSug.name}>{topSug.name}</div>
                                  </div>
                                ) : (
                                  <div className="text-center space-y-1 opacity-40">
                                    <div className="text-[10px] font-bold text-slate-400 uppercase">No Match</div>
                                    <div className="w-24 h-24 rounded-lg border-2 border-dashed border-slate-200 flex items-center justify-center bg-slate-50">
                                      <Search size={20} />
                                    </div>
                                  </div>
                                )}
                              </div>

                              {/* Form Fields Section */}
                              <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="space-y-1">
                                  <label className="text-[10px] font-bold text-slate-400 uppercase">Full Name</label>
                                  <input 
                                    placeholder="Eg: John Doe"
                                    className="w-full p-2.5 text-sm border rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none transition-all shadow-sm"
                                    value={currentAssign.name || ''}
                                    onChange={(e) => setAssignments(prev => ({
                                      ...prev,
                                      [assignmentKey]: { ...currentAssign, name: e.target.value }
                                    }))}
                                  />
                                </div>
                                <div className="space-y-1">
                                  <label className="text-[10px] font-bold text-slate-400 uppercase">Student / ID Number</label>
                                  <input 
                                    placeholder="Eg: STU123"
                                    className="w-full p-2.5 text-sm border rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none transition-all shadow-sm"
                                    value={currentAssign.student_number || ''}
                                    onChange={(e) => setAssignments(prev => ({
                                      ...prev,
                                      [assignmentKey]: { ...currentAssign, student_number: e.target.value }
                                    }))}
                                  />
                                </div>
                                <div className="space-y-1">
                                  <label className="text-[10px] font-bold text-slate-400 uppercase">Phone Number</label>
                                  <input 
                                    placeholder="Eg: +91 987..."
                                    className="w-full p-2.5 text-sm border rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none transition-all shadow-sm"
                                    value={currentAssign.phone || ''}
                                    onChange={(e) => setAssignments(prev => ({
                                      ...prev,
                                      [assignmentKey]: { ...currentAssign, phone: e.target.value }
                                    }))}
                                  />
                                </div>
                                <div className="space-y-1">
                                  <label className="text-[10px] font-bold text-slate-400 uppercase">
                                    Class assignment{schoolFlow ? ' *' : ''}
                                  </label>
                                  <select
                                    className="w-full p-2.5 text-sm border rounded-xl bg-white focus:ring-2 focus:ring-indigo-500 outline-none transition-all shadow-sm"
                                    value={currentAssign.class_id || ''}
                                    onChange={(e) => {
                                      const selected = classes.find(item => String(item.id) === e.target.value);
                                      setAssignments(prev => ({
                                        ...prev, [assignmentKey]: {
                                          ...currentAssign,
                                          class_id: selected ? String(selected.id) : '',
                                          class_year: selected?.class_year || '',
                                          division: selected?.division || '',
                                          branch: selected?.branch || '',
                                        }
                                      }));
                                    }}
                                    required={schoolFlow}
                                  >
                                    <option value="">Select Class...</option>
                                    {classes.map(c => (
                                      <option key={c.id} value={c.id}>
                                        {c.label || `${c.class_year} ${c.branch} ${c.division}`}
                                      </option>
                                    ))}
                                  </select>
                                </div>
                              </div>
                            </div>
                            
                            {/* suggestions grid if more than 1 */}
                            {(f.suggestions?.length > 1) && (
                              <div className="pt-3 border-t border-slate-100">
                                <div className="text-[10px] font-bold text-slate-400 uppercase mb-2">Other potential matches</div>
                                <div className="flex flex-wrap gap-2">
                                  {f.suggestions.slice(1).map((s, si) => (
                                    <button 
                                      key={si}
                                      onClick={() => applySuggestion(assignmentKey, s)}
                                      className="flex items-center gap-2 p-1.5 bg-white border border-slate-200 rounded-lg hover:border-indigo-300 transition-all group"
                                    >
                                      <img src={s.face_image} alt="alt" className="w-6 h-6 rounded object-cover" />
                                      <div className="text-[10px] font-medium text-slate-600">{s.name}</div>
                                      <div className="text-[9px] text-slate-400">{(s.similarity * 100).toFixed(0)}%</div>
                                    </button>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : item.status === 'done' ? (
                    <div className="flex flex-col items-center justify-center py-10 text-slate-400">
                      <div className="text-sm italic">No faces detected in this image.</div>
                      <p className="text-[11px] mt-1 text-slate-300">Try zooming in or using a clearer photo.</p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-20 bg-slate-50/50 rounded-lg border-2 border-dashed border-slate-100">
                      <Loader2 className="animate-spin text-indigo-400 mb-3" size={32} />
                      <div className="text-sm font-medium text-slate-500">Scanning Image...</div>
                      <div className="text-[10px] text-slate-400 mt-1 italic">This usually takes 2-4 seconds.</div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {loading ? (
            <div className="col-span-full py-20 flex flex-col items-center justify-center text-slate-400">
              <Loader2 className="animate-spin mb-3" />
              <span>Loading people data...</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="col-span-full py-20 flex flex-col items-center justify-center text-slate-400 bg-white rounded-xl border border-dashed">
              <Search className="mb-3 text-slate-200" size={48} />
              <div className="text-lg font-medium">No people found</div>
              <p className="text-sm">Try adjusting your filters or search query.</p>
            </div>
          ) : (
            filtered.map(p => (
              <div key={p.id} className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col group hover:shadow-md hover:border-indigo-200 transition-all">
                <div className="relative bg-slate-50 aspect-square flex items-center justify-center overflow-hidden border-b">
                  {p.image ? (
                    <img src={p.image} alt={p.name} className="w-full h-full object-contain p-2 group-hover:scale-105 transition-transform" />
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-slate-300">
                      <Search size={32} />
                      <span className="text-[10px] font-bold uppercase tracking-wider">No Image</span>
                    </div>
                  )}
                </div>
                <div className="p-3.5 space-y-2">
                  <div className="font-bold text-slate-800 truncate" title={p.name}>{p.name}</div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-1.5 text-xs text-slate-500">
                      <div className="w-1.5 h-1.5 rounded-full bg-indigo-500"></div>
                      <span className="font-medium">
                        {p.custom?.student_number || p.custom?.student_id || p.custom?.id_number || 'No ID'}
                      </span>
                    </div>
                    <div className="text-[10px] text-slate-400 font-medium uppercase truncate">
                      {[
                        p.custom?.class_year || p.custom?.Year, 
                        p.custom?.branch || p.custom?.Department, 
                        p.custom?.division || p.custom?.Division
                      ].filter(Boolean).join(' • ') || 'No Class Assigned'}
                    </div>
                  </div>
                  <div className="pt-2 border-t flex flex-wrap gap-1">
                    {[p.department, p.designation].filter(Boolean).map((t, i) => (
                      <span key={i} className="text-[9px] px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full font-bold uppercase">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

export default Faces;
