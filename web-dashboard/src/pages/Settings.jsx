import { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { 
  Save, 
  HelpCircle,
  Bell,
  Lock,
  Camera,
  Database,
  Users as UsersIcon,
  Trash2,
  Edit2,
  Plus,
  X
} from 'lucide-react';

const API_URL = 'http://127.0.0.1:5001/api';

const Settings = () => {
  const { user } = useAuth();
  const [threshold, setThreshold] = useState(0.6);
  const [cooldown, setCooldown] = useState(30);
  
  // User Management State
  const [systemUsers, setSystemUsers] = useState([]);
  const [showUserModal, setShowUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [userForm, setUserForm] = useState({ username: '', password: '', role: 'user' });

  useEffect(() => {
    if (user?.role === 'admin') {
      fetchSystemUsers();
    }
  }, [user]);

  const fetchSystemUsers = async () => {
    try {
      const res = await axios.get(`${API_URL}/users`);
      setSystemUsers(res.data.users);
    } catch (error) {
      console.error("Error fetching system users:", error);
    }
  };

  const handleSaveUser = async () => {
    try {
      if (editingUser) {
        // Update existing user
        const payload = {};
        if (userForm.password) payload.password = userForm.password;
        payload.role = userForm.role;

        await axios.put(`${API_URL}/users/${editingUser.username}`, payload);
      } else {
        // Create new user
        await axios.post(`${API_URL}/users`, userForm);
      }
      setShowUserModal(false);
      setEditingUser(null);
      setUserForm({ username: '', password: '', role: 'user' });
      fetchSystemUsers();
    } catch (error) {
      alert(error.response?.data?.error || "Operation failed");
    }
  };

  const handleDeleteUser = async (username) => {
    if (!confirm(`Are you sure you want to delete user ${username}?`)) return;
    try {
      await axios.delete(`${API_URL}/users/${username}`);
      fetchSystemUsers();
    } catch (error) {
      alert(error.response?.data?.error || "Delete failed");
    }
  };

  const openEditModal = (u) => {
    setEditingUser(u);
    setUserForm({ username: u.username, password: '', role: u.role }); // Password blank for no change
    setShowUserModal(true);
  };

  const openAddModal = () => {
    setEditingUser(null);
    setUserForm({ username: '', password: '', role: 'user' });
    setShowUserModal(true);
  };

  const Section = ({ title, icon: Icon, children, action }) => (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-6">
      <div className="p-6 border-b border-slate-200 flex items-center justify-between bg-slate-50/50">
        <div className="flex items-center space-x-3">
            <Icon size={20} className="text-slate-500" />
            <h3 className="text-lg font-bold text-slate-800">{title}</h3>
        </div>
        {action}
      </div>
      <div className="p-6 space-y-6">
        {children}
      </div>
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">System Configuration</h1>
          <p className="text-slate-500">Manage global settings for the attendance system.</p>
        </div>
        <button className="flex items-center space-x-2 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors shadow-sm">
          <Save size={18} />
          <span>Save Changes</span>
        </button>
      </div>

      {user?.role === 'admin' && (
        <Section 
          title="System Access" 
          icon={UsersIcon}
          action={
            <button 
              onClick={openAddModal}
              className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600/10 text-blue-600 rounded-lg hover:bg-blue-600/20 text-sm font-medium transition-colors"
            >
              <Plus size={16} />
              <span>Add User</span>
            </button>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="pb-3 font-semibold text-slate-600 text-sm">Username</th>
                  <th className="pb-3 font-semibold text-slate-600 text-sm">Role</th>
                  <th className="pb-3 font-semibold text-slate-600 text-sm text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="text-slate-700">
                {systemUsers.map((u) => (
                  <tr key={u.username} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="py-3 text-sm">{u.username}</td>
                    <td className="py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                        u.role === 'admin' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'
                      }`}>
                        {u.role.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-3 flex justify-end space-x-2">
                      <button 
                        onClick={() => openEditModal(u)}
                        className="p-1.5 hover:bg-slate-200 rounded text-slate-500 hover:text-blue-600 transition-colors"
                        title="Edit Password/Role"
                      >
                        <Edit2 size={16} />
                      </button>
                      {u.username !== 'admin' && (
                        <button 
                          onClick={() => handleDeleteUser(u.username)}
                          className="p-1.5 hover:bg-red-100 rounded text-slate-500 hover:text-red-600 transition-colors"
                          title="Delete User"
                        >
                          <Trash2 size={16} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="Face Recognition Engine" icon={Camera}>
        <div>
          <div className="flex justify-between items-center mb-2">
            <label className="text-sm font-semibold text-slate-700 flex items-center">
              Confidence Threshold
              <HelpCircle size={14} className="ml-2 text-slate-400 cursor-help" />
            </label>
            <span className="text-sm font-mono text-blue-600 font-bold">{(threshold * 100).toFixed(0)}%</span>
          </div>
          <input 
            type="range" 
            min="0.4" 
            max="0.9" 
            step="0.05" 
            value={threshold}
            onChange={(e) => setThreshold(parseFloat(e.target.value))}
            className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <p className="text-xs text-slate-500 mt-2">
            Minimum confidence score required to mark a face as recognized. Higher values reduce false positives but may miss legitimate faces.
          </p>
        </div>

        <div>
          <div className="flex justify-between items-center mb-2">
            <label className="text-sm font-semibold text-slate-700">Duplicate Detection Cooldown</label>
            <span className="text-sm font-mono text-blue-600 font-bold">{cooldown}s</span>
          </div>
          <input 
            type="range" 
            min="5" 
            max="300" 
            step="5" 
            value={cooldown}
            onChange={(e) => setCooldown(parseInt(e.target.value))}
            className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <p className="text-xs text-slate-500 mt-2">
            Time to wait before logging another entry for the same person. Prevents spamming logs.
          </p>
        </div>
      </Section>

      <Section title="Attendance Rules" icon={Database}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
           <div>
             <label className="block text-sm font-semibold text-slate-700 mb-2">Work Start Time</label>
             <input type="time" defaultValue="09:00" className="w-full px-3 py-2 border border-slate-300 rounded-lg text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20" />
           </div>
           <div>
             <label className="block text-sm font-semibold text-slate-700 mb-2">Late Mark Threshold</label>
             <input type="time" defaultValue="09:30" className="w-full px-3 py-2 border border-slate-300 rounded-lg text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20" />
           </div>
        </div>
        <div className="flex items-center space-x-3 pt-4 border-t border-slate-100">
          <input type="checkbox" id="auto_checkout" className="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500" />
          <label htmlFor="auto_checkout" className="text-sm text-slate-700">Auto check-out employees at midnight if no exit recorded</label>
        </div>
      </Section>

      <Section title="Notifications & Interface" icon={Bell}>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-slate-800">Voice Greeting</p>
              <p className="text-xs text-slate-500">Play text-to-speech greeting upon successful recognition</p>
            </div>
            <div className="relative inline-block w-12 mr-2 align-middle select-none transition duration-200 ease-in">
                <input type="checkbox" name="toggle" id="toggle" className="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer checked:right-0 checked:border-green-400"/>
                <label htmlFor="toggle" className="toggle-label block overflow-hidden h-6 rounded-full bg-gray-300 cursor-pointer checked:bg-green-400"></label>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-slate-800">Admin Alerts</p>
              <p className="text-xs text-slate-500">Email admin on unknown face detection</p>
            </div>
             <div className="relative inline-block w-12 mr-2 align-middle select-none transition duration-200 ease-in">
                <input type="checkbox" name="toggle2" id="toggle2" className="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer"/>
                <label htmlFor="toggle2" className="toggle-label block overflow-hidden h-6 rounded-full bg-gray-300 cursor-pointer"></label>
            </div>
          </div>
        </div>
      </Section>

      {/* User Modal */}
      {showUserModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
              <h3 className="font-bold text-lg text-slate-800">
                {editingUser ? 'Edit User' : 'Add New User'}
              </h3>
              <button onClick={() => setShowUserModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={20} />
              </button>
            </div>
            
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Username</label>
                <input 
                  type="text" 
                  value={userForm.username}
                  onChange={(e) => setUserForm({...userForm, username: e.target.value})}
                  disabled={!!editingUser}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:bg-slate-100 disabled:text-slate-500"
                  placeholder="Enter username"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  {editingUser ? 'New Password (leave blank to keep)' : 'Password'}
                </label>
                <input 
                  type="text" 
                  value={userForm.password}
                  onChange={(e) => setUserForm({...userForm, password: e.target.value})}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="Enter password"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Role</label>
                <select 
                  value={userForm.role}
                  onChange={(e) => setUserForm({...userForm, role: e.target.value})}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                >
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
            </div>

            <div className="px-6 py-4 bg-slate-50 flex justify-end space-x-3">
              <button 
                onClick={() => setShowUserModal(false)}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-200 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button 
                onClick={handleSaveUser}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-sm transition-colors"
              >
                {editingUser ? 'Update User' : 'Create User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Settings;