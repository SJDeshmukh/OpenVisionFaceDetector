import { useEffect, useState, useRef } from 'react';
import Webcam from 'react-webcam';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Upload, Check, Users, Camera, Loader2, Wand2, Cpu, BookOpen, Plus, Trash2, ChevronDown } from 'lucide-react';
import modelManager from '../lib/model-manager';

const BulkImageAttendance = () => {
  const { user } = useAuth();
  const [faces, setFaces] = useState([]);
  const [people, setPeople] = useState([]);
  const [assign, setAssign] = useState({});
  const [loading, setLoading] = useState(false);
  const [marking, setMarking] = useState({});
  const [isMarkingAll, setIsMarkingAll] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [classes, setClasses] = useState([]);
  const [selectedClass, setSelectedClass] = useState(() => {
    const saved = localStorage.getItem('lastClassFilter');
    return saved ? JSON.parse(saved) : { class_year: '', division: '', branch: '' };
  });
  const [selectedSubject, setSelectedSubject] = useState('');

  // ── Lecture mode state ────────────────────────────────────────────────────
  const [lectures, setLectures] = useState([]);
  const [selectedLectureId, setSelectedLectureId] = useState(() => {
    try { return localStorage.getItem('active_lecture_id') || ''; } catch (_) { return ''; }
  });
  const [lectureRoster, setLectureRoster] = useState([]); // [{person_id, status, name}]
  const [rosterMarking, setRosterMarking] = useState({});
  const batchLsKey = user?.id ? `class_batch_id_${user.id}` : null;
  const [batchId, setBatchId] = useState('');
  const [batchItems, setBatchItems] = useState([]);
  const [showWebcam, setShowWebcam] = useState(false);
  const webcamRef = useRef(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const pinchStartDist = useRef(null);
  const pinchStartZoom = useRef(1);
  const [simThreshold, setSimThreshold] = useState(0.72);
  const peopleById = useRef(null);
  const [pendingFiles, setPendingFiles] = useState([]); // queued File objects to be scanned together
  const [regenerating, setRegenerating] = useState({});
  const overridesRef = useRef(new Map()); // key: `${itemId}:${faceIndex}` -> dataURL
  const [useClientAI, setUseClientAI] = useState(false);
  const [showMeshFaces, setShowMeshFaces] = useState({}); // key: globalIndex -> bool

  // Load user-scoped batch ID once user is available
  useEffect(() => {
    if (batchLsKey) {
      const stored = localStorage.getItem(batchLsKey);
      if (stored) setBatchId(stored);
    }
  }, [batchLsKey]);

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
    const video = webcamRef.current?.video;
    if (!video) return;

    const vw = video.videoWidth || 1280;
    const vh = video.videoHeight || 720;
    const cropW = vw / zoomLevel;
    const cropH = vh / zoomLevel;
    const sx = (vw - cropW) / 2;
    const sy = (vh - cropH) / 2;

    const canvas = document.createElement('canvas');
    canvas.width = vw;
    canvas.height = vh;
    canvas.getContext('2d').drawImage(video, sx, sy, cropW, cropH, 0, 0, vw, vh);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.92);

    const res = await fetch(dataUrl);
    const buf = await res.arrayBuffer();
    const file = new File([buf], `webcam-${Date.now()}.jpg`, { type: 'image/jpeg' });

    setShowWebcam(false);
    setZoomLevel(1);
    onUploadImages([file]);
  };

  const handlePinchStart = (e) => {
    if (e.touches.length !== 2) return;
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    pinchStartDist.current = Math.hypot(dx, dy);
    pinchStartZoom.current = zoomLevel;
  };

  const handlePinchMove = (e) => {
    if (e.touches.length !== 2 || !pinchStartDist.current) return;
    e.preventDefault();
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    const dist = Math.hypot(dx, dy);
    const scale = dist / pinchStartDist.current;
    setZoomLevel(prev => Math.min(4, Math.max(1, pinchStartZoom.current * scale)));
  };

  const handlePinchEnd = () => {
    pinchStartDist.current = null;
  };

  useEffect(() => {
    const fetchPeople = async () => {
      try {
        console.log('[DEBUG_FETCH_PEOPLE] Params:', {
          class_year: selectedClass.class_year,
          division: selectedClass.division,
          branch: selectedClass.branch
        });
        const res = await axios.get(`${API_URL}/persons`, {
          params: {
            class_year: selectedClass.class_year,
            division: selectedClass.division,
            branch: selectedClass.branch
          },
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        console.log('[DEBUG_FETCH_PEOPLE] Count:', res.data?.persons?.length);
        const list = (res.data?.persons || []).map(p => ({
          id: p.person_id || p.id,
          name: p.name,
          display_id: p.display_id
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
  }, [user, selectedClass.class_year, selectedClass.division, selectedClass.branch]);

  const fetchLectures = async () => {
    try {
      const res = await axios.get(`${API_URL}/bulk-attendance/lectures`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setLectures(res.data?.lectures || []);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchLectures();
  }, [user?.token]);

  // Implicitly handle lecture creation/selection based on Subject Dropdown
  useEffect(() => {
    const manageLectureAssoc = async () => {
      if (!selectedClass.class_year || !selectedSubject) {
        return;
      }

      // If we already have a session active for this subject/class, keep it
      if (selectedLectureId) {
        const lec = lectures.find(l => String(l.id) === String(selectedLectureId));
        if (lec && lec.subject === selectedSubject) return;
      }

      const today = new Date().toISOString().split('T')[0];
      const match = lectures.find(l =>
        l.class_year === selectedClass.class_year &&
        l.division === selectedClass.division &&
        l.branch === selectedClass.branch &&
        l.subject === selectedSubject &&
        l.lecture_date === today
      );

      if (match) {
        setSelectedLectureId(String(match.id));
        localStorage.setItem('active_lecture_id', String(match.id));
      } else {
        const mapped = classes.find(c => c.class_year === selectedClass.class_year && c.division === selectedClass.division && c.branch === selectedClass.branch)?.mapped_subjects || [];
        const matchRow = mapped.find(m => m.subject === selectedSubject);
        const autoTeacher = matchRow?.faculty || '';

        try {
          const res = await axios.post(`${API_URL}/bulk-attendance/lectures`, {
            class_year: selectedClass.class_year,
            division: selectedClass.division,
            branch: selectedClass.branch,
            subject: selectedSubject,
            teacher: autoTeacher,
            lecture_date: today,
            start_time: new Date().toTimeString().slice(0, 5)
          }, {
            headers: { Authorization: `Bearer ${user?.token}` }
          });
          await fetchLectures();
          const newId = String(res.data?.lecture_id || '');
          setSelectedLectureId(newId);
          localStorage.setItem('active_lecture_id', newId);
        } catch (e) {
          console.error("Failed to implicitly create lecture", e);
        }
      }
    };
    manageLectureAssoc();
  }, [selectedClass, selectedSubject, lectures]); // Add lectures to deps so we can find a match when list loads

  // Fetch roster whenever selected lecture changes
  useEffect(() => {
    if (!selectedLectureId) { setLectureRoster([]); return; }
    (async () => {
      try {
        const res = await axios.get(`${API_URL}/bulk-attendance/lectures/${selectedLectureId}`);
        setLectureRoster(res.data.attendance || []);
      } catch (_) { }
    })();
  }, [selectedLectureId]);


  const toggleRosterStudent = async (personId, currentStatus) => {
    if (!selectedLectureId) return;
    const newStatus = currentStatus === 'present' ? 'absent' : 'present';
    setRosterMarking(p => ({ ...p, [personId]: true }));
    try {
      await axios.post(`${API_URL}/bulk-attendance/lectures/${selectedLectureId}/mark`, { person_id: personId, status: newStatus });
      setLectureRoster(prev => {
        const exists = prev.find(r => String(r.person_id) === String(personId));
        if (exists) return prev.map(r => String(r.person_id) === String(personId) ? { ...r, status: newStatus } : r);
        const person = people.find(p => String(p.id) === String(personId));
        return [...prev, { person_id: personId, status: newStatus, name: person?.name || '' }];
      });
    } catch (e) {
      alert(e.response?.data?.error || 'Mark failed');
    } finally {
      setRosterMarking(p => ({ ...p, [personId]: false }));
    }
  };

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
        if (batchLsKey) localStorage.removeItem(batchLsKey);
        setBatchId('');
      }
    }
    const res = await axios.post(`${API_URL}/class-batch/start`, selectedClass, {
      headers: { Authorization: `Bearer ${user?.token}` }
    });
    const id = res.data?.batch_id;
    if (id) {
      if (batchLsKey) localStorage.setItem(batchLsKey, id);
      setBatchId(id);
    }
    return id;
  };

  const fetchBatchStatus = async (id) => {
    const params = new URLSearchParams({ batch_id: id, exclude_images: '1' });
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
          // Apply local override if present to survive polling refresh
          const key = `${normFace.itemId}:${normFace.faceIndex}`;
          const ov = overridesRef.current.get(key);
          if (ov) {
            normFace.thumbs = { ...(normFace.thumbs || {}), face: ov };
            normFace.thumb = ov;
          }
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
          // If backend already persisted an assignment, prefer it
          if (f.assigned_person_id) {
            nextAssign[f.globalIndex] = String(f.assigned_person_id);
          } else {
            const top = Array.isArray(f.suggestions) && f.suggestions.length ? f.suggestions[0] : null;
            const isBlurryFace = typeof f.sharpness === 'number' && f.sharpness < 80;
            const isExtremePose = typeof f.pose_yaw === 'number' && f.pose_yaw > 0.45;
            const isAmbiguous = top?.is_ambiguous === true;
            // Don't auto-assign blurry+ambiguous or extreme-pose faces — require manual review
            const skipAutoAssign = (isBlurryFace && isAmbiguous) || isExtremePose;
            const ok = !skipAutoAssign && top && typeof top.similarity === 'number' ? top.similarity >= simThreshold : false;
            nextAssign[f.globalIndex] = ok && top?.person_id ? String(top.person_id) : '';
          }
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
          // If batch was deleted or never created, clear stale ID to stop 404 spam
          const status = e?.response?.status;
          if (status === 404) {
            try { if (batchLsKey) localStorage.removeItem(batchLsKey); } catch (_) { }
            setBatchId('');
            return;
          }
          // ignore other transient errors; next tick will try again
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
      // Client-side AI path disabled for now; always use server path

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
      fd.append('fast', 'true');

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

  const addFilesToPending = (files) => {
    const rawArr = Array.from(files || []).filter(f => f.type.startsWith('image/'));
    if (rawArr.length === 0) return;
    setPendingFiles(prev => [...prev, ...rawArr]);
  };
  const scanPendingFiles = async () => {
    if (pendingFiles.length === 0) {
      alert('Please add images to scan');
      return;
    }
    if (!scopeSelected) {
      alert('Select class scope first');
      return;
    }
    try {
      await onUploadImages(pendingFiles);
      setPendingFiles([]);
    } catch (e) { }
  };

  const saveMappings = async () => {
    const id = batchLsKey ? localStorage.getItem(batchLsKey) : batchId;
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
      alert('Saved embeddings successfully');
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
      if (selectedLectureId) {
        // Lecture mode: mark present for the selected lecture (no check-in/check-out)
        const localNow = new Date().toLocaleString('sv-SE').replace(' ', 'T');
        const res = await axios.post(`${API_URL}/bulk-attendance/lectures/${selectedLectureId}/mark`, {
          person_id: personId,
          status: 'present',
          image: f.thumbs?.face || f.thumb,
          timestamp: localNow
        });
        // Refresh roster
        setLectureRoster(prev => {
          const exists = prev.find(r => String(r.person_id) === String(personId));
          const name = peopleById.current?.get(String(personId)) || '';
          if (exists) return prev.map(r => String(r.person_id) === String(personId) ? { ...r, status: 'present' } : r);
          return [...prev, { person_id: personId, status: 'present', name }];
        });
      } else {
        // Legacy mode: standard check-in/check-out
        await axios.post(`${API_URL}/person-event`, {
          detected: true,
          recognized: true,
          person_id: personId,
          is_attendance: true,
          image: f.thumbs?.face || f.thumb
        });
      }
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Mark failed');
    } finally {
      setMarking(prev => ({ ...prev, [f.globalIndex]: false }));
    }
  };

  const markAll = async () => {
    if (isMarkingAll) return;

    const distinctPeople = new Set();
    faces.forEach(f => {
      const pid = assign[f.globalIndex];
      if (pid) distinctPeople.add(pid);
    });

    if (distinctPeople.size === 0) {
      alert('No recognized students to mark');
      return;
    }

    setShowConfirmModal(true);
  };

  const confirmMarking = async () => {
    setShowConfirmModal(false);
    setIsMarkingAll(true);
    try {
      const distinctPeople = new Set();
      const facesToMark = [];

      faces.forEach(f => {
        const pid = assign[f.globalIndex];
        if (pid && !distinctPeople.has(pid)) {
          distinctPeople.add(pid);
          facesToMark.push(f);
        }
      });

      const entries = facesToMark.map(f => ({
        person_id: assign[f.globalIndex],
        status: 'present',
        image: f.thumbs?.face || f.thumb
      }));

      if (entries.length > 0) {
        if (selectedLectureId) {
          const localNow = new Date().toLocaleString('sv-SE').replace(' ', 'T');
          await axios.post(`${API_URL}/bulk-attendance/lectures/${selectedLectureId}/mark`, {
            entries,
            timestamp: localNow
          });

          // Update local roster
          setLectureRoster(prev => {
            const next = [...prev];
            entries.forEach(entry => {
              const pid = String(entry.person_id);
              const name = peopleById.current?.get(pid) || '';
              const exists = next.find(r => String(r.person_id) === pid);
              if (exists) {
                exists.status = 'present';
              } else {
                next.push({ person_id: entry.person_id, status: 'present', name });
              }
            });
            return next;
          });
        }
      }
    } finally {
      setIsMarkingAll(false);
    }
  };

  const handleRegenerate = async (f) => {
    const personId = assign[f.globalIndex];
    if (!personId) {
      alert('Assign a person first');
      return;
    }
    setRegenerating(prev => ({ ...prev, [f.globalIndex]: true }));
    try {
      const resp = await axios.post(`${API_URL}/regenerate`, {
        person_id: personId,
        image: f.thumbs?.face || f.thumb,
        fidelity: 1.0
      }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });

      if (resp.data?.success && resp.data?.image) {
        // Persist override so it survives polling refreshes
        const key = `${f.itemId}:${f.faceIndex}`;
        overridesRef.current.set(key, resp.data.image);

        // Update the face image in the local state
        setFaces(prevFaces => prevFaces.map(face => {
          if (face.globalIndex === f.globalIndex) {
            return { ...face, thumbs: { ...face.thumbs, face: resp.data.image }, thumb: resp.data.image };
          }
          return face;
        }));

        // Also update batch items for immediate visual update
        setBatchItems(prevItems => prevItems.map(item => {
          if (item.id === f.itemId) {
            return {
              ...item,
              mappedFaces: item.mappedFaces.map(face => {
                if (face.globalIndex === f.globalIndex) {
                  return { ...face, thumbs: { ...face.thumbs, face: resp.data.image }, thumb: resp.data.image };
                }
                return face;
              })
            };
          }
          return item;
        }));
      }
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Restoration failed');
    } finally {
      setRegenerating(prev => ({ ...prev, [f.globalIndex]: false }));
    }
  };

  // Build merged roster: all people + their status from lectureRoster
  const rosterMap = Object.fromEntries(lectureRoster.map(r => [String(r.person_id), r.status]));
  const presentCount = Object.values(rosterMap).filter(s => s === 'present').length;

  // True while any batch item is still being processed — blocks new uploads
  const isProcessing = batchItems.some(i => i.status === 'processing' || i.status === 'pending');

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">Bulk Image Attendance</h1>
      </div>

      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="p-2 border rounded-lg bg-white appearance-none pr-8 relative"
            value={`${selectedClass.class_year}|${selectedClass.division}|${selectedClass.branch}`}
            onChange={(e) => {
              const [y, d, b] = e.target.value.split('|');
              const newClass = { class_year: y || '', division: d || '', branch: b || '' };
              setSelectedClass(newClass);
              localStorage.setItem('lastClassFilter', JSON.stringify(newClass));
              setSelectedSubject(''); // reset subject on class change
            }}
          >
            <option value="||">Select Class Scope</option>
            {classes.map(c => (
              <option key={c.id} value={`${c.class_year}|${c.division}|${c.branch}`}>
                {c.label || `${c.class_year} ${c.branch} ${c.division}`}
              </option>
            ))}
          </select>

          {(() => {
            const currentClass = selectedClass && selectedClass.class_year ? classes.find(c => c.class_year === selectedClass.class_year && c.division === selectedClass.division && c.branch === selectedClass.branch) : null;
            const mapped = currentClass?.mapped_subjects || [];

            if (!currentClass) {
              return <select disabled className="p-2 border rounded-lg bg-slate-50 text-slate-400"><option>Select class to unlock subject</option></select>;
            }
            if (mapped.length === 0) {
              return <select disabled className="p-2 border rounded-lg bg-red-50 text-red-500"><option>No subjects mapped</option></select>;
            }

            const filteredMapped = user?.role === 'faculty' 
              ? mapped.filter(m => m.faculty === user.username || m.faculty === user.email)
              : mapped;

            return (
              <select
                value={selectedSubject}
                onChange={e => setSelectedSubject(e.target.value)}
                className="p-2 border border-slate-200 rounded-lg bg-white"
              >
                <option value="">Select Subject</option>
                {filteredMapped.map(s => <option key={s.subject} value={s.subject}>{s.subject}</option>)}
              </select>
            );
          })()}

          {(() => {
            if (!selectedSubject) return null;
            const currentClass = classes.find(c => c.class_year === selectedClass.class_year && c.division === selectedClass.division && c.branch === selectedClass.branch);
            const sub = (currentClass?.mapped_subjects || []).find(m => m.subject === selectedSubject);
            if (sub && sub.faculty) {
              return <span className="text-sm font-medium text-slate-600 bg-slate-100 px-3 py-1.5 rounded-lg border border-slate-200">Teacher: {sub.faculty}</span>;
            }
            return null;
          })()}

          {selectedLectureId ? (
            <span className="text-sm font-semibold text-emerald-700 bg-emerald-50 px-3 py-1.5 rounded-full border border-emerald-200 ml-auto">
              {presentCount} / {people.length} present (Roster Synced)
            </span>
          ) : (
            <span className="text-sm font-medium text-orange-600 bg-orange-50 px-3 py-1.5 rounded-full border border-orange-200 ml-auto">Select Subject to sync Roster</span>
          )}
        </div>
      </div>



      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <label className={`inline-flex items-center gap-2 px-4 py-2 ${(!scopeSelected || !selectedLectureId || isProcessing) ? 'bg-slate-200 text-slate-500 cursor-not-allowed' : 'bg-indigo-600 text-white hover:bg-indigo-700 cursor-pointer'} rounded-lg transition-colors`}>
            <><Upload size={18} /><span>Upload Images</span></>
            <input
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              disabled={loading || !scopeSelected || !selectedLectureId || isProcessing}
              onChange={(e) => {
                if (e.target.files?.length > 0) addFilesToPending(e.target.files);
                e.target.value = '';
              }}
            />
          </label>
          <button
            onClick={scanPendingFiles}
            disabled={!scopeSelected || pendingFiles.length === 0 || !selectedLectureId || isProcessing || loading}
            className="px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-2"
            title={isProcessing ? 'Wait for current images to finish processing' : loading ? 'Uploading images…' : 'Queue images one-by-one, then press to scan'}
          >
            {isProcessing ? (
              <><Loader2 size={16} className="animate-spin" /><span>Processing... ({batchItems.filter(i => i.status === 'done' || i.status === 'failed').length}/{batchItems.length})</span></>
            ) : loading ? (
              <><Loader2 size={16} className="animate-spin" /><span>Uploading...</span></>
            ) : (
              <span>Scan Attendance ({pendingFiles.length})</span>
            )}
          </button>
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
            onClick={saveMappings}
            disabled={faces.length === 0}
            className="px-4 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 inline-flex items-center gap-2"
          >
            Save Embeddings
          </button>

          <button
            onClick={markAll}
            disabled={faces.length === 0 || isMarkingAll}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 inline-flex items-center gap-2"
          >
            {isMarkingAll ? (
              <><Loader2 size={18} className="animate-spin" /><span>Marking...</span></>
            ) : (
              <span>Mark Attendance</span>
            )}
          </button>
          <button
            onClick={async () => {
              const id = batchLsKey ? localStorage.getItem(batchLsKey) : batchId;
              if (!confirm('End session and clear all data for a fresh start?')) return;
              try {
                if (id) await axios.post(`${API_URL}/class-batch/clear`, { batch_id: id }, { headers: { Authorization: `Bearer ${user?.token}` } });
              } catch (_) {}
              // Clear persisted keys
              if (batchLsKey) localStorage.removeItem(batchLsKey);
              localStorage.removeItem('active_lecture_id');
              localStorage.removeItem('lastClassFilter');
              // Reset all local state
              setBatchId('');
              setSelectedLectureId('');
              setBatchItems([]);
              setFaces([]);
              setAssign({});
              setPendingFiles([]);
              setShowMeshFaces({});
              setRegenerating({});
              const emptyClass = { class_year: '', division: '', branch: '' };
              setSelectedClass(emptyClass);
              setSelectedSubject('');
            }}
            className="px-3 py-2 rounded-lg bg-red-50 text-red-600 border border-red-200 hover:bg-red-100"
          >
            End Session
          </button>
          {/* Client-Side AI option disabled for now */}
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
                  {true ? (
                    <img
                      src={item.image ? (item.image.startsWith('data:') ? item.image : `data:image/jpeg;base64,${item.image}`) : `${API_URL}/class-batch/item-image/${item.id}?type=${item.status === 'done' ? 'annotated' : 'raw'}&token=${user?.token}&t=${Date.now()}`}
                      alt={`frame-seq-${item.seq}`}
                      className={`w-full h-full object-contain p-2 ${item.status !== 'done' ? 'opacity-70 blur-[1px]' : ''}`}
                      onError={(e) => {
                        // If annotated fails, try raw
                        if (e.target.src.includes('type=annotated')) {
                          e.target.src = `${API_URL}/class-batch/item-image/${item.id}?type=raw&token=${user?.token}&t=${Date.now()}`;
                        }
                      }}
                    />
                  ) : null}
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
                    {(() => {
                      const confirmed = item.mappedFaces.filter(f => f.landmarks_3d && f.landmarks_3d.length > 0);
                      const total = item.mappedFaces.length;
                      const filtered = total - confirmed.length;
                      return (
                        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                          <Users size={14} />
                          Detected Faces ({confirmed.length > 0 ? confirmed.length : total})
                          {filtered > 0 && (
                            <span className="text-[10px] font-normal text-slate-400" title={`${filtered} detection(s) removed — no 3D landmark mesh found (likely false positives)`}>
                              · {filtered} filtered
                            </span>
                          )}
                        </h3>
                      );
                    })()}

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
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-3">
                      {((() => {
                        const withLmk = item.mappedFaces.filter(f => f.landmarks_3d && f.landmarks_3d.length > 0);
                        return withLmk.length > 0 ? withLmk : item.mappedFaces;
                      })()).map(f => {
                        const sharpness = typeof f.sharpness === 'number' ? f.sharpness : null;
                        const isBlurry = sharpness !== null && sharpness < 80;
                        const isMarginal = sharpness !== null && sharpness >= 80 && sharpness < 150;
                        const isExtremePose = typeof f.pose_yaw === 'number' && f.pose_yaw > 0.45;
                        const hasNoMatch = !Array.isArray(f.suggestions) || f.suggestions.length === 0;
                        return (
                        <div key={f.globalIndex} className={`border rounded-xl p-2 bg-white shadow-sm flex flex-col ${isExtremePose ? 'border-red-300 bg-red-50/30' : isBlurry ? 'border-orange-300' : hasNoMatch ? 'border-slate-300 opacity-80' : ''}`}>
                          <div className="w-full aspect-square mb-2 bg-slate-100 rounded-lg overflow-hidden border relative group">
                            <img
                              src={showMeshFaces[f.globalIndex] && f.thumbs?.lmk ? f.thumbs.lmk : (f.thumbs?.face || f.thumb)}
                              alt={`face-${f.globalIndex}`}
                              className={`w-full h-full object-cover transition-opacity duration-200 ${isBlurry && !showMeshFaces[f.globalIndex] ? 'opacity-90' : ''}`}
                            />

                            {/* Mesh toggle button — shown only when lmk thumbnail is available */}
                            {f.thumbs?.lmk && (
                              <button
                                onClick={() => setShowMeshFaces(prev => ({ ...prev, [f.globalIndex]: !prev[f.globalIndex] }))}
                                className={`absolute top-1 right-1 px-1.5 py-0.5 text-[9px] font-bold rounded shadow transition-colors ${showMeshFaces[f.globalIndex] ? 'bg-emerald-600 text-white border border-emerald-500' : 'bg-black/50 text-emerald-300 border border-emerald-500/50 hover:bg-black/70'}`}
                                title={showMeshFaces[f.globalIndex] ? 'Show photo' : 'Show 3D landmark mesh'}
                              >
                                {showMeshFaces[f.globalIndex] ? 'PHOTO' : '3D'}
                              </button>
                            )}

                            {/* Quality / Sharpness Badge */}
                            {isBlurry ? (
                              <div className="absolute top-1 left-1 bg-orange-500 border border-orange-400 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow" title={`Sharpness: ${sharpness} — blurry face, enhance recommended`}>
                                BLUR
                              </div>
                            ) : isMarginal ? (
                              <div className="absolute top-1 left-1 bg-amber-400 border border-amber-300 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow" title={`Sharpness: ${sharpness} — slightly soft`}>
                                SOFT
                              </div>
                            ) : sharpness !== null ? (
                              <div className="absolute top-1 left-1 bg-emerald-600/80 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow" title={`Sharpness: ${sharpness} — clear`}>
                                CLEAR
                              </div>
                            ) : null}

                            {/* Extreme pose badge */}
                            {isExtremePose && (
                              <div className="absolute top-1 left-10 bg-red-500 border border-red-400 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow" title={`Extreme angle (yaw ${typeof f.pose_yaw === 'number' ? (f.pose_yaw * 100).toFixed(0) : '?'}%) — identification unreliable`}>
                                ANGLED
                              </div>
                            )}

                            {/* Enhance button — only for blurry/soft faces that have an assignment */}
                            {assign[f.globalIndex] && (isBlurry || isMarginal) && (
                              <button
                                onClick={() => handleRegenerate(f)}
                                disabled={regenerating[f.globalIndex]}
                                className={`absolute bottom-1 right-1 ${isBlurry ? 'bg-orange-500/90 hover:bg-orange-600' : 'bg-amber-500/90 hover:bg-amber-600'} text-white p-1.5 rounded-lg shadow-lg backdrop-blur transition-all transform hover:scale-105 disabled:opacity-50`}
                                title={isBlurry ? 'Enhance blurry face using reference photo' : 'Sharpen soft face using reference photo'}
                              >
                                {regenerating[f.globalIndex] ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                              </button>
                            )}
                          </div>
                          {assign[f.globalIndex] ? (
                            <div className="mb-2">
                              <span className="inline-block px-2 py-0.5 text-[10px] rounded bg-emerald-600 text-white">
                                {(() => {
                                  const p = people.find(person => String(person.id) === String(assign[f.globalIndex]));
                                  return p ? `${p.name} (#${p.display_id})` : 'Assigned';
                                })()}
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
                              <option key={p.id} value={p.id}>{p.name} (#{p.display_id})</option>
                            ))}
                          </select>
                          <div className="text-[10px] text-slate-500">
                            Top suggestion: {Array.isArray(f.suggestions) && f.suggestions.length
                              ? (
                                <>
                                  <span className={`font-semibold ${f.suggestions[0].is_ambiguous ? 'text-amber-600' : 'text-slate-700'}`}>
                                    {f.suggestions[0].name}
                                  </span>
                                  {" "}
                                  {(f.suggestions[0].similarity * 100).toFixed(1)}%
                                  {f.suggestions[0].is_ambiguous && (
                                    <span className="ml-1 text-[9px] px-1 bg-amber-500 text-white rounded font-bold animate-pulse" title="Model collapse detected: Top 2 matches are too close. Please verify.">
                                      AMBIGUOUS
                                    </span>
                                  )}
                                  {f.suggestions[0].perfect_scope === false && (
                                    <span className="ml-1 text-[9px] px-1 bg-amber-100 text-amber-700 border border-amber-200 rounded font-medium" title="Matched from a different class/batch">
                                      Cross-Class
                                    </span>
                                  )}
                                </>
                              )
                              : (typeof f.pose_yaw === 'number' && f.pose_yaw > 0.45)
                                ? <span className="text-red-500 font-semibold" title={`Extreme pose angle (yaw ${(f.pose_yaw * 100).toFixed(0)}%) — match confidence too low`}>Extreme angle, no match</span>
                                : (typeof f.sharpness === 'number' && f.sharpness < 80)
                                  ? <span className="text-orange-500 font-semibold" title="Face too blurry for reliable identification">Too blurry, no confident match</span>
                                  : <span className="text-slate-400 italic">No confident match</span>}
                          </div>
                        </div>
                      ); })}
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
        <div className="fixed inset-0 bg-black z-50 flex flex-col">
          {/* Top bar */}
          <div className="flex justify-between items-center px-4 py-3 bg-black/70 absolute top-0 left-0 right-0 z-10">
            <button
              onClick={() => { setShowWebcam(false); setZoomLevel(1); }}
              className="text-white text-sm font-medium bg-white/20 px-3 py-1.5 rounded-full"
            >
              Cancel
            </button>
            <span className="text-white font-bold text-base tracking-wide">
              {zoomLevel > 1 ? `${zoomLevel.toFixed(1)}×` : 'Pinch to zoom'}
            </span>
            {zoomLevel > 1 && (
              <button
                onClick={() => setZoomLevel(1)}
                className="text-white text-sm bg-white/20 px-3 py-1.5 rounded-full"
              >
                Reset
              </button>
            )}
            {zoomLevel <= 1 && <div className="w-16" />}
          </div>

          {/* Camera view with pinch zoom */}
          <div
            className="flex-1 overflow-hidden flex items-center justify-center bg-black"
            onTouchStart={handlePinchStart}
            onTouchMove={handlePinchMove}
            onTouchEnd={handlePinchEnd}
            style={{ touchAction: 'none' }}
          >
            <Webcam
              audio={false}
              ref={webcamRef}
              screenshotFormat="image/jpeg"
              videoConstraints={{ facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } }}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                transform: `scale(${zoomLevel})`,
                transformOrigin: 'center center',
                transition: pinchStartDist.current ? 'none' : 'transform 0.1s ease-out',
              }}
            />
          </div>

          {/* Zoom slider + capture button */}
          <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-6 pb-8 pt-4 flex flex-col items-center gap-4">
            <input
              type="range"
              min="1"
              max="4"
              step="0.1"
              value={zoomLevel}
              onChange={e => setZoomLevel(parseFloat(e.target.value))}
              className="w-48 accent-white"
            />
            <button
              onClick={captureAndUpload}
              disabled={loading}
              className="w-16 h-16 rounded-full bg-white border-4 border-white/50 flex items-center justify-center shadow-xl active:scale-95 transition-transform disabled:opacity-50"
            >
              <Camera size={28} className="text-black" />
            </button>
          </div>
        </div>
      )}
      {/* Confirmation Modal */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-md overflow-hidden transform animate-in zoom-in-95 duration-200">
            <div className="p-6">
              <div className="h-12 w-12 rounded-full bg-indigo-50 flex items-center justify-center text-indigo-600 mb-4">
                <Users size={24} />
              </div>
              <h3 className="text-xl font-bold text-slate-900 mb-2">Confirm Attendance</h3>
              <p className="text-slate-500 mb-6">
                Are the students correctly labeled? You are about to mark attendance for
                <span className="font-bold text-indigo-600 mx-1">
                  {Array.from(new Set(faces.filter(f => assign[f.globalIndex]).map(f => assign[f.globalIndex]))).length}
                </span>
                recognized students for the lecture
                <span className="font-bold text-slate-700 ml-1">"{selectedSubject}"</span>.
              </p>

              <div className="flex flex-col sm:flex-row gap-3">
                <button
                  onClick={confirmMarking}
                  className="flex-1 px-4 py-3 bg-indigo-600 text-white rounded-xl font-semibold hover:bg-indigo-700 transition-colors shadow-lg shadow-indigo-200"
                >
                  Yes, Mark Attendance
                </button>
                <button
                  onClick={() => setShowConfirmModal(false)}
                  className="flex-1 px-4 py-3 bg-slate-100 text-slate-700 rounded-xl font-semibold hover:bg-slate-200 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
            <div className="bg-slate-50 px-6 py-4 border-t border-slate-100 italic text-xs text-slate-400 text-center">
              This action will sync the roster to the core attendance logs in real-time.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default BulkImageAttendance;
