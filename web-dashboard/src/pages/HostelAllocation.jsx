import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  AlertTriangle, BedDouble, Building2, CheckCircle2, ChevronDown, ChevronRight, Copy, Download, GripVertical,
  Home, Loader2, Maximize2, Minus, Plus, RefreshCw, Search, ShieldAlert, Trash2, Undo2,
  UserPlus, Wrench, X
} from 'lucide-react';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';

const EMPTY = { buildings: [], residents: [], history: [], summary: {}, permissions: {} };
const STATUS_STYLE = {
  available: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  occupied: 'border-blue-300 bg-blue-50 text-blue-800',
  reserved: 'border-amber-300 bg-amber-50 text-amber-800',
  unavailable: 'border-slate-300 bg-slate-100 text-slate-600',
};

const initials = (name) => String(name || '?').split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
const availableBedLabel = (count) => `${count} ${count === 1 ? 'bed' : 'beds'} available`;
const apiError = (error) => error.response?.data?.error || error.message || 'Request failed';
const ruleText = (rules = {}) => Object.entries(rules).filter(([, value]) => value && (!Array.isArray(value) || value.length)).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${Array.isArray(value) ? value.join(', ') : value}`).join(' · ');
const roomMatchesFilter = (room, filter) => filter === 'all' ||
  (filter === 'available' && room.summary.available > 0) ||
  (filter === 'partial' && room.summary.occupied > 0 && room.summary.available > 0) ||
  (filter === 'full' && room.summary.total > 0 && room.summary.occupied === room.summary.total) ||
  (filter === 'unavailable' && room.summary.unavailable > 0);

function Summary({ value = {}, compact = false }) {
  return (
    <div className={`grid gap-3 ${compact ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-3 xl:grid-cols-5'}`} aria-label="Occupancy summary">
      {[
        ['Total beds', value.total || 0, 'text-slate-800'], ['Occupied', value.occupied || 0, 'text-blue-700'],
        ['Available', value.available || 0, 'text-emerald-700'], ['Reserved', value.reserved || 0, 'text-amber-700'],
        ['Unavailable', value.unavailable || 0, 'text-slate-600'],
      ].map(([label, count, color]) => <div key={label} className="min-w-0 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"><div className={`text-2xl font-extrabold ${color}`}>{count}</div><div className="mt-0.5 whitespace-normal text-[10px] font-semibold uppercase leading-tight tracking-wide text-slate-500">{label}</div></div>)}
    </div>
  );
}

function Modal({ title, children, onClose }) {
  return <div className="fixed inset-0 z-[70] grid place-items-center bg-slate-950/60 p-4" role="dialog" aria-modal="true" aria-label={title} onKeyDown={event => { if (event.key === 'Escape') onClose(); }}>
    <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white shadow-2xl">
      <div className="flex items-center justify-between border-b p-4"><h2 className="text-lg font-bold">{title}</h2><button type="button" onClick={onClose} aria-label="Close dialog" className="rounded-lg p-2 hover:bg-slate-100"><X size={18} /></button></div>
      <div className="p-5">{children}</div>
    </div>
  </div>;
}

function Toast({ toast, onClose }) {
  if (!toast) return null;
  const style = toast.type === 'error' ? 'border-red-200 bg-red-50 text-red-800' : toast.type === 'warning' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800';
  const Icon = toast.type === 'error' || toast.type === 'warning' ? AlertTriangle : CheckCircle2;
  return <div className={`fixed right-4 top-20 z-[110] flex w-[min(92vw,390px)] items-start gap-3 rounded-2xl border p-4 shadow-2xl ${style}`} role="status" aria-live="polite"><Icon className="mt-0.5 shrink-0" size={20} /><div className="min-w-0 flex-1"><div className="text-xs font-bold uppercase tracking-wide">{toast.type === 'error' ? 'Action failed' : toast.type === 'warning' ? 'Action needed' : 'Completed'}</div><p className="mt-0.5 break-words text-sm">{toast.message}</p></div><button type="button" onClick={onClose} className="rounded-lg p-1" aria-label="Dismiss notification"><X size={16} /></button></div>;
}

export default function HostelAllocation() {
  const { staffSession } = useAuth();
  const [data, setData] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState('');
  const [error, setError] = useState('');
  const [announcement, setAnnouncement] = useState('');
  const [toast, setToast] = useState(null);
  const [buildingId, setBuildingId] = useState('');
  const [collapsed, setCollapsed] = useState(new Set());
  const [mode, setMode] = useState('allocation');
  const [search, setSearch] = useState('');
  const [roomFilter, setRoomFilter] = useState('all');
  const [zoom, setZoom] = useState(1);
  const [selectedResidentId, setSelectedResidentId] = useState(null);
  const [selectedRoomId, setSelectedRoomId] = useState(null);
  const [selectedBedId, setSelectedBedId] = useState(null);
  const [modal, setModal] = useState(null);
  const [lastChange, setLastChange] = useState(null);
  const [draggedRoom, setDraggedRoom] = useState(null);
  const busy = Boolean(busyAction);
  const requestConfig = useMemo(() => staffSession?.access_token ? { headers: { 'X-Leave-Staff-Token': staffSession.access_token } } : {}, [staffSession?.access_token]);
  const showToast = useCallback((message, type = 'success') => {
    setAnnouncement(message);
    setToast({ id: Date.now(), message, type });
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError('');
    try {
      const response = await axios.get(`${API_URL}/hostel-management/state`, { ...requestConfig, params: { _ts: Date.now() } });
      setData(response.data || EMPTY);
      setBuildingId(current => current && response.data.buildings?.some(item => String(item.id) === String(current)) ? current : String(response.data.buildings?.[0]?.id || ''));
    } catch (requestError) { const message = apiError(requestError); setError(message); showToast(message, 'error'); }
    finally { if (!quiet) setLoading(false); }
  }, [requestConfig, showToast]);
  useEffect(() => { load(); }, [load]);

  const building = data.buildings.find(item => String(item.id) === String(buildingId));
  const rooms = useMemo(() => (building?.floors || []).flatMap(floor => floor.rooms.map(room => ({ ...room, floor, building }))), [building]);
  const beds = useMemo(() => rooms.flatMap(room => room.beds.map(bed => ({ ...bed, room }))), [rooms]);
  const allLocatedBeds = useMemo(() => data.buildings.flatMap(itemBuilding => itemBuilding.floors.flatMap(floor => floor.rooms.flatMap(room => room.beds.map(bed => ({ ...bed, building: itemBuilding, floor, room }))))), [data.buildings]);
  const selectedRoom = rooms.find(room => room.id === selectedRoomId) || null;
  const selectedBed = beds.find(bed => bed.id === selectedBedId) || null;
  const selectedResident = data.residents.find(item => item.id === selectedResidentId) || null;
  const selectedResidentBed = selectedResident?.allocation ? allLocatedBeds.find(item => item.id === selectedResident.allocation.bed_id) : null;
  const modalOriginBed = modal?.resident?.allocation ? allLocatedBeds.find(item => item.id === modal.resident.allocation.bed_id) : null;
  const bedLocation = bed => bed ? `${bed.building?.name || building?.name} / ${bed.floor?.name || bed.room?.floor?.name || ''} / Room ${bed.room?.room_number} / ${bed.bed_label}` : '';
  const unallocated = data.residents.filter(item => !item.allocation);
  const residentSource = search.trim() ? data.residents : unallocated;
  const visibleResidents = residentSource.filter(item => `${item.name} ${item.resident_id}`.toLowerCase().includes(search.toLowerCase()));
  const exportQuery = new URLSearchParams({ building_id: buildingId || '', room_filter: roomFilter, search }).toString();

  const mutate = async (method, path, payload, success) => {
    const action = method === 'delete' ? 'Deleting safely…' : method === 'post' ? 'Creating and saving…' : 'Saving changes…';
    setBusyAction(action); setError(''); setAnnouncement('');
    try {
      const response = await axios({ method, url: `${API_URL}${path}`, data: payload, ...requestConfig });
      showToast(success); setLastChange(response.data?.history_id ? { historyId: response.data.history_id, message: success } : null);
      await load(true); return response.data;
    } catch (requestError) { const message = apiError(requestError); setError(message); showToast(message, 'error'); throw requestError; }
    finally { setBusyAction(''); }
  };

  const createBuilding = () => setModal({ type: 'building', name: '', code: '' });
  const saveBuilding = async e => { e.preventDefault(); await mutate('post', '/hostel-management/buildings', modal, `Building ${modal.name} created`); setModal(null); };
  const saveFloor = async e => { e.preventDefault(); await mutate('post', `/hostel-management/buildings/${building.id}/floors`, { name: modal.name }, `Floor ${modal.name} created`); setModal(null); };
  const saveRooms = async e => { e.preventDefault(); await mutate('post', `/hostel-management/floors/${modal.floorId}/rooms`, modal, `${modal.count} room(s) created`); setModal(null); };

  const deleteBuilding = () => building && setModal({ type: 'delete', kind: 'building', entity: building, title: `Delete ${building.name}?`, message: 'All vacant floors, rooms, and beds in this building will be permanently deleted. Remove allocated residents first.' });

  const beginAssignment = (residentId, bed) => {
    if (bed.status !== 'available') { showToast(`This bed is ${bed.status}. Choose an available bed.`, 'warning'); return; }
    const resident = data.residents.find(item => item.id === Number(residentId));
    if (!resident) return;
    setSelectedResidentId(resident.id);
    setModal({ type: 'allocate', resident, bed, reason: '', override: false, override_reason: '' });
  };
  const beginRoomAssignment = (residentId, room) => {
    const resident = data.residents.find(item => item.id === Number(residentId));
    const availableBeds = room.beds.filter(item => item.status === 'available');
    if (!resident || !availableBeds.length) { showToast(`Room ${room.room_number} has no available bed. Choose another room or make a bed available.`, 'warning'); return; }
    setSelectedResidentId(resident.id); setSelectedRoomId(room.id);
    if (availableBeds.length === 1) beginAssignment(resident.id, { ...availableBeds[0], room });
    else setModal({ type: 'bedSelect', resident, room, beds: availableBeds });
  };
  const confirmAssignment = async e => {
    e.preventDefault();
    try {
      await mutate('post', '/hostel-management/allocations', { person_id: modal.resident.id, bed_id: modal.bed.id, reason: modal.reason, override: modal.override, override_reason: modal.override_reason }, `${modal.resident.name} ${modal.resident.allocation ? 'moved' : 'assigned'} successfully`);
      setModal(null); setSelectedResidentId(null);
    } catch (requestError) {
      if (requestError.response?.data?.code === 'ELIGIBILITY_FAILED' && data.permissions.can_override_eligibility) setModal(current => ({ ...current, eligibilityError: apiError(requestError), showOverride: true }));
    }
  };
  const undoLastChange = async () => {
    if (!lastChange?.historyId) return;
    await mutate('post', `/hostel-management/history/${lastChange.historyId}/undo`, {}, 'The last allocation change was undone');
    setLastChange(null);
  };
  const removeResident = resident => setModal({ type: 'removeResident', resident, reason: 'Moved to pending allocation' });
  const addBed = room => setModal({ type: 'addBed', room, bed_label: `Bed ${room.summary.total + 1}` });
  const renameBed = bed => setModal({ type: 'renameBed', bed, bed_label: bed.bed_label });
  const deleteBed = bed => setModal({ type: 'delete', kind: 'bed', entity: bed, title: `Delete ${bed.bed_label}?`, message: 'Only an available, unoccupied bed can be deleted. This action cannot be undone.' });
  const configureBed = bed => {
    if (bed.status === 'occupied') { showToast('Remove or transfer the resident before changing this bed’s availability.', 'warning'); return; }
    setModal({ type: 'configureBed', bed, status: bed.status || 'available', reason: bed.unavailable_reason || 'maintenance', note: bed.unavailable_note || bed.reservation_note || '', start_date: bed.unavailable_from || '', expected_reopening_date: bed.expected_reopening_date || '', reservation_expires_at: String(bed.reservation_expires_at || '').slice(0, 16), reserved_for_person_id: bed.reserved_for_person_id || '' });
  };
  const editRoom = room => setModal({ type: 'editRoom', room, room_number: room.room_number, room_type: room.room_type, capacity: room.summary.total });
  const csvValue = value => Array.isArray(value) ? value.join(', ') : value || '';
  const editEntityEligibility = (entity, endpoint, label) => {
    const current = entity.eligibility_rules || {};
    setModal({ type: 'eligibility', endpoint, label, gender: csvValue(current.gender), academic_year: csvValue(current.academic_year), resident_category: csvValue(current.resident_category) });
  };
  const editEligibility = room => editEntityEligibility(room, `/hostel-management/rooms/${room.id}`, `Room ${room.room_number}`);
  const staffAccessValues = (permissions, staffId) => {
    const current = permissions.find(item => item.username === `staff:${staffId}` && String(item.building_id) === String(building?.id));
    return { role: current?.access_role || 'warden', can_export: Boolean(current?.can_export), can_override_eligibility: Boolean(current?.can_override_eligibility), can_view_resident_details: Boolean(current?.can_view_resident_details) };
  };
  const managePermission = async () => {
    let staff = []; let permissions = [];
    setBusyAction('Loading staff access…');
    try { const response = await axios.get(`${API_URL}/hostel-management/permissions`, requestConfig); staff = response.data?.staff || []; permissions = response.data?.permissions || []; }
    catch (requestError) { const message = apiError(requestError); setError(message); showToast(message, 'error'); return; }
    finally { setBusyAction(''); }
    if (!staff.length) { showToast('No PIN-based staff accounts are available. Create a staff account first.', 'warning'); return; }
    setModal({ type: 'staffAccess', staff, permissions, staff_id: String(staff[0].id), ...staffAccessValues(permissions, staff[0].id) });
  };
  const downloadExport = async (kind) => {
    setBusyAction('Preparing your CSV download…');
    try {
      const query = kind === 'current' ? exportQuery : `building_id=${buildingId || ''}`;
      const response = await axios.get(`${API_URL}/hostel-management/export/${kind}.csv?${query}`, { ...requestConfig, responseType: 'blob' });
      const url = URL.createObjectURL(response.data); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = kind === 'current' ? 'hostel-current-occupancy.csv' : 'hostel-allocation-history.csv'; anchor.click();
      URL.revokeObjectURL(url);
    } catch (requestError) { setError(apiError(requestError)); }
    finally { setBusyAction(''); }
  };
  const deleteRoom = room => setModal({ type: 'delete', kind: 'room', entity: room, title: `Delete Room ${room.room_number}?`, message: 'The room and all available beds inside it will be deleted. Occupied rooms cannot be deleted.' });

  const finishModalAction = async action => {
    try { await action(); setModal(null); } catch { /* Error toast is handled by mutate. */ }
  };
  const saveRemoveResident = e => { e.preventDefault(); finishModalAction(async () => { await mutate('delete', `/hostel-management/allocations/${modal.resident.id}`, { reason: modal.reason }, `${modal.resident.name} returned to pending allocation`); setSelectedResidentId(null); }); };
  const saveAddBed = e => { e.preventDefault(); const label = modal.bed_label.trim(); finishModalAction(() => mutate('post', `/hostel-management/rooms/${modal.room.id}/beds`, { bed_label: label }, `${label} added to Room ${modal.room.room_number}`)); };
  const saveRenameBed = e => { e.preventDefault(); const label = modal.bed_label.trim(); finishModalAction(() => mutate('put', `/hostel-management/beds/${modal.bed.id}`, { bed_label: label }, `${modal.bed.bed_label} renamed to ${label}`)); };
  const saveConfigureBed = e => {
    e.preventDefault();
    const payload = { status: modal.status };
    if (modal.status === 'unavailable') Object.assign(payload, { reason: modal.reason, note: modal.note, start_date: modal.start_date, expected_reopening_date: modal.expected_reopening_date });
    if (modal.status === 'reserved') Object.assign(payload, { reservation_expires_at: modal.reservation_expires_at, note: modal.note, reserved_for_person_id: modal.reserved_for_person_id || null });
    finishModalAction(() => mutate('put', `/hostel-management/beds/${modal.bed.id}`, payload, `${modal.bed.bed_label} is now ${modal.status}`));
  };
  const saveEditRoom = e => { e.preventDefault(); finishModalAction(() => mutate('put', `/hostel-management/rooms/${modal.room.id}`, { room_number: modal.room_number.trim(), room_type: modal.room_type.trim(), capacity: Number(modal.capacity) }, `Room ${modal.room_number.trim()} updated`)); };
  const saveEligibility = e => {
    e.preventDefault();
    const list = value => value.split(',').map(item => item.trim()).filter(Boolean);
    const rules = { gender: list(modal.gender), academic_year: list(modal.academic_year), resident_category: list(modal.resident_category) };
    finishModalAction(() => mutate('put', modal.endpoint, { eligibility_rules: rules }, `Eligibility rules updated for ${modal.label}`));
  };
  const saveStaffAccess = e => {
    e.preventDefault();
    const selectedStaff = modal.staff.find(item => String(item.id) === String(modal.staff_id));
    if (!selectedStaff) { showToast('Select a staff member.', 'warning'); return; }
    const payload = { username: `staff:${selectedStaff.id}`, building_id: building.id, access_role: modal.role, can_export: modal.can_export, can_override_eligibility: modal.can_override_eligibility, can_view_resident_details: modal.can_view_resident_details };
    finishModalAction(() => mutate('put', '/hostel-management/permissions', payload, `${selectedStaff.name} now has ${modal.role} access to ${building.name}`));
  };
  const saveDuplicateFloor = e => { e.preventDefault(); finishModalAction(() => mutate('post', `/hostel-management/floors/${modal.floor.id}/duplicate`, { name: modal.name.trim() }, `${modal.name.trim()} created without resident assignments`)); };
  const confirmDelete = e => {
    e.preventDefault();
    const targets = {
      bed: { path: `/hostel-management/beds/${modal.entity.id}`, success: `${modal.entity.bed_label} deleted` },
      room: { path: `/hostel-management/rooms/${modal.entity.id}`, success: `Room ${modal.entity.room_number} deleted` },
      floor: { path: `/hostel-management/floors/${modal.entity.id}`, success: `${modal.entity.name} deleted` },
      building: { path: `/hostel-management/buildings/${modal.entity.id}`, success: `${modal.entity.name} deleted` },
    };
    const target = targets[modal.kind];
    finishModalAction(async () => {
      await mutate('delete', target.path, null, target.success);
      if (modal.kind === 'bed') setSelectedBedId(null);
      if (modal.kind === 'room') { setSelectedRoomId(null); setSelectedBedId(null); }
      if (modal.kind === 'building') { setSelectedResidentId(null); setSelectedRoomId(null); setSelectedBedId(null); setCollapsed(new Set()); }
    });
  };

  const dropRoom = async (floor, targetRoomId) => {
    if (!draggedRoom || draggedRoom.floorId !== floor.id || draggedRoom.roomId === targetRoomId) return;
    const ids = floor.rooms.map(item => item.id); const from = ids.indexOf(draggedRoom.roomId); const to = ids.indexOf(targetRoomId); ids.splice(to, 0, ids.splice(from, 1)[0]);
    await mutate('put', `/hostel-management/floors/${floor.id}/room-order`, { room_ids: ids }, 'Room layout order updated'); setDraggedRoom(null);
  };
  const locateResident = resident => {
    setSelectedResidentId(resident.id);
    if (!resident.allocation) return;
    const bed = allLocatedBeds.find(item => item.id === resident.allocation.bed_id);
    if (bed) { setBuildingId(String(bed.building.id)); setCollapsed(current => { const next = new Set(current); next.delete(bed.floor.id); return next; }); setSelectedRoomId(bed.room.id); setSelectedBedId(bed.id); }
  };

  if (loading) return <div className="grid min-h-[520px] place-items-center rounded-3xl border border-slate-200 bg-white shadow-sm"><div className="text-center"><span className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><Loader2 className="animate-spin" size={27} /></span><h2 className="font-bold text-slate-900">Loading hostel allocation</h2><p className="mt-1 text-sm text-slate-500">Preparing buildings, rooms, beds and residents…</p></div></div>;

  return <div className="hostel-allocation relative space-y-5 pb-8" aria-busy={busy}>
    <Toast toast={toast} onClose={() => setToast(null)} />
    {busy && <div className="fixed inset-0 z-[100] grid cursor-wait place-items-center bg-slate-950/15 backdrop-blur-[1px]" role="status" aria-live="assertive"><div className="flex items-center gap-3 rounded-2xl border border-indigo-100 bg-white px-5 py-3 font-semibold text-slate-800 shadow-2xl"><Loader2 className="animate-spin text-indigo-600" size={20} /><span>{busyAction}</span></div></div>}
    <div className="flex flex-col gap-4 rounded-3xl border border-indigo-100 bg-gradient-to-br from-white via-indigo-50/60 to-violet-50/70 p-5 shadow-sm xl:flex-row xl:items-center xl:justify-between">
      <div><h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900"><Building2 className="text-indigo-600" /> Building & Resident Allocation</h1><p className="text-sm text-slate-500">Build the hostel visually, then allocate residents to real bed slots.</p></div>
      <div className="flex flex-wrap gap-2">
        <button disabled={busy} onClick={() => load()} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold shadow-sm"><RefreshCw size={15} className="mr-1 inline" />Refresh</button>
        {data.permissions.can_export && <><button disabled={busy} onClick={() => downloadExport('current')} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold shadow-sm"><Download size={15} className="mr-1 inline" />Filtered occupancy CSV</button><button disabled={busy} onClick={() => downloadExport('history')} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold shadow-sm"><Download size={15} className="mr-1 inline" />History CSV</button></>}
        {data.permissions.can_edit_layout && <button disabled={busy} onClick={() => setMode(value => value === 'layout' ? 'allocation' : 'layout')} className={`rounded-xl px-4 py-2 text-sm font-semibold shadow-sm ${mode === 'layout' ? 'bg-amber-500 text-white' : 'bg-indigo-600 text-white'}`}>{mode === 'layout' ? 'Finish Layout Editing' : 'Edit Layout'}</button>}
      </div>
    </div>
    <div aria-live="polite" className="sr-only">{announcement}</div>
    {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
    {data.permissions.role === 'viewer' && <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">Read-only access: you can view assigned buildings and permitted resident details, but cannot change layouts or allocations.</div>}
    {lastChange && <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"><span>{lastChange.message}</span>{data.permissions.can_allocate && <button disabled={busy} onClick={undoLastChange} className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 font-semibold"><Undo2 size={14} className="mr-1 inline" />Undo</button>}</div>}
    <Summary value={building?.summary || data.summary} />

    <div className="grid min-h-[650px] grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(440px,1fr)_360px]">
      <aside className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm xl:sticky xl:top-4 xl:self-start">
        <div className="mb-4 flex items-center justify-between"><h2 className="font-bold">Buildings</h2>{data.permissions.can_manage_buildings && <button onClick={createBuilding} aria-label="Create building" className="rounded-lg bg-indigo-50 p-2 text-indigo-700"><Plus size={16} /></button>}</div>
        <select className="mb-3 w-full rounded-lg border p-2 text-sm" value={buildingId} onChange={e => setBuildingId(e.target.value)}><option value="">Select building</option>{data.buildings.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        {building && <div className="mb-5 space-y-1">{building.floors.map(floor => <button key={floor.id} onClick={() => document.getElementById(`floor-${floor.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })} className="flex w-full items-center justify-between rounded-lg px-2 py-2 text-left text-sm hover:bg-slate-50"><span>{floor.name}</span><span className="text-xs text-slate-400">{floor.summary.available} free</span></button>)}</div>}
        <div className="border-t pt-4"><label className="text-xs font-semibold uppercase text-slate-500">{search ? 'Resident search results' : 'Pending allocation'}</label><div className="relative my-2"><Search className="absolute left-2.5 top-2.5 text-slate-400" size={15} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Resident, ID, building or room" className="w-full rounded-lg border py-2 pl-8 pr-2 text-sm" /></div>
          <div className="max-h-[390px] space-y-2 overflow-y-auto">{visibleResidents.map(resident => <button key={resident.id} draggable={data.permissions.can_allocate} onDragStart={e => { e.dataTransfer.setData('residentId', String(resident.id)); setSelectedResidentId(resident.id); }} onClick={() => locateResident(resident)} className={`flex w-full items-center gap-2 rounded-xl border p-2 text-left hover:border-indigo-300 ${selectedResidentId === resident.id ? 'border-indigo-500 bg-indigo-50' : ''}`}><span className="grid h-8 w-8 place-items-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700">{initials(resident.name)}</span><span className="min-w-0"><span className="block truncate text-sm font-medium">{resident.name}</span><span className="block text-xs text-slate-500">ID {resident.resident_id}{resident.allocation ? ' · Allocated' : ''}</span></span>{data.permissions.can_allocate && <GripVertical className="ml-auto text-slate-300" size={14} />}</button>)}{!visibleResidents.length && <p className="py-6 text-center text-xs text-slate-400">No matching residents</p>}</div>
        </div>
      </aside>

      <main className="overflow-auto rounded-3xl border border-slate-200 bg-gradient-to-b from-slate-50 to-indigo-50/30 p-4 shadow-inner">
        {!building ? <div className="grid h-full min-h-[500px] place-items-center text-center"><div><span className="mx-auto mb-4 grid h-20 w-20 place-items-center rounded-3xl bg-indigo-100 text-indigo-500"><Building2 size={42} /></span><h2 className="text-xl font-bold">{data.permissions.can_manage_buildings ? 'Create your first hostel building' : 'No assigned hostel buildings'}</h2><p className="mb-5 mt-1 text-sm text-slate-500">Building → Floors → Rooms → Beds</p>{data.permissions.can_manage_buildings && <button disabled={busy} onClick={createBuilding} className="rounded-xl bg-indigo-600 px-5 py-2.5 font-semibold text-white shadow-md shadow-indigo-200">Create Building</button>}</div></div> : <>
          <div className="sticky left-0 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white/90 p-3 shadow-sm backdrop-blur"><div><h2 className="text-xl font-bold">{building.name}</h2><p className="text-xs text-slate-500">{mode === 'layout' ? 'Layout Editing — drag rooms to rearrange' : 'Resident Allocation — drag or select a resident, then choose a bed'}</p></div><div className="flex flex-wrap gap-2">{data.permissions.can_edit_layout && <button disabled={busy} onClick={() => setModal({ type: 'floor', name: '' })} className="rounded-lg border bg-white px-3 py-2 text-sm font-semibold"><Plus size={14} className="inline" /> Floor</button>}{data.permissions.can_manage_eligibility && <button disabled={busy} onClick={() => editEntityEligibility(building, `/hostel-management/buildings/${building.id}`, building.name)} className="rounded-lg border bg-white px-3 py-2 text-sm font-semibold">Building rules</button>}{data.permissions.can_manage_permissions && <button disabled={busy} onClick={managePermission} className="rounded-lg border bg-white px-3 py-2 text-sm font-semibold">Staff access</button>}{mode === 'layout' && data.permissions.can_manage_buildings && <button disabled={busy} onClick={deleteBuilding} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700"><Trash2 size={14} className="mr-1 inline" />Delete building</button>}<button disabled={busy} onClick={() => setZoom(value => Math.max(.7, value - .1))} className="rounded-lg border bg-white p-2" aria-label="Zoom out"><Minus size={15} /></button><button disabled={busy} onClick={() => setZoom(1)} className="rounded-lg border bg-white p-2" aria-label="Fit to screen"><Maximize2 size={15} /></button><button disabled={busy} onClick={() => setZoom(value => Math.min(1.4, value + .1))} className="rounded-lg border bg-white p-2" aria-label="Zoom in"><Plus size={15} /></button></div></div>
          <div className="origin-top-left space-y-4" style={{ transform: `scale(${zoom})`, width: `${100 / zoom}%` }}>{building.floors.map(floor => <section id={`floor-${floor.id}`} key={floor.id} className="rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-center gap-3 border-b p-3"><button onClick={() => setCollapsed(current => { const next = new Set(current); next.has(floor.id) ? next.delete(floor.id) : next.add(floor.id); return next; })} aria-expanded={!collapsed.has(floor.id)} className="flex items-center gap-2 font-bold">{collapsed.has(floor.id) ? <ChevronRight size={17} /> : <ChevronDown size={17} />}{floor.name}</button><span className="text-xs text-slate-500">{floor.summary.occupied}/{floor.summary.total} occupied · {floor.summary.available} available for allocation</span>{mode === 'layout' && <div className="ml-auto flex flex-wrap gap-2"><button onClick={() => setModal({ type: 'rooms', floorId: floor.id, count: 10, start_number: 1, prefix: '', capacity: 3, room_type: 'Standard' })} className="rounded-lg bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700">+ Add rooms</button>{data.permissions.can_manage_eligibility && <button onClick={() => editEntityEligibility(floor, `/hostel-management/floors/${floor.id}`, floor.name)} className="rounded-lg border px-3 py-1.5 text-xs">Floor rules</button>}<button onClick={() => setModal({ type: 'duplicateFloor', floor, name: `Copy of ${floor.name}` })} className="rounded-lg border px-3 py-1.5 text-xs"><Copy size={13} className="inline" /> Duplicate layout</button><button onClick={() => setModal({ type: 'delete', kind: 'floor', entity: floor, title: `Delete ${floor.name}?`, message: 'This floor, its vacant rooms, and available beds will be permanently deleted. Move all allocated residents first.' })} className="rounded-lg border border-red-200 px-2 py-1.5 text-xs text-red-600" aria-label={`Delete ${floor.name}`}><Trash2 size={13} /></button></div>}</div>
            {!collapsed.has(floor.id) && <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2 2xl:grid-cols-3">{floor.rooms.filter(room => roomMatchesFilter(room, roomFilter) && (!search.trim() || `${building.name} ${floor.name} ${room.room_number} ${room.beds.map(bed => `${bed.resident?.name || ''} ${bed.resident?.resident_id || ''}`).join(' ')}`.toLowerCase().includes(search.toLowerCase()))).map(room => <article key={room.id} draggable={mode === 'layout'} onDragStart={() => setDraggedRoom({ roomId: room.id, floorId: floor.id })} onDragOver={e => { if (mode === 'layout' || (mode === 'allocation' && room.summary.available)) e.preventDefault(); }} onDrop={e => { e.preventDefault(); if (mode === 'layout') dropRoom(floor, room.id); else beginRoomAssignment(e.dataTransfer.getData('residentId'), { ...room, floor, building }); }} onClick={() => { setSelectedResidentId(null); setSelectedBedId(null); setSelectedRoomId(room.id); }} className={`rounded-xl border-2 bg-white p-3 transition ${selectedRoomId === room.id ? 'border-indigo-500 shadow-md' : room.summary.available ? 'border-emerald-200' : room.summary.unavailable === room.summary.total ? 'border-slate-300' : 'border-blue-200'}`}>
                <div className="mb-2 flex items-start justify-between gap-2"><div className="min-w-0"><h3 className="truncate font-bold" title={`Room ${room.room_number}`}>Room {room.room_number}</h3><p className="text-xs leading-relaxed text-slate-500">{room.room_type} · {room.summary.occupied}/{room.summary.total} occupied · {availableBedLabel(room.summary.available)}</p></div>{mode === 'layout' && <GripVertical className="shrink-0 text-slate-400" size={18} />}</div>
                {ruleText(room.effective_eligibility) && <div className="mb-2 rounded-lg bg-violet-50 px-2 py-1 text-[10px] text-violet-700"><ShieldAlert size={11} className="mr-1 inline" />{ruleText(room.effective_eligibility)}</div>}
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{room.beds.map(bed => <button key={bed.id} onClick={event => { event.stopPropagation(); setSelectedRoomId(room.id); setSelectedBedId(bed.id); if (mode === 'allocation' && selectedResidentId && bed.status === 'available') beginAssignment(selectedResidentId, { ...bed, room }); else if (bed.resident) locateResident(data.residents.find(item => item.id === bed.resident.id) || bed.resident); else setSelectedResidentId(null); }} onDragOver={event => { if (mode === 'allocation' && bed.status === 'available') event.preventDefault(); }} onDrop={event => { event.preventDefault(); event.stopPropagation(); beginAssignment(event.dataTransfer.getData('residentId'), { ...bed, room }); }} className={`min-h-16 rounded-lg border p-2 text-left text-xs focus:ring-2 focus:ring-indigo-500 ${STATUS_STYLE[bed.status]}`} aria-label={`Room ${room.room_number}, ${bed.bed_label}, ${bed.status}${bed.resident ? `, occupied by ${bed.resident.name}` : ''}`}><span className="flex items-center gap-1 font-semibold"><BedDouble className="shrink-0" size={13} /><span className="truncate" title={bed.bed_label}>{bed.bed_label}</span></span>{bed.resident ? <span className="mt-1 block truncate" title={bed.resident.name}>{bed.resident.name}</span> : <span className="mt-1 block capitalize">{bed.status === 'available' ? 'Available' : bed.status}</span>}</button>)}</div>
              </article>)}{!floor.rooms.some(room => roomMatchesFilter(room, roomFilter) && (!search.trim() || `${building.name} ${floor.name} ${room.room_number} ${room.beds.map(bed => `${bed.resident?.name || ''} ${bed.resident?.resident_id || ''}`).join(' ')}`.toLowerCase().includes(search.toLowerCase()))) && <div className="col-span-full rounded-xl border border-dashed p-8 text-center text-sm text-slate-400">{floor.rooms.length ? 'No rooms match the current search and filter.' : 'No rooms yet. Use “Add rooms” in Layout Editing mode.'}</div>}</div>}
          </section>)}</div>
        </>}
      </main>

      <aside className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm xl:sticky xl:top-4 xl:self-start">
        <div className="mb-4"><label className="text-xs font-semibold uppercase text-slate-500">Room filter</label><select value={roomFilter} onChange={e => setRoomFilter(e.target.value)} className="mt-1 w-full rounded-lg border p-2 text-sm"><option value="all">All rooms</option><option value="available">Rooms with available beds</option><option value="partial">Partially occupied rooms</option><option value="full">Full rooms</option><option value="unavailable">Rooms with unavailable beds</option></select></div>
        {selectedResident ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3"><span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-indigo-100 font-bold text-indigo-700">{initials(selectedResident.name)}</span><div className="min-w-0"><h3 className="break-words font-bold leading-snug" title={selectedResident.name}>{selectedResident.name}</h3><p className="break-all text-xs text-slate-500">Resident ID: {selectedResident.resident_id}</p></div></div>
            <dl className="space-y-2 text-sm"><div><dt className="text-xs text-slate-400">Gender</dt><dd>{selectedResident.gender || 'Requires review'}</dd></div><div><dt className="text-xs text-slate-400">Academic year</dt><dd>{selectedResident.academic_year || 'Requires review'}</dd></div><div><dt className="text-xs text-slate-400">Category</dt><dd>{selectedResident.resident_category || 'Requires review'}</dd></div></dl>
            {selectedResident.allocation ? <><p className="rounded-lg bg-blue-50 p-2 text-xs text-blue-700">Currently: {selectedResidentBed ? `${selectedResidentBed.building.name} / ${selectedResidentBed.floor.name} / Room ${selectedResidentBed.room.room_number} / ${selectedResidentBed.bed_label}` : `Bed #${selectedResident.allocation.bed_id}`}. Select another available bed to transfer.</p>{data.permissions.can_allocate && <button onClick={() => removeResident(selectedResident)} className="w-full rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600">Remove from room and return to pending</button>}</> : <p className="rounded-lg bg-emerald-50 p-2 text-xs text-emerald-700">Pending allocation. Select or drag this resident onto an available bed.</p>}
          </div>
        ) : selectedRoom ? (
          <div className="space-y-3">
            <div><h3 className="text-lg font-bold">Room {selectedRoom.room_number}</h3><p className="text-sm text-slate-500">{selectedRoom.room_type}</p></div>
            <Summary value={selectedRoom.summary} compact />
            <p className="text-xs text-violet-700">{ruleText(selectedRoom.effective_eligibility) || 'No eligibility restrictions'}</p>
            {selectedBed && <div className={`rounded-xl border p-3 text-xs ${STATUS_STYLE[selectedBed.status]}`}><div className="flex min-w-0 items-center justify-between gap-2"><strong className="truncate" title={selectedBed.bed_label}>{selectedBed.bed_label}</strong><span className="shrink-0 rounded-full bg-white/70 px-2 py-0.5 font-semibold capitalize">{selectedBed.status}</span></div>{selectedBed.unavailable_reason && <div className="mt-2">Reason: {selectedBed.unavailable_reason.replaceAll('_', ' ')}</div>}{selectedBed.unavailable_note && <div>Note: {selectedBed.unavailable_note}</div>}{selectedBed.unavailable_from && <div>Unavailable from: {String(selectedBed.unavailable_from)}</div>}{selectedBed.expected_reopening_date && <div>Expected reopening (review required): {String(selectedBed.expected_reopening_date)}</div>}{selectedBed.reservation_expires_at && <div>Reservation expires: {String(selectedBed.reservation_expires_at)}</div>}</div>}
            {mode === 'layout' && data.permissions.can_edit_layout && <div className="space-y-2">
              <button onClick={() => addBed(selectedRoom)} className="w-full rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white"><Plus size={14} className="inline" /> Add custom bed</button>
              <button onClick={() => editRoom(selectedRoom)} className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white">Edit room and capacity</button>
              {data.permissions.can_manage_eligibility && <button onClick={() => editEligibility(selectedRoom)} className="w-full rounded-lg border px-3 py-2 text-sm">Eligibility rules</button>}
              {selectedBed && <><button onClick={() => renameBed(selectedBed)} className="w-full rounded-lg border px-3 py-2 text-sm">Rename {selectedBed.bed_label}</button><button onClick={() => configureBed(selectedBed)} className="w-full rounded-lg border px-3 py-2 text-sm"><Wrench size={14} className="inline" /> Configure availability</button><button onClick={() => deleteBed(selectedBed)} className="w-full rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600"><Trash2 size={14} className="inline" /> Delete selected bed</button></>}
              <button onClick={() => deleteRoom(selectedRoom)} className="w-full rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600"><Trash2 size={14} className="inline" /> Delete vacant room</button>
            </div>}
          </div>
        ) : <div className="py-12 text-center text-slate-400"><Home className="mx-auto mb-2" /><p className="text-sm">Select a room or resident to see details and actions.</p></div>}
        <div className="mt-6 border-t pt-4"><h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">Recent allocation history</h3><div className="max-h-48 space-y-2 overflow-y-auto">{data.history.slice(0, 10).map(item => <div key={item.id} className="rounded-lg bg-slate-50 p-2 text-xs"><strong>{item.resident_name || `Resident ${item.person_id}`}</strong><span className="ml-1 capitalize">{item.action}</span><div className="text-slate-400">{String(item.created_at || '')}</div></div>)}</div></div>
      </aside>
    </div>

    {modal?.type === 'building' && <Modal title="Create Building" onClose={() => setModal(null)}><form onSubmit={saveBuilding} className="space-y-4"><label className="block text-sm font-medium">Building name<input autoFocus required value={modal.name} onChange={e => setModal({ ...modal, name: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="Building A" /></label><label className="block text-sm font-medium">Building number/code<input value={modal.code} onChange={e => setModal({ ...modal, code: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="A" /></label><button disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 p-2.5 font-semibold text-white">{busy ? <><Loader2 className="animate-spin" size={17} />Creating building…</> : 'Create Building'}</button></form></Modal>}
    {modal?.type === 'floor' && <Modal title={`Add Floor to ${building?.name}`} onClose={() => setModal(null)}><form onSubmit={saveFloor} className="space-y-4"><label className="block text-sm font-medium">Floor name<input autoFocus required value={modal.name} onChange={e => setModal({ ...modal, name: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="Ground Floor" /></label><button disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 p-2.5 font-semibold text-white">{busy ? <><Loader2 className="animate-spin" size={17} />Adding floor…</> : 'Add Floor'}</button></form></Modal>}
    {modal?.type === 'rooms' && <Modal title="Quick Add Rooms" onClose={() => setModal(null)}><form onSubmit={saveRooms} className="grid grid-cols-2 gap-4"><label className="text-sm font-medium">Number of rooms<input type="number" min="1" max="100" value={modal.count} onChange={e => setModal({ ...modal, count: Number(e.target.value) })} className="mt-1 w-full rounded-xl border p-2.5" /></label><label className="text-sm font-medium">First room number<input type="number" value={modal.start_number} onChange={e => setModal({ ...modal, start_number: Number(e.target.value) })} className="mt-1 w-full rounded-xl border p-2.5" /></label><label className="text-sm font-medium">Number prefix<input value={modal.prefix} onChange={e => setModal({ ...modal, prefix: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="2" /></label><label className="text-sm font-medium">Beds per room<input type="number" min="1" max="20" value={modal.capacity} onChange={e => setModal({ ...modal, capacity: Number(e.target.value) })} className="mt-1 w-full rounded-xl border p-2.5" /></label><label className="col-span-2 text-sm font-medium">Room type<input value={modal.room_type} onChange={e => setModal({ ...modal, room_type: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label><button disabled={busy} className="col-span-2 flex items-center justify-center gap-2 rounded-xl bg-indigo-600 p-2.5 font-semibold text-white">{busy ? <><Loader2 className="animate-spin" size={17} />Creating rooms and beds…</> : 'Create Rooms & Beds'}</button></form></Modal>}
    {modal?.type === 'removeResident' && <Modal title="Return resident to pending allocation" onClose={() => setModal(null)}><form onSubmit={saveRemoveResident} className="space-y-4"><div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800"><strong>{modal.resident.name}</strong> will be removed from the current bed. Their resident record will remain available in the pending allocation list.</div><label className="block text-sm font-medium">Reason<textarea autoFocus required rows="3" value={modal.reason} onChange={e => setModal({ ...modal, reason: e.target.value })} className="mt-1 w-full resize-none rounded-xl border p-2.5" placeholder="Explain why this allocation is being removed" /></label><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy} className="flex-1 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white">Return to pending</button></div></form></Modal>}
    {modal?.type === 'addBed' && <Modal title={`Add a bed to Room ${modal.room.room_number}`} onClose={() => setModal(null)}><form onSubmit={saveAddBed} className="space-y-4"><p className="text-sm text-slate-500">Give the bed a clear, unique label residents and staff can identify.</p><label className="block text-sm font-medium">Bed label<input autoFocus required value={modal.bed_label} onChange={e => setModal({ ...modal, bed_label: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="Bed 4 or Window Bed" /></label><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy} className="flex-1 rounded-xl bg-emerald-600 px-4 py-2.5 font-semibold text-white">Add bed</button></div></form></Modal>}
    {modal?.type === 'renameBed' && <Modal title={`Rename ${modal.bed.bed_label}`} onClose={() => setModal(null)}><form onSubmit={saveRenameBed} className="space-y-4"><label className="block text-sm font-medium">New bed label<input autoFocus required value={modal.bed_label} onChange={e => setModal({ ...modal, bed_label: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy || modal.bed_label.trim() === modal.bed.bed_label} className="flex-1 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white">Save name</button></div></form></Modal>}
    {modal?.type === 'configureBed' && <Modal title={`Configure ${modal.bed.bed_label}`} onClose={() => setModal(null)}><form onSubmit={saveConfigureBed} className="space-y-4"><div><label className="block text-sm font-medium">Bed availability</label><div className="mt-2 grid grid-cols-3 gap-2">{['available', 'reserved', 'unavailable'].map(status => { const disabled = modal.bed.status === 'unavailable' && status === 'reserved'; return <button type="button" key={status} disabled={disabled} title={disabled ? 'Make this bed available before reserving it' : ''} onClick={() => setModal({ ...modal, status })} className={`rounded-xl border px-2 py-2.5 text-xs font-semibold capitalize ${modal.status === status ? 'border-indigo-500 bg-indigo-50 text-indigo-700 ring-2 ring-indigo-100' : 'border-slate-200'}`}>{status}</button>; })}</div>{modal.bed.status === 'unavailable' && <p className="mt-2 text-xs text-amber-700">To reserve this bed, first save it as Available, then reopen this form and select Reserved.</p>}</div>{modal.status === 'unavailable' && <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><label className="block text-sm font-medium">Reason<select value={modal.reason} onChange={e => setModal({ ...modal, reason: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5"><option value="maintenance">Maintenance</option><option value="cleaning">Cleaning</option><option value="out_of_service">Out of service</option><option value="other">Other</option></select></label><label className="block text-sm font-medium">Note {modal.reason === 'other' && <span className="text-red-600">*</span>}<textarea required={modal.reason === 'other'} rows="2" value={modal.note} onChange={e => setModal({ ...modal, note: e.target.value })} className="mt-1 w-full resize-none rounded-xl border p-2.5" /></label><div className="grid grid-cols-2 gap-3"><label className="text-sm font-medium">Starts<input type="date" value={modal.start_date || ''} onChange={e => setModal({ ...modal, start_date: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label><label className="text-sm font-medium">Expected reopening<input type="date" value={modal.expected_reopening_date || ''} onChange={e => setModal({ ...modal, expected_reopening_date: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label></div></div>}{modal.status === 'reserved' && <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-3"><label className="block text-sm font-medium">Reservation expires<input required type="datetime-local" value={modal.reservation_expires_at} onChange={e => setModal({ ...modal, reservation_expires_at: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label><label className="block text-sm font-medium">Reserved for (optional)<select value={modal.reserved_for_person_id} onChange={e => setModal({ ...modal, reserved_for_person_id: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5"><option value="">No specific resident</option>{data.residents.map(resident => <option key={resident.id} value={resident.id}>{resident.name} · {resident.resident_id}</option>)}</select></label><label className="block text-sm font-medium">Reservation note<textarea rows="2" value={modal.note} onChange={e => setModal({ ...modal, note: e.target.value })} className="mt-1 w-full resize-none rounded-xl border p-2.5" /></label></div>}{modal.status === 'available' && <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">This bed will become available for immediate resident allocation. Existing reservation or unavailability details will be cleared.</p>}<div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy} className="flex-1 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white">Save availability</button></div></form></Modal>}
    {modal?.type === 'editRoom' && <Modal title={`Edit Room ${modal.room.room_number}`} onClose={() => setModal(null)}><form onSubmit={saveEditRoom} className="space-y-4"><label className="block text-sm font-medium">Room number<input autoFocus required value={modal.room_number} onChange={e => setModal({ ...modal, room_number: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label><label className="block text-sm font-medium">Room type<input required value={modal.room_type} onChange={e => setModal({ ...modal, room_type: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="Standard, Deluxe, Accessible…" /></label><label className="block text-sm font-medium">Bed capacity<input required type="number" min="1" max="20" value={modal.capacity} onChange={e => setModal({ ...modal, capacity: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /><span className="mt-1 block text-xs text-slate-500">Capacity cannot be reduced below current occupancy. Only available beds can be removed.</span></label><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy} className="flex-1 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white">Save room</button></div></form></Modal>}
    {modal?.type === 'eligibility' && <Modal title={`Eligibility rules · ${modal.label}`} onClose={() => setModal(null)}><form onSubmit={saveEligibility} className="space-y-4"><p className="rounded-xl bg-violet-50 p-3 text-sm text-violet-800">Enter multiple allowed values separated by commas. Leave a field blank to remove that restriction.</p><label className="block text-sm font-medium">Allowed genders<input value={modal.gender} onChange={e => setModal({ ...modal, gender: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="female, male" /></label><label className="block text-sm font-medium">Allowed academic years<input value={modal.academic_year} onChange={e => setModal({ ...modal, academic_year: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="1, 2, 3" /></label><label className="block text-sm font-medium">Allowed resident categories<input value={modal.resident_category} onChange={e => setModal({ ...modal, resident_category: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" placeholder="student, faculty" /></label><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy} className="flex-1 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white">Save rules</button></div></form></Modal>}
    {modal?.type === 'staffAccess' && <Modal title={`Staff access · ${building?.name}`} onClose={() => setModal(null)}><form onSubmit={saveStaffAccess} className="space-y-4"><p className="text-sm text-slate-500">Choose the staff member and exactly what they can do in this building.</p><label className="block text-sm font-medium">Staff member<select required value={modal.staff_id} onChange={e => { const staffId = e.target.value; setModal({ ...modal, staff_id: staffId, ...staffAccessValues(modal.permissions, staffId) }); }} className="mt-1 w-full rounded-xl border p-2.5">{modal.staff.map(item => <option key={item.id} value={item.id}>{item.name} · {item.role}{item.department ? ` · ${item.department}` : ''}</option>)}</select></label><label className="block text-sm font-medium">Access level<select value={modal.role} onChange={e => setModal({ ...modal, role: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5"><option value="warden">Warden — edit layout and allocations</option><option value="viewer">Viewer — read only</option></select></label><div className="space-y-2">{[['can_export', 'Allow CSV exports'], ['can_override_eligibility', 'Allow eligibility overrides'], ['can_view_resident_details', 'Allow full resident details']].map(([key, label]) => <label key={key} className="flex items-center justify-between rounded-xl border p-3 text-sm font-medium"><span>{label}</span><input type="checkbox" checked={modal[key]} onChange={e => setModal({ ...modal, [key]: e.target.checked })} className="h-4 w-4" /></label>)}</div><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy} className="flex-1 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white">Save access</button></div></form></Modal>}
    {modal?.type === 'duplicateFloor' && <Modal title={`Duplicate ${modal.floor.name}`} onClose={() => setModal(null)}><form onSubmit={saveDuplicateFloor} className="space-y-4"><p className="rounded-xl bg-blue-50 p-3 text-sm text-blue-800">Rooms and bed configuration will be copied. Resident assignments will not be copied.</p><label className="block text-sm font-medium">New floor name<input autoFocus required value={modal.name} onChange={e => setModal({ ...modal, name: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Cancel</button><button disabled={busy} className="flex-1 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white">Duplicate floor</button></div></form></Modal>}
    {modal?.type === 'delete' && <Modal title={modal.title} onClose={() => setModal(null)}><form onSubmit={confirmDelete} className="space-y-4"><div className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><AlertTriangle className="shrink-0" size={22} /><div><strong className="block">This is a permanent action</strong><p className="mt-1 text-sm">{modal.message}</p></div></div><div className="flex gap-2"><button type="button" onClick={() => setModal(null)} className="flex-1 rounded-xl border px-4 py-2.5 font-semibold">Keep it</button><button disabled={busy} className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-red-600 px-4 py-2.5 font-semibold text-white"><Trash2 size={16} />Delete permanently</button></div></form></Modal>}
    {modal?.type === 'bedSelect' && <Modal title={`Choose a bed in Room ${modal.room.room_number}`} onClose={() => setModal(null)}><p className="mb-3 text-sm text-slate-600">Choose an available destination for <strong>{modal.resident.name}</strong>.</p><div className="grid grid-cols-2 gap-2">{modal.beds.map(bed => <button key={bed.id} onClick={() => beginAssignment(modal.resident.id, { ...bed, room: modal.room })} className="rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-left text-sm font-semibold text-emerald-800"><BedDouble size={15} className="mr-1 inline" />{bed.bed_label}<span className="block text-xs font-normal">Available</span></button>)}</div></Modal>}
    {modal?.type === 'allocate' && <Modal title={modal.resident.allocation ? 'Confirm Resident Transfer' : 'Confirm Resident Allocation'} onClose={() => setModal(null)}><form onSubmit={confirmAssignment} className="space-y-4"><div className="rounded-xl bg-indigo-50 p-3 text-sm"><strong>{modal.resident.name}</strong><div className="mt-1 text-indigo-700">{modal.resident.allocation ? `${bedLocation(modalOriginBed) || `Bed #${modal.resident.allocation.bed_id}`} → ` : ''}{bedLocation({ ...modal.bed, building: modal.bed.room?.building || building, floor: modal.bed.room?.floor, room: modal.bed.room || selectedRoom })}</div></div>{modal.eligibilityError && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{modal.eligibilityError}</div>}<label className="block text-sm font-medium">Reason or note<input value={modal.reason} onChange={e => setModal({ ...modal, reason: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label>{modal.showOverride && <><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={modal.override} onChange={e => setModal({ ...modal, override: e.target.checked })} />Use authorized eligibility override</label>{modal.override && <label className="block text-sm font-medium">Override reason<input required value={modal.override_reason} onChange={e => setModal({ ...modal, override_reason: e.target.value })} className="mt-1 w-full rounded-xl border p-2.5" /></label>}</>}<button disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 p-2.5 font-semibold text-white">{busy ? <><Loader2 className="animate-spin" size={17} />Saving allocation…</> : <><UserPlus size={16} />Confirm {modal.resident.allocation ? 'Transfer' : 'Allocation'}</>}</button></form></Modal>}
  </div>;
}
