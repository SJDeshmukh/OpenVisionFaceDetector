import { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { 
  MoreVertical, 
  Search, 
  Plus, 
  Filter, 
  Download,
  Trash2,
  Edit2,
  Shield,
  Upload,
  X,
  User,
  Camera
} from 'lucide-react';
import { io } from 'socket.io-client';
import { API_URL, BASE_URL } from '../config';

const People = () => {
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [shifts, setShifts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState({ 
    id: null,
    name: '', 
    phone: '', 
    department: '', 
    designation: '', 
    shift: '',
    photo: null, 
    photoPreview: null,
    templates: ''
  });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (user) {
      fetchUsers();
      fetchShifts();
      
      // Socket.IO for Real-time Updates (force polling)
      const socket = io(BASE_URL, {
        transports: ['polling'],
        upgrade: false,
        path: '/socket.io'
      });
      
      socket.on('connect', () => {
          console.log("People Socket Connected");
          if (user.vendor_id) {
              socket.emit('join_vendor', { vendor_id: user.vendor_id });
          }
      });

      socket.on('persons_updated', (data) => {
          if (String(data.vendor_id) === String(user.vendor_id)) {
              console.log("Person updated, refreshing list...");
              fetchUsers();
          }
      });

      return () => {
          socket.disconnect();
      };
    }
  }, [user]);

  const fetchUsers = async () => {
    try {
      // API call includes Authorization header automatically via AuthContext global axios defaults
      const response = await axios.get(`${API_URL}/sync/download?limit=200`);
      setUsers(response.data.faces || []);
      setLoading(false);
    } catch (error) {
      console.error("Error fetching users:", error);
      setLoading(false);
    }
  };

  const fetchShifts = async () => {
    try {
      const companyId = user?.company_id || 1;
      const response = await axios.get(`${API_URL}/companies/${companyId}`);
      if (response.data && response.data.shifts) {
        setShifts(response.data.shifts);
      }
    } catch (error) {
      console.error("Error fetching shifts:", error);
    }
  };

  const handleImageChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setFormData({ ...formData, photo: reader.result, photoPreview: reader.result });
      };
      reader.readAsDataURL(file);
    }
  };

  const openAddModal = () => {
    setIsEditing(false);
    setFormData({ 
      id: null,
      name: '', 
      phone: '', 
      department: '', 
      designation: '', 
      shift: '',
      photo: null, 
      photoPreview: null,
      templates: ''
    });
    setIsModalOpen(true);
  };

  const handleEdit = (user) => {
    setIsEditing(true);
    const dynamicFields = user.custom_data || {};
    
    setFormData({
      id: user.person_id || user.id,
      name: user.name || '',
      phone: user.phone || '',
      department: user.department || '',
      designation: user.designation || '',
      shift: user.shift || '',
      photo: user.face_image,
      photoPreview: user.face_image && user.face_image.startsWith('data:') 
        ? user.face_image 
        : `data:image/jpeg;base64,${user.face_image}`,
      templates: user.templates || '',
      ...dynamicFields
    });
    setIsModalOpen(true);
  };

  const handleDelete = async (name) => {
    if (window.confirm(`Are you sure you want to delete ${name}?`)) {
      try {
        await axios.delete(`${API_URL}/sync/delete/${name}`);
        // Socket.IO will handle the refresh, but we can optimistically update or just wait
      } catch (error) {
        console.error("Error deleting user:", error);
        alert("Failed to delete user");
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.name || !formData.photo) return;
    
    setSubmitting(true);
    try {
      const payload = {
        person_id: formData.id,
        name: formData.name,
        face_image: formData.photo,
        templates: formData.templates,
        ...formData // Spread all other dynamic fields
      };

      // Cleanup
      delete payload.photoPreview;
      delete payload.photo; 
      delete payload.id; 

      const response = await axios.post(`${API_URL}/sync/upload`, payload);
      if (response.data.status === 'success') {
        setIsModalOpen(false);
        setFormData({ 
            id: null,
            name: '', 
            phone: '', 
            department: '', 
            designation: '', 
            shift: '',
            photo: null, 
            photoPreview: null,
            templates: ''
        });
        fetchUsers(); 
      }
    } catch (error) {
      console.error("Error registering user:", error);
      alert("Failed to register user");
    } finally {
      setSubmitting(false);
    }
  };

  // Determine columns based on Vendor Config (SuperAdmin defined)
  const getColumns = () => {
    if (user?.vendor_config && Array.isArray(user.vendor_config) && user.vendor_config.length > 0) {
      return user.vendor_config;
    }
    // Fallback Defaults
    return [
      { field: 'department', label: 'Department' },
      { field: 'shift', label: 'Shift' },
      { field: 'designation', label: 'Designation' }
    ];
  };

  const columns = getColumns();

  const getCellValue = (person, field) => {
    // 1. Check custom_data (Priority for dynamic fields)
    if (person.custom_data && person.custom_data[field]) {
      return person.custom_data[field];
    }
    // 2. Check root properties (Legacy/Fallback)
    if (person[field]) {
      return person[field];
    }
    return '-';
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">People Management</h1>
          <p className="text-slate-500">Manage employees and their facial data.</p>
        </div>
        <div className="flex space-x-3">
          <button className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors">
            <Upload size={18} />
            <span>Import</span>
          </button>
          <button 
            onClick={openAddModal}
            className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors shadow-sm">
            <Plus size={18} />
            <span>Add Employee</span>
          </button>
        </div>
      </div>

      {/* Filters & Search */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col sm:flex-row gap-4 justify-between items-center">
        <div className="relative w-full sm:w-96">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
          <input 
            type="text" 
            placeholder="Search employees by name or ID..." 
            className="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
          />
        </div>
        <div className="flex items-center space-x-3 w-full sm:w-auto">
          <button className="flex items-center space-x-2 px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 text-sm font-medium">
            <Filter size={16} />
            <span>Filters</span>
          </button>
          <button className="flex items-center space-x-2 px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 text-sm font-medium">
            <Download size={16} />
            <span>Export</span>
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Employee</th>
                {columns.map(col => (
                  <th key={col.field} className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    {col.label}
                  </th>
                ))}
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={columns.length + 2} className="px-6 py-8 text-center text-slate-500">Loading employees...</td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={columns.length + 2} className="px-6 py-8 text-center text-slate-500">No employees found.</td>
                </tr>
              ) : (
                users.map((user, idx) => (
                  <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        {user.face_image ? (
                          <img 
                            src={user.face_image.startsWith('data:') ? user.face_image : `data:image/jpeg;base64,${user.face_image}`} 
                            alt={user.name} 
                            className="h-10 w-10 rounded-full object-cover mr-3 border border-slate-200"
                          />
                        ) : (
                          <div className="h-10 w-10 rounded-full bg-slate-200 flex items-center justify-center text-slate-600 font-bold text-sm mr-3">
                            {user.name.charAt(0)}
                          </div>
                        )}
                        <div>
                          <div className="text-sm font-medium text-slate-900">{user.name}</div>
                          <div className="text-xs text-slate-500 font-mono">{user.id}</div>
                        </div>
                      </div>
                    </td>
                    
                    {columns.map(col => (
                      <td key={col.field} className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                        {getCellValue(user, col.field)}
                      </td>
                    ))}

                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex justify-end space-x-2">
                        <button 
                          onClick={() => handleEdit(user)}
                          className="p-1 text-slate-400 hover:text-blue-600 transition-colors">
                          <Edit2 size={16} />
                        </button>
                        <button 
                          onClick={() => handleDelete(user.name)}
                          className="p-1 text-slate-400 hover:text-red-600 transition-colors">
                          <Trash2 size={16} />
                        </button>
                        <button className="p-1 text-slate-400 hover:text-slate-600 transition-colors">
                          <MoreVertical size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        
        {/* Pagination */}
        <div className="px-6 py-4 border-t border-slate-200 flex items-center justify-between">
          <div className="text-sm text-slate-500">
            Showing <span className="font-medium">1</span> to <span className="font-medium">{users.length}</span> of <span className="font-medium">{users.length}</span> results
          </div>
          <div className="flex space-x-2">
            <button className="px-3 py-1 border border-slate-200 rounded text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50" disabled>Previous</button>
            <button className="px-3 py-1 border border-slate-200 rounded text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50" disabled>Next</button>
          </div>
        </div>
      </div>

      {/* Registration Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center p-6 border-b border-slate-100 sticky top-0 bg-white z-10">
              <h2 className="text-xl font-bold text-slate-800">{isEditing ? 'Edit Employee' : 'Add New Employee'}</h2>
              <button onClick={() => setIsModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                <X size={24} />
              </button>
            </div>
            
            <form onSubmit={handleSubmit} className="p-6 space-y-6">
              <div className="flex flex-col items-center justify-center space-y-4">
                <div className="relative group cursor-pointer">
                  <div className="w-32 h-32 rounded-full bg-slate-100 flex items-center justify-center overflow-hidden border-2 border-dashed border-slate-300 group-hover:border-blue-500 transition-colors">
                    {formData.photoPreview ? (
                      <img src={formData.photoPreview} alt="Preview" className="w-full h-full object-cover" />
                    ) : (
                      <div className="text-center p-4">
                        <Camera className="mx-auto text-slate-400 mb-2" size={32} />
                        <span className="text-xs text-slate-400">Upload Photo</span>
                      </div>
                    )}
                  </div>
                  <input 
                    type="file" 
                    accept="image/*"
                    onChange={handleImageChange}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  />
                </div>
                <p className="text-sm text-slate-500">Click to upload a clear face photo</p>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">Full Name</label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                  <input 
                    type="text" 
                    value={formData.name}
                    onChange={(e) => setFormData({...formData, name: e.target.value})}
                    placeholder="e.g. John Doe"
                    className={`w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 ${isEditing ? 'opacity-50 cursor-not-allowed' : ''}`}
                    required
                    readOnly={isEditing}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">Phone</label>
                <input 
                    type="tel" 
                    value={formData.phone}
                    onChange={(e) => setFormData({...formData, phone: e.target.value})}
                    placeholder="e.g. +1234567890"
                    className="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                />
              </div>

              {/* Dynamic Fields Rendering */}
              <div className="space-y-4">
                  {columns.map((col, idx) => {
                      const fieldKey = col.key || col.field;
                      // Skip name/phone as they are already handled above
                      if (['name', 'phone'].includes(fieldKey)) return null;

                      return (
                          <div key={idx} className="space-y-2">
                              <label className="text-sm font-medium text-slate-700">{col.label}</label>
                              {col.type === 'select' || fieldKey === 'shift' ? (
                                  <select 
                                      value={formData[fieldKey] || ''}
                                      onChange={(e) => setFormData({...formData, [fieldKey]: e.target.value})}
                                      className="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                                  >
                                      <option value="">Select {col.label}</option>
                                      {fieldKey === 'shift' ? (
                                          shifts.map((s, sIdx) => (
                                              <option key={sIdx} value={s.name}>{s.name} ({s.start_time} - {s.end_time})</option>
                                          ))
                                      ) : (
                                          col.options && col.options.map((opt, oId) => (
                                              <option key={oId} value={opt}>{opt}</option>
                                          ))
                                      )}
                                  </select>
                              ) : (
                                  <input 
                                      type={col.type || 'text'}
                                      value={formData[fieldKey] || ''}
                                      onChange={(e) => setFormData({...formData, [fieldKey]: e.target.value})}
                                      placeholder={`Enter ${col.label}`}
                                      className="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                                  />
                              )}
                          </div>
                      );
                  })}
              </div>

              <div className="flex gap-3 pt-2">
                <button 
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="flex-1 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={submitting || !formData.name || !formData.photo}
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting ? 'Saving...' : (isEditing ? 'Save Changes' : 'Register Employee')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default People;
