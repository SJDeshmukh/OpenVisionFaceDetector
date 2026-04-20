import { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Plus, Trash2, Save, BookOpen, X } from 'lucide-react';

const Classes = () => {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ class_year: '', division: '', branch: '', label: '' });
  const [loading, setLoading] = useState(false);
  const [managingClass, setManagingClass] = useState(null);

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

  useEffect(() => { fetchItems(); }, []);

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
      <form onSubmit={create} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm grid grid-cols-1 md:grid-cols-5 gap-3">
        <input className="p-2 border rounded-lg" placeholder="Year" value={form.class_year} onChange={e => setForm({ ...form, class_year: e.target.value })} />
        <input className="p-2 border rounded-lg" placeholder="Division" value={form.division} onChange={e => setForm({ ...form, division: e.target.value })} />
        <input className="p-2 border rounded-lg" placeholder="Branch" value={form.branch} onChange={e => setForm({ ...form, branch: e.target.value })} />
        <input className="p-2 border rounded-lg" placeholder="Label (e.g., TY-CSE-A)" value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} />
        <button className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">
          <Plus size={16} /> Add
        </button>
      </form>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-left">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="p-3">Label</th>
              <th className="p-3">Year</th>
              <th className="p-3">Division</th>
              <th className="p-3">Branch</th>
              <th className="p-3">Subjects/Faculty</th>
              <th className="p-3 w-48">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="6" className="p-6 text-center text-slate-400">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="6" className="p-6 text-center text-slate-400">No classes yet</td></tr>
            ) : items.map(it => (
              <Row key={it.id} it={it} onSave={update} onDelete={del} onManageSubjects={() => setManagingClass(it)} />
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
        />
      )}
    </div>
  );
};

const Row = ({ it, onSave, onDelete, onManageSubjects }) => {
  const [edit, setEdit] = useState({ ...it });
  useEffect(() => {
    setEdit({ ...it });
  }, [it]);
  return (
    <tr className="border-b border-slate-100">
      <td className="p-3">
        <input value={edit.label || ''} onChange={e => setEdit({ ...edit, label: e.target.value })} className="p-2 border rounded-lg w-full" />
      </td>
      <td className="p-3">
        <input value={edit.class_year || ''} onChange={e => setEdit({ ...edit, class_year: e.target.value })} className="p-2 border rounded-lg w-full" />
      </td>
      <td className="p-3">
        <input value={edit.division || ''} onChange={e => setEdit({ ...edit, division: e.target.value })} className="p-2 border rounded-lg w-full" />
      </td>
      <td className="p-3">
        <input value={edit.branch || ''} onChange={e => setEdit({ ...edit, branch: e.target.value })} className="p-2 border rounded-lg w-full" />
      </td>
      <td className="p-3">
        <span className="text-sm text-slate-600">
          {it.mapped_subjects?.length || 0} configured
        </span>
      </td>
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
    </tr>
  );
};

const ManageSubjectsModal = ({ cls, onClose, onUpdate }) => {
  const [subjects, setSubjects] = useState(cls.mapped_subjects || []);
  const [newSubj, setNewSubj] = useState({ subject: '', faculty: '' });

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
      <div className="bg-white rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-6 border-b border-slate-100 bg-slate-50/50">
          <div>
            <h3 className="font-semibold text-slate-800 text-lg">Manage Subjects & Faculty</h3>
            <p className="text-sm text-slate-500 mt-1">Configure mapping for {cls.label || cls.class_year}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-full transition-colors text-slate-500"><X size={20} /></button>
        </div>

        <div className="p-6 flex-1 overflow-y-auto space-y-4">
          <div className="flex gap-2 items-end">
            <div className="flex-1">
              <label className="text-xs text-slate-500 mb-1 block">Subject *</label>
              <input type="text" placeholder="e.g. Mathematics" value={newSubj.subject} onChange={e => setNewSubj(p => ({ ...p, subject: e.target.value }))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none" />
            </div>
            <div className="flex-1">
              <label className="text-xs text-slate-500 mb-1 block">Teacher</label>
              <input type="text" placeholder="Teacher name" value={newSubj.faculty} onChange={e => setNewSubj(p => ({ ...p, faculty: e.target.value }))} className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-emerald-500 outline-none" />
            </div>
            <button onClick={handleAdd} disabled={!newSubj.subject.trim()} className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 inline-flex items-center gap-1 font-medium text-sm">
              <Plus size={16} /> Add
            </button>
          </div>

          <div className="space-y-2 mt-4">
            {subjects.length === 0 ? (
              <div className="p-4 border border-dashed border-slate-200 rounded-xl text-center text-sm text-slate-500 bg-slate-50">
                No subjects mapped for this class yet.
              </div>
            ) : (
              subjects.map((item, i) => (
                <div key={i} className="flex items-center justify-between p-3 border border-slate-100 rounded-xl bg-white shadow-sm">
                  <div>
                    <div className="font-medium text-slate-800 text-sm">{item.subject}</div>
                    {item.faculty && <div className="text-xs text-slate-500">Teacher: {item.faculty}</div>}
                  </div>
                  <button onClick={() => handleRemove(i)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-md transition-colors"><Trash2 size={16} /></button>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="p-6 border-t border-slate-100 bg-slate-50 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-slate-600 hover:bg-slate-200 rounded-xl font-medium transition-colors">Cancel</button>
          <button onClick={() => onUpdate(subjects)} className="px-5 py-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 font-medium transition-colors inline-flex items-center gap-2 shadow-sm">
            <Save size={16} /> Save Changes
          </button>
        </div>
      </div>
    </div>
  );
};

export default Classes;

