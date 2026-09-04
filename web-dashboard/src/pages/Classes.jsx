import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Plus, Trash2, Save, BookOpen, X, Search, ChevronDown, GraduationCap } from 'lucide-react';

const Classes = () => {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ class_year: '', division: '', branch: '', label: '' });
  const [loading, setLoading] = useState(false);
  const [managingClass, setManagingClass] = useState(null);
  const [masterSubjects, setMasterSubjects] = useState([]);
  const [facultyLogins, setFacultyLogins] = useState([]);
  const [showMasterPanel, setShowMasterPanel] = useState(false);
  const [masterForm, setMasterForm] = useState({ class_year: '', branch: '', subject_name: '' });

  const fetchItems = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/classes`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setItems(res.data?.classes || []);
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Error loading classes');
    } finally {
      setLoading(false);
    }
  };

  const fetchMasterSubjects = async () => {
    try {
      const res = await axios.get(`${API_URL}/subject-master`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setMasterSubjects(res.data?.subjects || []);
    } catch (e) {
      console.error('Error fetching master subjects', e);
    }
  };

  const fetchFaculty = async () => {
    try {
      const res = await axios.get(`${API_URL}/bulk-registration/faculty-logins`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const emails = (res.data?.logins || [])
        .map(l => l.email || l.username)
        .filter(Boolean);
      setFacultyLogins(emails);
    } catch (e) {
      console.error('Error fetching faculty', e);
    }
  };

  useEffect(() => {
    if (!user?.token) return;
    fetchItems(); 
    fetchMasterSubjects();
    fetchFaculty();
  }, [user?.token]);

  const addMasterSubject = async (e) => {
    e.preventDefault();
    if (!masterForm.subject_name.trim()) return;
    try {
      await axios.post(`${API_URL}/subject-master`, masterForm, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setMasterForm({ ...masterForm, subject_name: '' });
      await fetchMasterSubjects();
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to add master subject');
    }
  };

  const deleteMasterSubject = async (id) => {
    if (!confirm('Remove this master subject?')) return;
    try {
      await axios.delete(`${API_URL}/subject-master/${id}`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchMasterSubjects();
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to delete master subject');
    }
  };

  const create = async (e) => {
    e.preventDefault();
    try {
      const payload = { ...form, mapped_subjects: [] };
      await axios.post(`${API_URL}/classes`, payload, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setForm({ class_year: '', division: '', branch: '', label: '' });
      fetchItems();
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Create failed');
    }
  };

  const update = async (id, payload) => {
    try {
      await axios.put(`${API_URL}/classes/${id}`, payload, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchItems();
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Update failed');
    }
  };

  const del = async (id) => {
    if (!confirm('Delete this class?')) return;
    try {
      await axios.delete(`${API_URL}/classes/${id}`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchItems();
    } catch (e) {
      alert(e.response?.data?.error || e.message || 'Delete failed');
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-800">Classes</h1>
      {user?.role !== 'faculty' && (
        <form onSubmit={create} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm grid grid-cols-1 md:grid-cols-5 gap-3">
          <input className="p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Year" value={form.class_year} onChange={e => setForm({ ...form, class_year: e.target.value })} />
          <input className="p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Division" value={form.division} onChange={e => setForm({ ...form, division: e.target.value })} />
          <input className="p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Branch" value={form.branch} onChange={e => setForm({ ...form, branch: e.target.value })} />
          <input className="p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none transition-all" placeholder="Label (e.g., TY-CSE-A)" value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} />
          <button className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-all shadow-sm hover:shadow-md">
            <Plus size={16} /> Add Class
          </button>
        </form>
      )}

      {/* Subject Master Section */}
      {user?.role !== 'faculty' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <button 
            onClick={() => setShowMasterPanel(!showMasterPanel)}
            className="w-full flex items-center justify-between p-4 hover:bg-slate-50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
                <GraduationCap size={20} />
              </div>
              <div className="text-left">
                <h3 className="font-bold text-slate-800">Subject Master</h3>
                <p className="text-xs text-slate-500">Define subjects per year & branch for reuse</p>
              </div>
            </div>
            <ChevronDown size={20} className={`text-slate-400 transition-transform ${showMasterPanel ? 'rotate-180' : ''}`} />
          </button>

          {showMasterPanel && (
            <div className="p-6 border-t border-slate-100 space-y-6 bg-slate-50/50">
              <form onSubmit={addMasterSubject} className="flex flex-wrap gap-3 items-end">
                <div className="flex-1 min-w-[120px]">
                  <label className="block text-xs font-semibold text-slate-500 mb-1 uppercase tracking-wider">Year</label>
                  <input className="w-full p-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="e.g. 1st Year" value={masterForm.class_year} onChange={e => setMasterForm({...masterForm, class_year: e.target.value})} />
                </div>
                <div className="flex-1 min-w-[120px]">
                  <label className="block text-xs font-semibold text-slate-500 mb-1 uppercase tracking-wider">Branch</label>
                  <input className="w-full p-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="e.g. CSE" value={masterForm.branch} onChange={e => setMasterForm({...masterForm, branch: e.target.value})} />
                </div>
                <div className="flex-[2] min-w-[200px]">
                  <label className="block text-xs font-semibold text-slate-500 mb-1 uppercase tracking-wider">Subject Name *</label>
                  <input className="w-full p-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none" placeholder="e.g. Data Structures" value={masterForm.subject_name} onChange={e => setMasterForm({...masterForm, subject_name: e.target.value})} required />
                </div>
                <button className="px-5 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-all font-medium text-sm shadow-sm hover:shadow-md flex items-center gap-2">
                  <Plus size={16} /> Add to Master
                </button>
              </form>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {masterSubjects.length === 0 ? (
                  <p className="col-span-full py-6 text-center text-slate-400 text-sm">No master subjects defined yet.</p>
                ) : (
                  masterSubjects.map(s => (
                    <div key={s.id} className="bg-white p-3 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between group hover:border-indigo-300 transition-all">
                      <div>
                        <div className="text-sm font-bold text-slate-800">{s.subject_name}</div>
                        <div className="text-[10px] text-slate-500 uppercase font-semibold">
                          {s.class_year || 'Any Year'} • {s.branch || 'Any Branch'}
                        </div>
                      </div>
                      <button onClick={() => deleteMasterSubject(s.id)} className="p-1.5 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-left">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="p-3">Label</th>
              <th className="p-3">Year</th>
              <th className="p-3">Division</th>
              <th className="p-3">Branch</th>
              <th className="p-3">Subjects/Faculty</th>
              {user?.role !== 'faculty' && <th className="p-3 w-48">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={user?.role === 'faculty' ? 5 : 6} className="p-6 text-center text-slate-400">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={user?.role === 'faculty' ? 5 : 6} className="p-6 text-center text-slate-400">No classes yet</td></tr>
            ) : items.map(it => (
              <Row
                key={it.id}
                it={it}
                onSave={update}
                onDelete={del}
                onManageSubjects={() => {
                  setManagingClass(it);
                  fetchMasterSubjects();
                  fetchFaculty();
                }}
                role={user?.role}
              />
            ))}
          </tbody>
        </table>
      </div>

      {managingClass && (
        <ManageSubjectsModal
          cls={managingClass}
          onClose={() => setManagingClass(null)}
          onUpdate={(mapped_subjects) => {
            update(managingClass.id, { mapped_subjects });
            setManagingClass(null);
          }}
          masterSubjects={masterSubjects}
          facultyLogins={facultyLogins}
        />
      )}
    </div>
  );
};

const Row = ({ it, onSave, onDelete, onManageSubjects, role }) => {
  const [edit, setEdit] = useState({ ...it });
  useEffect(() => {
    setEdit({ ...it });
  }, [it]);

  const isFaculty = role === 'faculty';

  return (
    <tr className="border-b border-slate-100">
      <td className="p-3">
        {isFaculty ? (
          <span className="text-sm font-medium text-slate-700">{edit.label || '-'}</span>
        ) : (
          <input value={edit.label || ''} onChange={e => setEdit({ ...edit, label: e.target.value })} className="p-2 border rounded-lg w-full" />
        )}
      </td>
      <td className="p-3">
        {isFaculty ? (
          <span className="text-sm text-slate-600">{edit.class_year || '-'}</span>
        ) : (
          <input value={edit.class_year || ''} onChange={e => setEdit({ ...edit, class_year: e.target.value })} className="p-2 border rounded-lg w-full" />
        )}
      </td>
      <td className="p-3">
        {isFaculty ? (
          <span className="text-sm text-slate-600">{edit.division || '-'}</span>
        ) : (
          <input value={edit.division || ''} onChange={e => setEdit({ ...edit, division: e.target.value })} className="p-2 border rounded-lg w-full" />
        )}
      </td>
      <td className="p-3">
        {isFaculty ? (
          <span className="text-sm text-slate-600">{edit.branch || '-'}</span>
        ) : (
          <input value={edit.branch || ''} onChange={e => setEdit({ ...edit, branch: e.target.value })} className="p-2 border rounded-lg w-full" />
        )}
      </td>
      <td className="p-3">
        <div className="space-y-1">
          {it.mapped_subjects && it.mapped_subjects.length > 0 ? (
            it.mapped_subjects.map((ms, idx) => (
              <div key={idx} className="flex items-center gap-2 text-xs">
                <span className="font-semibold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">{ms.subject}</span>
                <span className="text-slate-400">by</span>
                <span className="text-slate-600">{ms.faculty || 'Unassigned'}</span>
              </div>
            ))
          ) : (
            <span className="text-sm text-slate-400 italic">No subjects mapped</span>
          )}
        </div>
      </td>
      {!isFaculty && (
        <td className="p-3">
          <div className="flex items-center gap-2">
            <button onClick={() => onSave(it.id, {
              label: edit.label,
              class_year: edit.class_year,
              division: edit.division,
              branch: edit.branch
            })} className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 inline-flex items-center gap-1 text-sm">
              <Save size={14} /> Save
            </button>
            <button onClick={onManageSubjects} className="px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 inline-flex items-center gap-1 text-sm">
              <BookOpen size={14} /> Subjects
            </button>
            <button onClick={() => onDelete(it.id)} className="px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-700 inline-flex items-center gap-1 text-sm">
              <Trash2 size={14} /> Del
            </button>
          </div>
        </td>
      )}
    </tr>
  );
};

const SearchableDropdown = ({ value, onChange, options, placeholder, icon: Icon, allowCustom = true }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const wrapperRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const safeOptions = (options || []).filter(opt => typeof opt === 'string' && opt.trim());
  const filtered = safeOptions.filter(opt =>
    opt.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="relative" ref={wrapperRef}>
      <div className="relative">
        {Icon && <Icon className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={14} />}
        <input
          type="text"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setSearch(e.target.value);
            if (!isOpen) setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          placeholder={placeholder}
          className={`w-full border border-slate-200 rounded-lg ${Icon ? 'pl-9' : 'px-3'} pr-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all`}
        />
        <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
      </div>

      {isOpen && (
        <div className="absolute z-[60] w-full mt-1 bg-white border border-slate-200 rounded-xl shadow-xl max-h-48 overflow-y-auto py-1 animate-in fade-in slide-in-from-top-2 duration-200">
          {filtered.length === 0 ? (
            allowCustom ? (
              <div className="px-3 py-2 text-xs text-slate-500 italic">
                Press Enter or click Add to use "{search}"
              </div>
            ) : (
              <div className="px-3 py-2 text-xs text-slate-400 italic">No matches found</div>
            )
          ) : (
            filtered.map((opt, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  onChange(opt);
                  setSearch('');
                  setIsOpen(false);
                }}
                className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 text-slate-700 transition-colors flex items-center gap-2"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-slate-300 group-hover:bg-indigo-500" />
                {opt}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
};

const ManageSubjectsModal = ({ cls, onClose, onUpdate, masterSubjects, facultyLogins }) => {
  const [subjects, setSubjects] = useState(cls.mapped_subjects || []);
  const [newSubj, setNewSubj] = useState({ subject: '', faculty: '' });

  const normalize = (value) => String(value || '').trim().toLowerCase();
  const classYear = normalize(cls.class_year);
  const classBranch = normalize(cls.branch);
  const subjectNames = Array.from(new Set(
    (masterSubjects || [])
      .map(s => String(s.subject_name || '').trim())
      .filter(Boolean)
  ));
  const matchingSubjectNames = new Set(
    (masterSubjects || [])
      .filter(s => {
        const subjectYear = normalize(s.class_year);
        const subjectBranch = normalize(s.branch);
        return (!subjectYear || subjectYear === classYear) && (!subjectBranch || subjectBranch === classBranch);
      })
      .map(s => String(s.subject_name || '').trim())
      .filter(Boolean)
  );
  const matchingSubjects = subjectNames.filter(name => matchingSubjectNames.has(name));
  const otherSubjects = subjectNames.filter(name => !matchingSubjectNames.has(name));

  const handleAdd = () => {
    if (!newSubj.subject.trim()) return;
    setSubjects([...subjects, { subject: newSubj.subject.trim(), faculty: newSubj.faculty.trim() }]);
    setNewSubj({ subject: '', faculty: '' });
  };

  const handleRemove = (index) => {
    setSubjects(subjects.filter((_, i) => i !== index));
  };

  return (
    <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl w-full max-w-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-6 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-50 text-indigo-600 rounded-xl">
              <BookOpen size={24} />
            </div>
            <div>
              <h3 className="font-bold text-slate-800 text-lg">Manage Subjects & Faculty</h3>
              <p className="text-sm text-slate-500">Configure mapping for <span className="font-semibold text-slate-700">{cls.label || cls.class_year}</span></p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-full transition-colors text-slate-500"><X size={20} /></button>
        </div>

        <div className="p-6 flex-1 overflow-y-auto space-y-6">
          <div className="bg-indigo-50/50 border border-indigo-100 p-4 rounded-xl flex flex-wrap lg:flex-nowrap gap-4 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs font-bold text-slate-600 mb-1.5 block uppercase tracking-tight">Subject *</label>
              <select
                value={newSubj.subject}
                onChange={e => setNewSubj(p => ({ ...p, subject: e.target.value }))}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
              >
                <option value="">{subjectNames.length ? 'Select a subject...' : 'No subjects configured'}</option>
                {matchingSubjects.length > 0 && (
                  <optgroup label="Subjects for this class">
                    {matchingSubjects.map(subject => <option key={`matching-${subject}`} value={subject}>{subject}</option>)}
                  </optgroup>
                )}
                {otherSubjects.length > 0 && (
                  <optgroup label={matchingSubjects.length ? 'Other configured subjects' : 'All configured subjects'}>
                    {otherSubjects.map(subject => <option key={`other-${subject}`} value={subject}>{subject}</option>)}
                  </optgroup>
                )}
              </select>
              {subjectNames.length === 0 && (
                <p className="mt-1.5 text-xs text-amber-600">Add a subject in Subject Master, then reopen this window.</p>
              )}
            </div>
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs font-bold text-slate-600 mb-1.5 block uppercase tracking-tight">Teacher / Faculty</label>
              <SearchableDropdown
                value={newSubj.faculty}
                onChange={val => setNewSubj(p => ({ ...p, faculty: val }))}
                options={facultyLogins}
                placeholder="Search faculty email..."
                icon={Search}
              />
            </div>
            <button 
              onClick={handleAdd} 
              disabled={!newSubj.subject.trim()} 
              className="h-[38px] px-6 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:bg-slate-300 inline-flex items-center gap-2 font-semibold text-sm transition-all shadow-sm hover:shadow-md"
            >
              <Plus size={18} /> Add
            </button>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between px-1">
              <h4 className="text-sm font-bold text-slate-700 uppercase tracking-wider">Current Mappings ({subjects.length})</h4>
              {subjects.length > 0 && (
                <button onClick={() => setSubjects([])} className="text-xs text-red-500 hover:underline font-medium">Clear All</button>
              )}
            </div>
            
            {subjects.length === 0 ? (
              <div className="py-12 border-2 border-dashed border-slate-200 rounded-2xl text-center bg-slate-50">
                <BookOpen size={40} className="mx-auto text-slate-300 mb-3" />
                <p className="text-slate-500 font-medium">No subjects mapped yet.</p>
                <p className="text-xs text-slate-400 mt-1">Add items using the form above.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2">
                {subjects.map((item, i) => (
                  <div key={i} className="flex items-center justify-between p-4 border border-slate-200 rounded-xl bg-white hover:border-indigo-200 transition-all group">
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 bg-slate-50 rounded-lg flex items-center justify-center text-indigo-600 font-bold group-hover:bg-indigo-50">
                        {item.subject.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="font-bold text-slate-800">{item.subject}</div>
                        <div className="text-sm text-slate-500 flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                          {item.faculty || 'Unassigned'}
                        </div>
                      </div>
                    </div>
                    <button onClick={() => handleRemove(i)} className="p-2 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100">
                      <Trash2 size={18} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-6 border-t border-slate-100 bg-slate-50 flex justify-end gap-3">
          <button onClick={onClose} className="px-5 py-2 text-slate-600 hover:bg-slate-200 rounded-xl font-bold transition-all">Cancel</button>
          <button onClick={() => onUpdate(subjects)} className="px-6 py-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 font-bold transition-all inline-flex items-center gap-2 shadow-lg shadow-indigo-200">
            <Save size={18} /> Save Mappings
          </button>
        </div>
      </div>
    </div>
  );
};

export default Classes;
