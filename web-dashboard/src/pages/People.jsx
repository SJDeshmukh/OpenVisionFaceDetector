import { useState, useEffect, useMemo } from 'react';
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
import { useSocket } from '../context/SocketContext';
import { API_URL, BASE_URL } from '../config';

const People = () => {
  const { user } = useAuth();
  const personLabel = (user?.vertical && ['school', 'hostel'].includes(String(user.vertical).toLowerCase())) ? 'Student' : 'Employee';
  const [users, setUsers] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
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
    templates: '',
    class_id: ''
  });
  const [submitting, setSubmitting] = useState(false);
  const [vendorConfig, setVendorConfig] = useState([]);
  const [vendorDepartments, setVendorDepartments] = useState([]);
  const [vendorClasses, setVendorClasses] = useState([]);
  const [bulkAttendanceFields, setBulkAttendanceFields] = useState([]);
  const [isBulkImportModalOpen, setIsBulkImportModalOpen] = useState(false);
  const [bulkImportProgress, setBulkImportProgress] = useState(null);
  const [bulkImportError, setBulkImportError] = useState(null);

  const { socket, joinVendor } = useSocket();
  useEffect(() => {
    if (user) {
      // Load initial data from localStorage for instant loading
      const cachedUsers = localStorage.getItem(`people_cache_${user?.vendor_id}`);
      if (cachedUsers) {
        try {
          setUsers(JSON.parse(cachedUsers));
          setLoading(false);
        } catch (e) {
          console.error("Error parsing people cache:", e);
        }
      }

      fetchUsers();
      fetchShifts();
      fetchConfig();

      if (socket) {
        socket.on('connect', () => {
          if (user.vendor_id) {
            joinVendor(user.vendor_id);
          }
        });

        socket.on('persons_updated', (data) => {
          if (String(data.vendor_id) === String(user.vendor_id)) {
            console.log("Person updated, refreshing list...");
            fetchUsers();
          }
        });
      }

      return () => { };
    }
  }, [user, socket]);

  const fetchUsers = async () => {
    try {
      const response = await axios.get(`${API_URL}/sync/download?limit=200`);
      const faces = response.data.faces || [];
      setUsers(faces);
      setLoading(false);
      // Save to cache
      localStorage.setItem(`people_cache_${user?.vendor_id}`, JSON.stringify(faces));
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

  // Fetch all dynamic config (registration fields, departments, classes, bulk fields)
  const fetchConfig = () => {
    if (!user?.vendor_id) return;
    
    axios.get(`${API_URL}/admin/vendors/${user.vendor_id}/registration-config`)
      .then(res => setVendorConfig(res.data.config || []))
      .catch(() => setVendorConfig([]));

    axios.get(`${API_URL}/leave/admin/departments`, { params: { vendor_id: user.vendor_id } })
      .then(res => setVendorDepartments(res.data.departments || []))
      .catch(() => setVendorDepartments([]));

    axios.get(`${API_URL}/classes`)
      .then(res => setVendorClasses(res.data.classes || []))
      .catch(() => setVendorClasses([]));

    if (user.features?.includes('bulk_image_attendance')) {
      axios.get(`${API_URL}/bulk-attendance/config`)
        .then(res => setBulkAttendanceFields(res.data.fields || []))
        .catch(() => setBulkAttendanceFields([]));
    }
  };

  const handleImageChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    try {
      // Compress the image before using it
      const compressedDataUrl = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
          let { width, height } = img;
          const maxDim = 640;
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
          resolve(canvas.toDataURL('image/webp', 0.6));
        };
        img.onerror = reject;

        const reader = new FileReader();
        reader.onload = (ev) => { img.src = ev.target.result; };
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });

      setFormData({ ...formData, photo: compressedDataUrl, photoPreview: compressedDataUrl });
    } catch (error) {
      console.error("Error compressing image:", error);
      alert("Failed to process image. Please try a different photo.");
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
      templates: '',
      class_id: ''
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
      photoPreview: user.image_url
        ? user.image_url
        : (user.face_image && (user.face_image.startsWith('http') || user.face_image.startsWith('data:'))
          ? user.face_image
          : (user.face_image ? `data:image/jpeg;base64,${user.face_image}` : null)),
      templates: user.templates || '',
      class_id: user.custom_data?.class_id || '',
      ...dynamicFields
    });
    setIsModalOpen(true);
  };

  const handleDelete = async (id, name) => {
    if (window.confirm(`Are you sure you want to delete ${name}?`)) {
      try {
        const resp = await axios.delete(`${API_URL}/sync/delete/id/${id}`);
        if (resp.data && resp.data.status === 'success') {
          setUsers(prev => prev.filter(u => u.id !== id));
        } else {
          const msg = resp.data?.error || 'Failed to delete';
          alert(msg);
        }
      } catch (error) {
        console.error("Error deleting user:", error);
        const msg = error.response?.data?.error || "Failed to delete user";
        alert(msg);
      }
    }
  };

  const handleClearAll = async () => {
    if (window.confirm("CRITICAL: This will delete ALL registered people and reset the registration configuration. This action cannot be undone. Are you sure?")) {
      try {
        const resp = await axios.delete(`${API_URL}/sync/delete-all`);
        if (resp.data && resp.data.status === 'success') {
          setUsers([]);
          // Clear stale cache
          localStorage.removeItem(`people_cache_${user?.vendor_id}`);
          // Re-fetch config so the UI reflects the cleared state
          fetchConfig();
          alert("All data and configurations cleared. Upload a new Excel to start fresh.");
        } else {
          alert(resp.data?.error || "Failed to clear all");
        }
      } catch (error) {
        console.error("Error clearing all:", error);
        alert(error.response?.data?.error || "Failed to clear data.");
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.name) return;

    setSubmitting(true);
    try {
      const activeColumns = getColumns();
      const missingRequired = (activeColumns || []).filter(f => f.required).some(f => {
        const key = f.key || f.field;
        // Basic fields (name/phone) are validated separately or are always present
        if (['name', 'phone', 'full_name', 'mobile_number'].includes(key)) return false;
        return !formData[key] || String(formData[key]).trim() === '';
      });
      if (missingRequired) {
        alert("Please fill all required registration fields");
        setSubmitting(false);
        return;
      }
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

      // Map class_id to scope fields if selected (Prefer these over manual Year/Div inputs)
      if (formData.class_id) {
        const selectedClass = vendorClasses.find(c => String(c.id) === String(formData.class_id));
        if (selectedClass) {
          payload.class_year = selectedClass.class_year;
          payload.division = selectedClass.division;
          payload.branch = selectedClass.branch;
          // Store original mapping in custom_data
          payload.custom_data = JSON.stringify({
             ...JSON.parse(formData.custom_data || '{}'),
             class_id: formData.class_id,
             class_year: selectedClass.class_year,
             division: selectedClass.division,
             branch: selectedClass.branch
          });
        }
      }

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
      const msg = error?.response?.data?.error || "Failed to register user";
      alert(msg);
    } finally {
      setSubmitting(false);
    }
  };

  // Determine columns based on Vendor Config (SuperAdmin defined)
  const getColumns = () => {
    let baseColumns = [];
    
    // 1. Prioritize Vendor Registration Config (Mobile Registration Fields)
    if (vendorConfig && Array.isArray(vendorConfig) && vendorConfig.length > 0) {
        baseColumns = [...vendorConfig];
    } else if (user?.features?.includes('bulk_image_attendance')) {
      // Fallback logic
      (bulkAttendanceFields || []).forEach(f => {
        let fieldName = f.name;
        if (['mobile_number', 'contact_number'].includes(fieldName.toLowerCase())) {
            fieldName = 'phone';
        }
        baseColumns.push({ 
          field: fieldName, 
          key: fieldName, 
          label: f.label, 
          required: f.required, 
          type: f.type, 
          options: f.options 
        });
      });
    } else {
      baseColumns = [
        { field: 'phone', label: 'Mobile Number' },
        { field: 'department', label: 'Department' },
        { field: 'shift', label: 'Shift' },
        { field: 'designation', label: 'Designation' }
      ];
    }

    return baseColumns;
  };
  const registrationColumns = getColumns();

  // Dynamically identify the Name header from the registration config
  const nameHeaderObj = registrationColumns.find(c => c.is_name) || 
                        registrationColumns.find(c => ['name', 'student name', 'full name'].includes(c.label?.toLowerCase()));
  const nameHeader = nameHeaderObj?.label || 'Student';

  const tableColumns = useMemo(() => {
    return (registrationColumns || []).filter((col) => {
      // Skip the Name column because it's already rendered in the first 'Student' column
      if (col.is_name) return false;
      if (['name', 'student name', 'full name'].includes(col.label?.toLowerCase())) return false;
      
      return true;
    });
  }, [registrationColumns]);

  const getCellValue = (person, field) => {
    let rawValue = null;
    
    // Normalize field mapping: if the field is a variant of mobile number, use 'phone'
    let effectiveField = field;
    if (['mobile_number', 'mobile number', 'phone_number', 'contact'].includes(String(field).toLowerCase())) {
        effectiveField = 'phone';
    }

    if (person?.custom_data && person.custom_data[effectiveField] !== undefined && person.custom_data[effectiveField] !== null) {
      rawValue = person.custom_data[effectiveField];
    } else if (person && person[effectiveField] !== undefined && person[effectiveField] !== null) {
      rawValue = person[effectiveField];
    }
    
    // Fallback for student ID fields
    if ((rawValue === null || rawValue === '') && ['student_id', 'student id'].includes(String(effectiveField).toLowerCase())) {
      rawValue = person?.custom_data?.student_id || person?.student_id || person?.display_id;
    }
    
    if (rawValue !== null && rawValue !== undefined) {
      const v = rawValue;
      const s = typeof v === 'string' ? v.trim() : v;
      return s === '' ? '-' : s;
    }
    return '-';
  };

  const filteredUsers = useMemo(() => {
    if (!searchTerm) return users;
    const lowerSearch = searchTerm.toLowerCase();
    return users.filter(u => {
      if ((u.name || '').toLowerCase().includes(lowerSearch) || 
          (String(u.id || '')).includes(lowerSearch) ||
          (String(u.display_id || '')).includes(lowerSearch) ||
          (u.phone || '').toLowerCase().includes(lowerSearch) ||
          (u.department || '').toLowerCase().includes(lowerSearch)) {
        return true;
      }
      
      // Expand search across all dynamically registered fields
      for (const col of registrationColumns) {
        if (col.field) {
          let rawValue = null;
          if (u?.custom_data && u.custom_data[col.field] !== undefined && u.custom_data[col.field] !== null) {
            rawValue = u.custom_data[col.field];
          } else if (u[col.field] !== undefined && u[col.field] !== null && typeof u[col.field] !== 'object') {
            rawValue = u[col.field];
          }
          
          if ((rawValue === null || rawValue === '') && ['student_id'].includes(col.field)) {
            rawValue = u?.custom_data?.student_id;
          }
          
          if (rawValue !== null && rawValue !== undefined && String(rawValue).toLowerCase().includes(lowerSearch)) {
            return true;
          }
        }
      }
      return false;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [users, searchTerm]);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">People Management</h1>
          <p className="text-slate-500">Manage {personLabel.toLowerCase()}s and their facial data.</p>
        </div>
        <div className="flex space-x-3">
          {(user?.role === 'super_admin' || user?.features?.includes('bulk_image_attendance') || user?.features?.includes('mobile_app')) && (
            <button
              onClick={openAddModal}
              className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-all text-sm font-medium shadow-sm hover:shadow-md"
            >
              <Plus size={20} />
              <span>Add {personLabel}</span>
            </button>
          )}
            <button
              onClick={() => setIsBulkImportModalOpen(true)}
              className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition-all text-sm font-medium shadow-sm hover:shadow-md"
            >
              <Upload size={20} />
              <span>Bulk Import</span>
            </button>
            {users.length > 0 && (
                <button
                onClick={handleClearAll}
                className="flex items-center space-x-2 px-4 py-2 bg-white border border-red-100 text-red-600 rounded-lg hover:bg-red-50 transition-all text-sm font-medium shadow-sm hover:shadow-md"
              >
                <Trash2 size={20} />
                <span>Clear All People</span>
              </button>
            )}
          </div>
        </div>

      {/* Filters & Search */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col sm:flex-row gap-4 justify-between items-center">
        <div className="relative w-full sm:w-96">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
          <input
            type="text"
            placeholder={`Search ${personLabel.toLowerCase()}s by name or ID...`}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
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
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{nameHeader}</th>
                {tableColumns.map(col => (
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
                  <td colSpan={tableColumns.length + 2} className="px-6 py-8 text-center text-slate-500">Loading {personLabel.toLowerCase()}s...</td>
                </tr>
              ) : filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan={tableColumns.length + 2} className="px-6 py-8 text-center text-slate-500">No {personLabel.toLowerCase()}s found.</td>
                </tr>
              ) : (
                filteredUsers.map((user, idx) => (
                  <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        {user.face_image || user.image_url ? (
                          <img
                            src={
                              user.image_url
                                ? user.image_url
                                : (user.face_image.startsWith('http')
                                  ? user.face_image
                                  : (user.face_image.startsWith('data:')
                                    ? user.face_image
                                    : `data:image/jpeg;base64,${user.face_image}`))
                            }
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
                          <div className="text-xs text-slate-500 font-mono">#{user.display_id || user.id}</div>
                          <div className="text-xs text-slate-500">
                            {user.custom_data?.student_id || ""}
                          </div>
                        </div>
                      </div>
                    </td>

                    {tableColumns.map(col => (
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
                          onClick={() => handleDelete(user.id, user.name)}
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
            Showing <span className="font-medium">1</span> to <span className="font-medium">{filteredUsers.length}</span> of <span className="font-medium">{filteredUsers.length}</span> results
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
              <h2 className="text-xl font-bold text-slate-800">{isEditing ? `Edit ${personLabel}` : `Add New ${personLabel}`}</h2>
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
                <label className="text-sm font-medium text-slate-700">
                  {nameHeader}
                  <span className="text-red-500 ml-1">*</span>
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                  <input
                    type="text"
                    value={formData.name || ''}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="e.g. John Doe"
                    className="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                    required
                  />
                </div>
              </div>

              {/* Phone Field */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">
                  {registrationColumns.find(c => c.is_phone)?.label || 'Phone'}
                  <span className="text-red-500 ml-1">*</span>
                </label>
                <input
                  type="text"
                  value={formData.phone || ''}
                  onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                  placeholder="e.g. +1234567890"
                  className="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  required
                />
              </div>

              {/* Dynamic Fields Rendering */}
              <div className="space-y-4">
                {registrationColumns.map((col, idx) => {
                  const fieldKey = col.key || col.field;
                  const label = col.label || '';
                  
                  // Skip core fields to prevent duplication
                  if (col.is_name || col.is_phone || col.is_id) return null;

                  // Fallback case-insensitive check + Simplification for branch/subject/sections
                  const skipList = [
                    'name', 'phone', 'full_name', 'mobile_number', 'mobile number', 'full name', 
                    'student_id', 'student id', 'branch', 'subject', 'department', 
                    'branch / subject', 'section'
                  ];
                  
                  if (skipList.includes(String(fieldKey).toLowerCase()) || skipList.includes(label.toLowerCase())) {
                    return null;
                  }

                  return (
                    <div key={idx} className="space-y-2">
                      <label className="text-sm font-medium text-slate-700">
                        {col.label}
                        {col.required && <span className="text-red-500 ml-1">*</span>}
                      </label>
                      <input
                        type={col.type || 'text'}
                        value={formData[fieldKey] || ''}
                        onChange={(e) => setFormData({ ...formData, [fieldKey]: e.target.value })}
                        placeholder={`Enter ${col.label}`}
                        className="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                        required={col.required}
                      />
                    </div>
                  );
                })}
                
                {/* Simplified Class Selection */}
                {vendorClasses.length > 0 && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-slate-700">
                      Select Class
                      <span className="text-red-500 ml-1">*</span>
                    </label>
                    <div className="relative">
                      <select
                        value={formData.class_id || ''}
                        onChange={(e) => {
                          const cid = e.target.value;
                          const sel = vendorClasses.find(c => String(c.id) === String(cid));
                          if (sel) {
                            setFormData(prev => ({ 
                              ...prev, 
                              class_id: cid,
                              class_year: sel.class_year,
                              division: sel.division,
                              branch: sel.branch,
                              Section: sel.division, // Compatibility
                              Department: sel.branch // Compatibility
                            }));
                          } else {
                            setFormData(prev => ({ ...prev, class_id: '' }));
                          }
                        }}
                        className="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                        required
                      >
                        <option value="">-- Choose Class --</option>
                        {vendorClasses.map(c => (
                          <option key={c.id} value={c.id}>
                            {c.class_year} - {c.branch} ({c.division})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
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
                  disabled={submitting || !formData.name}
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting ? 'Saving...' : (isEditing ? 'Save Changes' : `Register ${personLabel}`)}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* Bulk Import Modal */}
      {isBulkImportModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="bg-white rounded-2xl w-full max-w-md shadow-2xl overflow-hidden border border-slate-200">
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <h2 className="text-xl font-bold text-slate-800">Bulk Import {personLabel}s</h2>
              <button 
                onClick={() => {
                  setIsBulkImportModalOpen(false);
                  setBulkImportError(null);
                  setBulkImportProgress(null);
                }} 
                className="p-2 hover:bg-slate-200 rounded-lg transition-colors"
              >
                <X size={20} className="text-slate-500" />
              </button>
            </div>
            
            <div className="p-8 text-center">
              {!bulkImportProgress ? (
                <>
                  <div className="w-20 h-20 bg-blue-50 rounded-3xl flex items-center justify-center mx-auto mb-6 text-blue-600 ring-4 ring-blue-50/50">
                    <Upload size={32} />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800 mb-2">Upload Registration File</h3>
                  <p className="text-slate-500 text-sm mb-6 leading-relaxed">
                    Upload a CSV or Excel file containing your {personLabel.toLowerCase()} data. Headers will be used as registration fields.
                  </p>
                  
                  <div className="flex flex-col gap-3">
                    <label className="flex items-center justify-center gap-2 w-full py-3 px-4 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-all cursor-pointer font-medium shadow-lg shadow-blue-500/30">
                      <input 
                        type="file" 
                        className="hidden" 
                        accept=".csv, .xls, .xlsx"
                        onChange={async (e) => {
                          const file = e.target.files[0];
                          if (!file) return;
                          
                          const formData = new FormData();
                          formData.append('file', file);
                          
                          setBulkImportProgress('uploading');
                          setBulkImportError(null);
                          
                          try {
                            const res = await axios.post(`${API_URL}/bulk-registration/upload`, formData, {
                              headers: { 'Content-Type': 'multipart/form-data' }
                            });
                            
                            if (res.data.success) {
                              setBulkImportProgress('success');
                              setTimeout(() => {
                                setIsBulkImportModalOpen(false);
                                setBulkImportProgress(null);
                                fetchUsers();
                                fetchConfig(); // Re-fetch config so new Excel headers become table columns
                              }, 2000);
                            } else {
                              setBulkImportError(res.data.error || "Import failed");
                              setBulkImportProgress(null);
                            }
                          } catch (err) {
                            setBulkImportError(err.response?.data?.error || "Connection error");
                            setBulkImportProgress(null);
                          }
                        }} 
                      />
                      <Upload size={18} />
                      Select File
                    </label>
                  </div>
                </>
              ) : bulkImportProgress === 'uploading' ? (
                <div className="py-12 flex flex-col items-center">
                  <div className="relative w-16 h-16 mb-6">
                    <div className="absolute inset-0 border-4 border-slate-100 rounded-full"></div>
                    <div className="absolute inset-0 border-4 border-blue-600 rounded-full border-t-transparent animate-spin"></div>
                  </div>
                  <p className="text-slate-700 font-medium">Processing File...</p>
                  <p className="text-slate-400 text-sm mt-1">Extracting fields and registering records</p>
                </div>
              ) : (
                <div className="py-12 text-center">
                  <div className="w-20 h-20 bg-green-50 rounded-full flex items-center justify-center mx-auto mb-6 text-green-600 ring-4 ring-green-50/50">
                    <Shield size={32} />
                  </div>
                  <h3 className="text-xl font-bold text-slate-800 mb-2">Import Successful!</h3>
                  <p className="text-slate-500">The {personLabel.toLowerCase()} list is being updated.</p>
                </div>
              )}

              {bulkImportError && (
                <div className="mt-6 p-4 bg-red-50 border border-red-100 rounded-xl flex items-start gap-3 text-left">
                  <div className="text-red-500 mt-0.5">
                    <X size={18} />
                  </div>
                  <div>
                    <p className="text-red-800 text-sm font-semibold mb-0.5">Import Error</p>
                    <p className="text-red-600 text-xs leading-relaxed">{bulkImportError}</p>
                  </div>
                </div>
              )}
            </div>

            <div className="px-6 py-4 bg-slate-50/50 border-t border-slate-100 text-center">
              <p className="text-[10px] text-slate-400 uppercase tracking-widest font-bold">
                Supported: CSV, XLS, XLSX
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default People;
