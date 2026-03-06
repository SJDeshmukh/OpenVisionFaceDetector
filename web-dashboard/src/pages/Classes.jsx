import { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';
import { Plus, Trash2, Save } from 'lucide-react';

const Classes = () => {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ class_year: '', division: '', branch: '', label: '' });
  const [loading, setLoading] = useState(false);

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
      await axios.post(`${API_URL}/classes`, form, {
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
              <th className="p-3 w-40">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="5" className="p-6 text-center text-slate-400">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="5" className="p-6 text-center text-slate-400">No classes yet</td></tr>
            ) : items.map(it => (
              <Row key={it.id} it={it} onSave={update} onDelete={del} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const Row = ({ it, onSave, onDelete }) => {
  const [edit, setEdit] = useState(it);
  useEffect(() => setEdit(it), [it?.id]);
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
        <div className="flex items-center gap-2">
          <button onClick={() => onSave(it.id, { label: edit.label, class_year: edit.class_year, division: edit.division, branch: edit.branch })} className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 inline-flex items-center gap-1 text-sm">
            <Save size={14} /> Save
          </button>
          <button onClick={() => onDelete(it.id)} className="px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-700 inline-flex items-center gap-1 text-sm">
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </td>
    </tr>
  );
};

export default Classes;

