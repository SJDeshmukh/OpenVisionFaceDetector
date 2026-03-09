import { useEffect, useState, useRef } from 'react';
import Webcam from 'react-webcam';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Upload, Check, Users, Camera, Loader2 } from 'lucide-react';

const BulkImageAttendance = () => {
  const { user } = useAuth();
  const [faces, setFaces] = useState([]);
  const [people, setPeople] = useState([]);
  const [assign, setAssign] = useState({});
  const [loading, setLoading] = useState(false);
  const [marking, setMarking] = useState({});
  const [classes, setClasses] = useState([]);
  const [selectedClass, setSelectedClass] = useState({ class_year: '', division: '', branch: '' });
  const [batchId, setBatchId] = useState(() => localStorage.getItem('class_batch_id') || '');
  const [batchItems, setBatchItems] = useState([]);
  const [showWebcam, setShowWebcam] = useState(false);
  const webcamRef = useRef(null);
  const [simThreshold, setSimThreshold] = useState(0.6);
  const peopleById = useRef(null);
  useEffect(() => {
    peopleById.current = new Map(people.map(p => [String(p.id), p.name]));
  }, [people]);

  const applyThresholdToFaces = (threshold) => {
    setAssign(prevAssign => {
      const nextAssign = { ...prevAssign };
      faces.forEach(f => {
        const top = Array.isArray(f.suggestions) && f.suggestions.length ? f.suggestions[0] : null;
        const ok = top && typeof top.similarity === 'number' ? top.similarity >= threshold : !!top?.person_id;
        if (!nextAssign[f.globalIndex] || !ok) {
          nextAssign[f.globalIndex] = ok && top?.person_id ? String(top.person_id) : (nextAssign[f.globalIndex] || '');
        }
      });
      return nextAssign;
    });
  };

  const scopeSelected = Boolean(
    (selectedClass.class_year && selectedClass.class_year.trim()) ||
    (selectedClass.division && selectedClass.division.trim()) ||
    (selectedClass.branch && selectedClass.branch.trim())
  );

  const captureAndUpload = async () => {
    if (!scopeSelected) {
      alert('Select class scope first');
      return;
    }
    if (!webcamRef.current) return;
    const imageSrc = webcamRef.current.getScreenshot();
    if (!imageSrc) return;

    // Convert base64 to file
    const res = await fetch(imageSrc);
    const buf = await res.arrayBuffer();
    const file = new File([buf], `webcam-${Date.now()}.jpg`, { type: 'image/jpeg' });

    setShowWebcam(false);
    onUploadImages([file]);
  };

  useEffect(() => {
    const fetchPeople = async () => {
      try {
        const res = await axios.get(`${API_URL}/persons`, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        const list = (res.data?.persons || []).map(p => ({
          id: p.person_id || p.id,
          name: p.name
        })).filter(p => p.id && p.name);
        list.sort((a, b) => a.name.localeCompare(b.name));
        setPeople(list);
      } catch (e) {
        setPeople([]);
      }
    };
    fetchPeople();
    // Load classes for filtering/scope
    (async () => {
      try {
        const r = await axios.get(`${API_URL}/classes`, { headers: { Authorization: `Bearer ${user?.token}` } });
        setClasses(r.data?.classes || []);
      } catch (_) { }
    })();
    // Load threshold for selected class if any
  }, [user]);

  useEffect(() => {
    const loadThreshold = async () => {
      const y = selectedClass.class_year || '';
      const d = selectedClass.division || '';
      const b = selectedClass.branch || '';
      if (!y && !d && !b) return;
      try {
        const qs = new URLSearchParams({ class_year: y, division: d, branch: b });
        const r = await axios.get(`${API_URL}/class-threshold?${qs.toString()}`, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        if (r.data && typeof r.data.threshold === 'number') {
          const thr = Math.max(0, Math.min(1, r.data.threshold));
          setSimThreshold(thr);
          applyThresholdToFaces(thr);
        }
      } catch (_) { }
    };
    loadThreshold();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClass.class_year, selectedClass.division, selectedClass.branch, user?.token]);

  const ensureBatch = async () => {
    // If we have a stored batchId, verify it still exists in the backend
    if (batchId) {
      try {
        await axios.get(`${API_URL}/class-batch/status?batch_id=${batchId}`, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        return batchId; // batch is valid
      } catch (e) {
        // Batch is stale/gone — clear it and create a new one
        localStorage.removeItem('class_batch_id');
        setBatchId('');
      }
    }
    const res = await axios.post(`${API_URL}/class-batch/start`, selectedClass, {
      headers: { Authorization: `Bearer ${user?.token}` }
    });
    const id = res.data?.batch_id;
    if (id) {
      localStorage.setItem('class_batch_id', id);
      setBatchId(id);
    }
    return id;
  };

  const fetchBatchStatus = async (id) => {
    const params = new URLSearchParams({ batch_id: id });
    const res = await axios.get(`${API_URL}/class-batch/status?${params.toString()}`, {
      headers: { Authorization: `Bearer ${user?.token}` }
    });
    const rawItems = res.data?.items || [];

    // Compute everything BEFORE setting any React state
    let allFaces = [];
    let isPending = false;
    let globalIndex = 0;

    // Deep-copy items so React detects a new reference
    const enrichedItems = rawItems.map(item => {
      const newItem = { ...item, mappedFaces: [] };
      if (newItem.status === 'pending' || newItem.status === 'processing') {
        isPending = true;
      }
      if (newItem.faces && Array.isArray(newItem.faces)) {
        newItem.faces.forEach((f) => {
          const currentFaceIndex = globalIndex++;
          const normFace = f.thumbs ? { ...f } : { ...f, thumbs: { face: f.thumb } };
          normFace.globalIndex = currentFaceIndex;
          normFace.itemId = newItem.id;
          normFace.faceIndex = typeof f.index === 'number' ? f.index : currentFaceIndex;
          newItem.mappedFaces.push(normFace);
          allFaces.push(normFace);
        });
      }
      return newItem;
    });

    // Now set all state together — React will batch these
    setBatchItems(enrichedItems);
    setFaces(allFaces);
    setAssign(prevAssign => {
      const nextAssign = { ...prevAssign };
      allFaces.forEach(f => {
        if (nextAssign[f.globalIndex] === undefined) {
          const top = Array.isArray(f.suggestions) && f.suggestions.length ? f.suggestions[0] : null;
          const ok = top && typeof top.similarity === 'number' ? top.similarity >= simThreshold : !!top?.person_id;
          nextAssign[f.globalIndex] = ok && top?.person_id ? String(top.person_id) : '';
        }
      });
      return nextAssign;
    });

    return { isPending, items: enrichedItems, doneCount: enrichedItems.filter(i => i.status === 'done').length };
  };

  useEffect(() => {
    let interval;
    const poll = async () => {
      if (batchId && user?.token) {
        try {
          await fetchBatchStatus(batchId);
        } catch (e) {
          // ignore transient errors; next tick will try again
        }
      }
    };

    if (batchId) {
      poll(); // initial
      interval = setInterval(poll, 2000); // keep polling; lightweight and fixes stale UI after new uploads
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [batchId, user?.token]);

  const onUploadImages = async (files) => {
    const rawArr = Array.from(files || []).filter(f => f.type.startsWith('image/'));
    if (rawArr.length === 0) return;
    if (!scopeSelected) {
      alert('Select class scope first');
      return;
    }

    setLoading(true);
    try {
      const id = await ensureBatch();
      const fd = new FormData();

      // Compress each image before adding to FormData
      for (const file of rawArr) {
        const compressedFile = await new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => {
            let { width, height } = img;
            // Use 1600px max for bulk attendance to preserve some face detail for detection
            const maxDim = 1600;
            if (width > maxDim || height > maxDim) {
              if (width > height) {
                height = Math.round((height * maxDim) / width);
                width = maxDim;
              } else {
                width = Math.round((width * maxDim) / height);
                height = maxDim;
              }
            }
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, width, height);

            canvas.toBlob((blob) => {
              if (blob) {
                // Return as a new File object
                resolve(new File([blob], file.name || `image-${Date.now()}.jpg`, {
                  type: 'image/jpeg',
                  lastModified: Date.now()
                }));
              } else {
                resolve(file); // Fallback to original if blob fails
              }
            }, 'image/jpeg', 0.82); // 82% quality yields good compression while keeping faces readable
          };
          img.onerror = () => resolve(file); // fallback on error

          const reader = new FileReader();
          reader.onload = (e) => { img.src = e.target.result; };
          reader.onerror = () => resolve(file);
          reader.readAsDataURL(file);
        });

        fd.append('images', compressedFile);
      }

      fd.append('batch_id', id || '');
      fd.append('class_year', selectedClass.class_year || '');
      fd.append('division', selectedClass.division || '');
      fd.append('branch', selectedClass.branch || '');

      const params = new URLSearchParams();
      const res = await axios.post(`${API_URL}/class-batch/add?${params.toString()}`, fd, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });

      // If we got a task_id, we could track it, but the existing batchId polling
      // already handles the per-item status updates.
      if (res.data?.task_id) {
        console.log('Batch add task started:', res.data.task_id);
      }

      // Proactively refresh state once for immediate UI update; periodic poll continues
      if (id) {
        await fetchBatchStatus(id);
      }
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Detection failed');
    } finally {
      setLoading(false);
    }
  };

  const saveMappings = async () => {
    const id = localStorage.getItem('class_batch_id');
    if (!id) {
      alert('No active session');
      return;
    }
    const assigns = faces
      .filter(f => assign[f.globalIndex])
      .map(f => ({
        item_id: f.itemId,
        face_index: f.faceIndex,
        person_id: assign[f.globalIndex]
      }));
    if (assigns.length === 0) {
      alert('Nothing to save');
      return;
    }
    try {
      await axios.post(`${API_URL}/class-batch/commit`, {
        batch_id: id,
        assignments: assigns,
        class_year: selectedClass.class_year || '',
        division: selectedClass.division || '',
        branch: selectedClass.branch || '',
        threshold: simThreshold
      }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      try {
        const rRefresh = await axios.post(`${API_URL}/class-batch/refresh`, { batch_id: id }, { headers: { Authorization: `Bearer ${user?.token}` } });
        if (rRefresh.data?.task_id) {
          console.log('Batch refresh task started:', rRefresh.data.task_id);
        }
      } catch (_) { }
      try {
        await fetchBatchStatus(id);
      } catch (_) { }
      alert('Saved and refreshed suggestions');
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Save failed');
    }
  };

  const markOne = async (f) => {
    const personId = assign[f.globalIndex];
    if (!personId) {
      alert('Select a person first');
      return;
    }
    setMarking(prev => ({ ...prev, [f.globalIndex]: true }));
    try {
      await axios.post(`${API_URL}/person-event`, {
        detected: true,
        recognized: true,
        person_id: personId,
        is_attendance: true,
        image: f.thumbs?.face || f.thumb
      }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Mark failed');
    } finally {
      setMarking(prev => ({ ...prev, [f.globalIndex]: false }));
    }
  };

  const markAll = async () => {
    for (const f of faces) {
      if (assign[f.globalIndex]) {
        await markOne(f);
      }
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">Bulk Image Attendance</h1>
      </div>

      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="p-2 border rounded-lg bg-white"
            value={`${selectedClass.class_year}|${selectedClass.division}|${selectedClass.branch}`}
            onChange={(e) => {
              const [y, d, b] = e.target.value.split('|');
              setSelectedClass({ class_year: y || '', division: d || '', branch: b || '' });
            }}
          >
            <option value="||">Select Class Scope</option>
            {classes.map(c => (
              <option key={c.id} value={`${c.class_year}|${c.division}|${c.branch}`}>
                {c.label || `${c.class_year} ${c.branch} ${c.division}`}
              </option>
            ))}
          </select>
          <label className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 cursor-pointer disabled:opacity-50">
            {loading ? 'Uploading...' : <><Upload size={18} /><span>Upload Images</span></>}
            <input
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              disabled={loading || !scopeSelected}
              onChange={(e) => {
                if (e.target.files?.length > 0) onUploadImages(e.target.files);
                e.target.value = '';
              }}
            />
          </label>
          <div className="text-sm font-medium flex items-center gap-2">
            {batchItems.some(i => i.status === 'processing' || i.status === 'pending') ? (
              <span className="flex items-center gap-2 text-amber-600 bg-amber-50 px-3 py-1.5 rounded-lg border border-amber-200">
                <Loader2 size={16} className="animate-spin" />
                Parsing... {batchItems.filter(i => i.status === 'done').length}/{batchItems.length} parsed
              </span>
            ) : batchItems.length > 0 ? (
              <span className="flex items-center gap-1 text-emerald-600 bg-emerald-50 px-3 py-1.5 rounded-lg border border-emerald-200">
                <Check size={16} /> All {batchItems.length} items parsed
              </span>
            ) : (
              <span className="text-slate-500 py-1.5">Status: Idle</span>
            )}
          </div>
          <button
            onClick={() => { if (scopeSelected) setShowWebcam(true); }}
            disabled={!scopeSelected}
            className="px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 inline-flex items-center gap-2"
            title="Live Capture"
          >
            <Camera size={16} /> Live
          </button>
          <button
            onClick={markAll}
            disabled={faces.length === 0}
            className="px-4 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Mark Selected
          </button>
          <button
            onClick={async () => {
              const id = localStorage.getItem('class_batch_id');
              if (!id) return;
              if (!confirm('End session and clear server cache?')) return;
              await axios.post(`${API_URL}/class-batch/clear`, { batch_id: id }, { headers: { Authorization: `Bearer ${user?.token}` } });
              localStorage.removeItem('class_batch_id');
              setBatchId('');
              setBatchItems([]);
              setFaces([]); setAssign({});
            }}
            className="px-3 py-2 rounded-lg bg-red-50 text-red-600 border border-red-200 hover:bg-red-100"
          >
            End Session
          </button>
        </div>
      </div>

      {batchItems.length > 0 && (
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <Camera size={18} className="text-slate-500" />
            <h2 className="font-semibold text-slate-800">Uploaded Images ({batchItems.length})</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {batchItems.map(item => (
              <div key={item.id} className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
                <div className="relative bg-slate-100 h-64 sm:h-80 flex-shrink-0 flex items-center justify-center overflow-hidden">
                  {(item.annotated || item.image) ? (
                    <img
                      src={item.annotated || (item.image?.startsWith('data:') ? item.image : `data:image/jpeg;base64,${item.image}`)}
                      alt={`frame-seq-${item.seq}`}
                      className="w-full h-full object-contain p-2"
                    />
                  ) : (
                    <div className="text-slate-400">No Image Data</div>
                  )}
                  <div className={`absolute top-2 right-2 px-2 py-1 text-xs font-bold rounded-lg shadow-sm backdrop-blur border 
                    ${item.status === 'done' ? 'bg-emerald-500/90 text-white border-emerald-600' :
                      item.status === 'processing' ? 'bg-amber-500/90 text-white border-amber-600' :
                        item.status === 'failed' ? 'bg-red-500/90 text-white border-red-600' :
                          'bg-slate-800/80 text-white border-slate-700'}`}>
                    {item.status.toUpperCase()}
                  </div>
                </div>

                {item.mappedFaces && item.mappedFaces.length > 0 && (
                  <div className="p-4 bg-slate-50 border-t">
                    <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                      <Users size={14} /> Detected Faces ({item.mappedFaces.length})
                    </h3>
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-xs text-slate-600">Similarity threshold</span>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={Math.round(simThreshold * 100)}
                        onChange={e => setSimThreshold(Math.max(0, Math.min(100, parseInt(e.target.value || '0', 10))) / 100)}
                        className="w-16 p-1.5 border rounded"
                      />
                      <span className="text-xs text-slate-600">%</span>
                      <button
                        onClick={saveMappings}
                        className="ml-auto px-3 py-1.5 rounded bg-emerald-600 text-white text-xs hover:bg-emerald-700"
                      >
                        Save Mappings
                      </button>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-3">
                      {item.mappedFaces.map(f => (
                        <div key={f.globalIndex} className="border rounded-xl p-2 bg-white shadow-sm flex flex-col">
                          <div className="w-full aspect-square mb-2 bg-slate-100 rounded-lg overflow-hidden border relative group">
                            <img src={(f.thumbs?.face || f.thumb)} alt={`face-${f.globalIndex}`} className="w-full h-full object-cover" />

                            {/* 3D Landmarks Overlay */}
                            {f.landmarks_3d && Array.isArray(f.landmarks_3d) && (
                              <svg className="absolute inset-0 w-full h-full pointer-events-none opacity-80"
                                viewBox={`0 0 ${Math.max(1, f.box[2] - f.box[0])} ${Math.max(1, f.box[3] - f.box[1])}`} preserveAspectRatio="none">
                                {f.landmarks_3d.map((pt, i) => (
                                  <circle key={`lmk-${i}`} cx={pt[0]} cy={pt[1]} r={Math.max(0.7, (f.box[2] - f.box[0]) / 50)} fill="#10B981" fillOpacity="0.9" />
                                ))}
                              </svg>
                            )}

                            {/* 3D Ready Badge */}
                            {f.struct_vec && (
                              <div className="absolute top-1 right-1 bg-emerald-600 border border-emerald-400 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow">
                                3D Ready
                              </div>
                            )}
                          </div>
                          {assign[f.globalIndex] ? (
                            <div className="mb-2">
                              <span className="inline-block px-2 py-0.5 text-[10px] rounded bg-emerald-600 text-white">
                                {peopleById.current?.get(String(assign[f.globalIndex])) || 'Assigned'}
                              </span>
                            </div>
                          ) : null}
                          <select
                            className="w-full p-1.5 border rounded-md bg-slate-50 text-xs mb-2"
                            value={assign[f.globalIndex] || ''}
                            onChange={(e) => setAssign(prev => ({ ...prev, [f.globalIndex]: e.target.value }))}
                          >
                            <option value="">Assign person…</option>
                            {people.map(p => (
                              <option key={p.id} value={p.id}>{p.name}</option>
                            ))}
                          </select>
                          <div className="text-[10px] text-slate-500">
                            Top suggestion: {Array.isArray(f.suggestions) && f.suggestions.length
                              ? <><span className="font-semibold text-slate-700">{f.suggestions[0].name}</span> {(f.suggestions[0].similarity * 100).toFixed(1)}%</>
                              : '—'}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {item.status === 'done' && (!item.mappedFaces || item.mappedFaces.length === 0) && (
                  <div className="p-3 text-center text-sm text-slate-500 bg-slate-50 border-t">
                    No faces detected in this image.
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {showWebcam && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl p-4 w-full max-w-2xl">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-semibold text-slate-800">Live Camera Capture</h3>
              <button onClick={() => setShowWebcam(false)} className="text-slate-500 hover:text-slate-700 font-bold">✕</button>
            </div>
            <div className="bg-slate-900 rounded-lg overflow-hidden flex justify-center mb-4">
              <Webcam
                audio={false}
                ref={webcamRef}
                screenshotFormat="image/jpeg"
                videoConstraints={{ facingMode: "environment" }}
                className="w-full max-w-lg"
              />
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowWebcam(false)}
                className="px-4 py-2 border rounded-lg hover:bg-slate-50 text-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={captureAndUpload}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 inline-flex gap-2 items-center"
              >
                <Camera size={18} />
                Capture & Detect
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default BulkImageAttendance;
