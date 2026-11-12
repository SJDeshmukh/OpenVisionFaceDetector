import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  ArrowRight,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  Edit3,
  GraduationCap,
  RefreshCw,
  Upload,
  Users,
} from 'lucide-react';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';

const emptySession = {
  code: '',
  name: '',
  start_date: '',
  end_date: '',
  status: 'PLANNED',
};

const emptyProgram = {
  code: '',
  name: '',
  department_code: '',
  duration_years: 3,
  structure: 'ANNUAL',
  semesters_per_year: 1,
};

const errorMessage = (error, fallback) => error?.response?.data?.error || error?.message || fallback;

const StatusBadge = ({ status }) => {
  const normalized = String(status || '').toUpperCase();
  const colors = normalized === 'ACTIVE'
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : normalized === 'CLOSED'
      ? 'bg-slate-100 text-slate-600 border-slate-200'
      : 'bg-amber-50 text-amber-700 border-amber-200';
  return <span className={`px-2.5 py-1 rounded-full border text-[11px] font-bold tracking-wide ${colors}`}>{normalized}</span>;
};

const AcademicManagement = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isHostel = String(user?.vertical || '').trim().toLowerCase() === 'hostel';
  const [config, setConfig] = useState({ sessions: [], programs: [] });
  const [departments, setDepartments] = useState([]);
  const [sessionForm, setSessionForm] = useState(emptySession);
  const [programForm, setProgramForm] = useState(emptyProgram);
  const [editingProgramId, setEditingProgramId] = useState(null);
  const [sourceSessionId, setSourceSessionId] = useState('');
  const [targetSessionId, setTargetSessionId] = useState('');
  const [promotionRows, setPromotionRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState(null);

  const showNotice = (message, type = 'success') => setNotice({ message, type });

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [academicResponse, departmentResponse] = await Promise.all([
        axios.get(`${API_URL}/academic/config`),
        axios.get(`${API_URL}/leave/admin/departments`, { params: { vendor_id: user?.vendor_id } }),
      ]);
      setConfig({
        sessions: academicResponse.data?.sessions || [],
        programs: academicResponse.data?.programs || [],
      });
      setDepartments(departmentResponse.data?.departments || []);
    } catch (error) {
      showNotice(errorMessage(error, 'Unable to load resident academic setup.'), 'error');
    } finally {
      setLoading(false);
    }
  }, [user?.vendor_id]);

  useEffect(() => {
    if (isHostel) loadData();
    else setLoading(false);
  }, [isHostel, loadData]);

  const activeSession = useMemo(
    () => config.sessions.find((session) => String(session.status).toUpperCase() === 'ACTIVE'),
    [config.sessions],
  );

  const submitSession = async (event) => {
    event.preventDefault();
    setBusy('session');
    try {
      await axios.post(`${API_URL}/academic/sessions`, sessionForm);
      setSessionForm(emptySession);
      showNotice('Academic session created.');
      await loadData();
    } catch (error) {
      showNotice(errorMessage(error, 'Unable to create the academic session.'), 'error');
    } finally {
      setBusy('');
    }
  };

  const activateSession = async (session) => {
    setBusy(`session-${session.id}`);
    try {
      await axios.patch(`${API_URL}/academic/sessions/${session.id}`, { status: 'ACTIVE' });
      showNotice(`${session.name || session.code} is now the active session.`);
      await loadData();
    } catch (error) {
      showNotice(errorMessage(error, 'Unable to activate the academic session.'), 'error');
    } finally {
      setBusy('');
    }
  };

  const submitProgram = async (event) => {
    event.preventDefault();
    if (!programForm.department_code) {
      showNotice('Select the department whose HOD should receive leave requests.', 'error');
      return;
    }
    setBusy('program');
    try {
      const payload = {
        ...programForm,
        semesters_per_year: programForm.structure === 'ANNUAL' ? 1 : Number(programForm.semesters_per_year),
        duration_years: Number(programForm.duration_years),
      };
      if (editingProgramId) {
        await axios.patch(`${API_URL}/academic/programs/${editingProgramId}`, payload);
        showNotice('Course configuration updated.');
      } else {
        await axios.post(`${API_URL}/academic/programs`, payload);
        showNotice('Course and HOD department mapping created.');
      }
      setProgramForm(emptyProgram);
      setEditingProgramId(null);
      await loadData();
    } catch (error) {
      showNotice(errorMessage(error, 'Unable to save the course.'), 'error');
    } finally {
      setBusy('');
    }
  };

  const editProgram = (program) => {
    setEditingProgramId(program.id);
    setProgramForm({
      code: program.code || '',
      name: program.name || '',
      department_code: program.department_code || program.code || '',
      duration_years: Number(program.duration_years || 1),
      structure: program.structure || 'ANNUAL',
      semesters_per_year: Number(program.semesters_per_year || 1),
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const previewPromotion = async () => {
    if (!sourceSessionId || !targetSessionId) {
      showNotice('Select both the current and next academic sessions.', 'error');
      return;
    }
    setBusy('preview');
    try {
      const response = await axios.post(`${API_URL}/academic/promotions/preview`, {
        source_session_id: Number(sourceSessionId),
        target_session_id: Number(targetSessionId),
      });
      setPromotionRows((response.data?.students || []).map((resident) => ({
        ...resident,
        decision: resident.suggested_action,
      })));
      if (!(response.data?.students || []).length) {
        showNotice('No active resident enrollments were found in the selected session.', 'error');
      }
    } catch (error) {
      showNotice(errorMessage(error, 'Unable to preview the promotion.'), 'error');
    } finally {
      setBusy('');
    }
  };

  const updateDecision = (personId, decision) => {
    setPromotionRows((rows) => rows.map((row) => (
      Number(row.person_id) === Number(personId) ? { ...row, decision } : row
    )));
  };

  const executePromotion = async () => {
    if (!promotionRows.length) return;
    setBusy('execute');
    try {
      await axios.post(`${API_URL}/academic/promotions/execute`, {
        source_session_id: Number(sourceSessionId),
        target_session_id: Number(targetSessionId),
        decisions: promotionRows.map((row) => ({
          person_id: row.person_id,
          action: row.decision,
          reason: row.decision === 'repeat' ? 'Academic year repeated' : undefined,
        })),
      });
      setPromotionRows([]);
      showNotice('Resident academic years were updated and history was preserved.');
      await loadData();
    } catch (error) {
      showNotice(errorMessage(error, 'Unable to apply the promotion decisions.'), 'error');
    } finally {
      setBusy('');
    }
  };

  if (!isHostel) {
    return (
      <div className="max-w-4xl mx-auto mt-16 p-8 bg-white border border-slate-200 rounded-2xl shadow-sm text-center">
        <GraduationCap className="mx-auto text-slate-400 mb-3" size={34} />
        <h1 className="text-xl font-bold text-slate-900">Resident Academic Setup</h1>
        <p className="text-slate-500 mt-2">This page is available only for hostel businesses.</p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-violet-600 text-xs font-bold uppercase tracking-[0.18em]">
            <GraduationCap size={17} /> Hostel resident lifecycle
          </div>
          <h1 className="text-3xl font-bold text-slate-950 mt-2">Resident Academic Setup</h1>
          <p className="text-slate-500 mt-1">Configure courses and years, map HOD departments, and promote residents without losing history.</p>
        </div>
        <button
          type="button"
          onClick={loadData}
          disabled={loading}
          className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {notice && (
        <div className={`rounded-xl border px-4 py-3 text-sm font-medium ${notice.type === 'error' ? 'bg-rose-50 border-rose-200 text-rose-700' : 'bg-emerald-50 border-emerald-200 text-emerald-700'}`}>
          {notice.message}
        </div>
      )}

      <div className="grid xl:grid-cols-2 gap-6">
        <section className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-slate-200 flex items-center justify-between">
            <div>
              <h2 className="font-bold text-slate-900 flex items-center gap-2"><CalendarDays size={19} className="text-blue-600" /> Academic Sessions</h2>
              <p className="text-xs text-slate-500 mt-1">Only one session is active at a time.</p>
            </div>
            {activeSession && <StatusBadge status="ACTIVE" />}
          </div>
          <form onSubmit={submitSession} className="p-6 grid sm:grid-cols-2 gap-3 border-b border-slate-100 bg-slate-50/60">
            <input required value={sessionForm.code} onChange={(e) => setSessionForm({ ...sessionForm, code: e.target.value })} placeholder="Session code, e.g. 2026-27" className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" />
            <input required value={sessionForm.name} onChange={(e) => setSessionForm({ ...sessionForm, name: e.target.value })} placeholder="Display name" className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" />
            <label className="text-xs font-semibold text-slate-600">Start date<input required type="date" value={sessionForm.start_date} onChange={(e) => setSessionForm({ ...sessionForm, start_date: e.target.value })} className="block w-full mt-1 px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" /></label>
            <label className="text-xs font-semibold text-slate-600">End date<input required type="date" value={sessionForm.end_date} onChange={(e) => setSessionForm({ ...sessionForm, end_date: e.target.value })} className="block w-full mt-1 px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" /></label>
            <button disabled={busy === 'session'} className="sm:col-span-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white font-semibold text-sm hover:bg-blue-700 disabled:opacity-50">Create session</button>
          </form>
          <div className="p-4 space-y-2 max-h-72 overflow-y-auto">
            {config.sessions.map((session) => (
              <div key={session.id} className="flex items-center justify-between gap-3 px-4 py-3 border border-slate-200 rounded-xl">
                <div>
                  <div className="font-semibold text-slate-900">{session.name || session.code}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{session.code} · {String(session.start_date).slice(0, 10)} to {String(session.end_date).slice(0, 10)}</div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={session.status} />
                  {String(session.status).toUpperCase() === 'PLANNED' && (
                    <button type="button" onClick={() => activateSession(session)} disabled={busy === `session-${session.id}`} className="text-xs font-semibold text-blue-600 hover:text-blue-800">Activate</button>
                  )}
                </div>
              </div>
            ))}
            {!config.sessions.length && !loading && <p className="text-sm text-slate-500 text-center py-6">Create the first hostel academic session.</p>}
          </div>
        </section>

        <section className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-slate-200">
            <h2 className="font-bold text-slate-900 flex items-center gap-2"><BookOpen size={19} className="text-violet-600" /> Courses and HOD Mapping</h2>
            <p className="text-xs text-slate-500 mt-1">The selected department controls which HOD receives each resident’s leave request.</p>
          </div>
          <form onSubmit={submitProgram} className="p-6 grid sm:grid-cols-2 gap-3 border-b border-slate-100 bg-slate-50/60">
            <input required value={programForm.code} onChange={(e) => setProgramForm({ ...programForm, code: e.target.value.toUpperCase() })} placeholder="Course code, e.g. BSC-CS" className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" />
            <input required value={programForm.name} onChange={(e) => setProgramForm({ ...programForm, name: e.target.value })} placeholder="Course name" className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" />
            <select required value={programForm.department_code} onChange={(e) => setProgramForm({ ...programForm, department_code: e.target.value })} className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white">
              <option value="">Select HOD department</option>
              {departments.map((department) => <option key={department} value={department}>{department}</option>)}
            </select>
            <input required min="1" max="12" type="number" value={programForm.duration_years} onChange={(e) => setProgramForm({ ...programForm, duration_years: e.target.value })} placeholder="Duration in years" className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" />
            <select value={programForm.structure} onChange={(e) => setProgramForm({ ...programForm, structure: e.target.value, semesters_per_year: e.target.value === 'ANNUAL' ? 1 : 2 })} className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white">
              <option value="ANNUAL">Year based</option>
              <option value="SEMESTER">Semester based</option>
            </select>
            {programForm.structure === 'SEMESTER' ? (
              <input required min="1" max="4" type="number" value={programForm.semesters_per_year} onChange={(e) => setProgramForm({ ...programForm, semesters_per_year: e.target.value })} placeholder="Semesters per year" className="px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white" />
            ) : <div className="px-3 py-2.5 rounded-xl bg-slate-100 text-sm text-slate-500">One academic level per year</div>}
            {!departments.length && (
              <button type="button" onClick={() => navigate('/leave-management')} className="sm:col-span-2 text-left text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2.5">
                Create departments and assign HODs in Leave Management before adding courses. <ArrowRight size={13} className="inline ml-1" />
              </button>
            )}
            <div className="sm:col-span-2 flex gap-2">
              {editingProgramId && <button type="button" onClick={() => { setEditingProgramId(null); setProgramForm(emptyProgram); }} className="px-4 py-2.5 rounded-xl border border-slate-200 text-slate-600 font-semibold text-sm">Cancel</button>}
              <button disabled={busy === 'program' || !departments.length} className="flex-1 px-4 py-2.5 rounded-xl bg-violet-600 text-white font-semibold text-sm hover:bg-violet-700 disabled:opacity-50">{editingProgramId ? 'Update course' : 'Add course'}</button>
            </div>
          </form>
          <div className="p-4 space-y-2 max-h-72 overflow-y-auto">
            {config.programs.map((program) => (
              <div key={program.id} className="flex items-center justify-between gap-3 px-4 py-3 border border-slate-200 rounded-xl">
                <div>
                  <div className="font-semibold text-slate-900">{program.name} <span className="text-slate-400 font-medium">({program.code})</span></div>
                  <div className="text-xs text-slate-500 mt-1">{program.duration_years} year{Number(program.duration_years) === 1 ? '' : 's'} · HOD department: <strong className="text-slate-700">{program.department_code || program.code}</strong></div>
                </div>
                <button type="button" onClick={() => editProgram(program)} className="p-2 rounded-lg text-slate-500 hover:text-violet-700 hover:bg-violet-50" title="Edit course"><Edit3 size={16} /></button>
              </div>
            ))}
            {!config.programs.length && !loading && <p className="text-sm text-slate-500 text-center py-6">Add each hostel resident course and map its HOD department.</p>}
          </div>
        </section>
      </div>

      <section className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-5 border-b border-slate-200 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h2 className="font-bold text-slate-900 flex items-center gap-2"><Upload size={19} className="text-emerald-600" /> Import Hostel Residents</h2>
            <p className="text-sm text-slate-500 mt-1">Configure sessions and courses first, then use Residents → Bulk Import.</p>
          </div>
          <button type="button" onClick={() => navigate('/people')} className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 text-white font-semibold text-sm hover:bg-emerald-700">
            <Users size={17} /> Open Residents
          </button>
        </div>
        <div className="px-6 py-5 grid md:grid-cols-2 gap-4">
          <div className="rounded-xl border border-slate-200 p-4">
            <div className="font-semibold text-slate-800">Required Excel columns</div>
            <code className="block mt-2 text-xs leading-6 text-slate-600 whitespace-normal">admission_number, student_name, academic_session, program_code, year_of_study, division</code>
          </div>
          <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-4 text-sm text-blue-800">
            Department is derived from <strong>program_code</strong>. This prevents an Excel typo from sending leave requests to the wrong HOD.
          </div>
        </div>
      </section>

      <section className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-5 border-b border-slate-200">
          <h2 className="font-bold text-slate-900 flex items-center gap-2"><CheckCircle2 size={19} className="text-indigo-600" /> Annual Promotion and Graduation</h2>
          <p className="text-sm text-slate-500 mt-1">Move residents to the next year while retaining their previous session, year, room-independent identity, and leave history.</p>
        </div>
        <div className="p-6 flex flex-col lg:flex-row gap-3">
          <select value={sourceSessionId} onChange={(e) => { setSourceSessionId(e.target.value); setPromotionRows([]); }} className="flex-1 px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white">
            <option value="">Current/source session</option>
            {config.sessions.map((session) => <option key={session.id} value={session.id}>{session.name || session.code} ({session.status})</option>)}
          </select>
          <select value={targetSessionId} onChange={(e) => { setTargetSessionId(e.target.value); setPromotionRows([]); }} className="flex-1 px-3 py-2.5 border border-slate-200 rounded-xl text-sm bg-white">
            <option value="">Next/target session</option>
            {config.sessions.map((session) => <option key={session.id} value={session.id}>{session.name || session.code} ({session.status})</option>)}
          </select>
          <button type="button" onClick={previewPromotion} disabled={busy === 'preview'} className="px-5 py-2.5 rounded-xl bg-indigo-600 text-white font-semibold text-sm hover:bg-indigo-700 disabled:opacity-50">Preview residents</button>
        </div>

        {promotionRows.length > 0 && (
          <div className="border-t border-slate-200">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr><th className="text-left px-5 py-3">Resident</th><th className="text-left px-5 py-3">Course / Department</th><th className="text-left px-5 py-3">Current</th><th className="text-left px-5 py-3">Decision</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {promotionRows.map((row) => (
                    <tr key={row.person_id}>
                      <td className="px-5 py-3 font-semibold text-slate-900">{row.student_name}</td>
                      <td className="px-5 py-3 text-slate-600">{row.program_code}<div className="text-xs text-slate-400">{row.department_code || row.program_code}</div></td>
                      <td className="px-5 py-3 text-slate-600">Year {row.year_of_study} · {row.division}</td>
                      <td className="px-5 py-3">
                        <select value={row.decision} onChange={(e) => updateDecision(row.person_id, e.target.value)} className="px-3 py-2 border border-slate-200 rounded-lg bg-white">
                          {row.suggested_action === 'graduate' ? <option value="graduate">Graduate</option> : <option value="promote">Promote to Year {row.target_year_of_study}</option>}
                          <option value="repeat">Repeat current year</option>
                          <option value="leave">Left hostel/course</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="px-6 py-4 bg-slate-50 flex items-center justify-between gap-4">
              <p className="text-xs text-slate-500">The target session must be active before applying these decisions.</p>
              <button type="button" onClick={executePromotion} disabled={busy === 'execute'} className="px-5 py-2.5 rounded-xl bg-slate-900 text-white font-semibold text-sm hover:bg-slate-800 disabled:opacity-50">Apply {promotionRows.length} decisions</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default AcademicManagement;
