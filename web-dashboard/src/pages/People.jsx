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
  Camera,
  ChevronLeft,
  BookOpen
} from 'lucide-react';
import { useSocket } from '../context/SocketContext';
import { API_URL, BASE_URL } from '../config';
import { motion, AnimatePresence } from 'framer-motion';

const Toast = ({ message, type, onClose }) => (
  <motion.div
    initial={{ opacity: 0, y: 50, scale: 0.9 }}
    animate={{ opacity: 1, y: 0, scale: 1 }}
    exit={{ opacity: 0, scale: 0.9, transition: { duration: 0.2 } }}
    className={`fixed bottom-6 right-6 z-[9999] flex items-center gap-3 px-5 py-3 rounded-xl shadow-2xl border ${
      type === 'success' 
        ? 'bg-emerald-50 border-emerald-100 text-emerald-800' 
        : 'bg-rose-50 border-rose-100 text-rose-800'
    }`}
  >
    <div className={`w-2 h-2 rounded-full ${type === 'success' ? 'bg-emerald-500' : 'bg-rose-500'} animate-pulse`} />
    <span className="font-medium text-sm">{message}</span>
    <button onClick={onClose} className="ml-2 hover:bg-black/5 p-1 rounded-md transition-colors">
      <X size={14} className="opacity-60" />
    </button>
  </motion.div>
);

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
    class_id: '',
    display_id: ''
  });
  const [submitting, setSubmitting] = useState(false);
  const [vendorConfig, setVendorConfig] = useState([]);
  const [vendorDepartments, setVendorDepartments] = useState([]);
  const [vendorClasses, setVendorClasses] = useState([]);
  const [bulkAttendanceFields, setBulkAttendanceFields] = useState([]);
  const [isBulkImportModalOpen, setIsBulkImportModalOpen] = useState(false);
  const [bulkImportProgress, setBulkImportProgress] = useState(null);
  const [bulkImportError, setBulkImportError] = useState(null);
  const [isFacultyUploadModalOpen, setIsFacultyUploadModalOpen] = useState(false);
  const [facultyUploadProgress, setFacultyUploadProgress] = useState(null);
  const [facultyUploadResult, setFacultyUploadResult] = useState(null);
  const [facultyUploadError, setFacultyUploadError] = useState(null);
  
  const [bulkImportPhase, setBulkImportPhase] = useState('cards'); // 'cards' | 'upload'
  const [selectedBulkClass, setSelectedBulkClass] = useState(null);

  const [activeTab, setActiveTab] = useState('people'); // 'people' | 'faculty'
  const [facultyLogins, setFacultyLogins] = useState([]);
  const [facultyLoading, setFacultyLoading] = useState(false);
  
  // Faculty Edit State
  const [isFacultyEditModalOpen, setIsFacultyEditModalOpen] = useState(false);
  const [selectedFaculty, setSelectedFaculty] = useState(null);
  const [facultyFormData, setFacultyFormData] = useState({
    name: '',
    email: '',
    phone: '',
    designation: '',
    password: ''
  });

  // Add Faculty (single) State
  const [isAddFacultyModalOpen, setIsAddFacultyModalOpen] = useState(false);
  const [addFacultyFormData, setAddFacultyFormData] = useState({
    name: '', email: '', phone: '', designation: '', password: '1234'
  });

  // Toast State
  const [toasts, setToasts] = useState([]);
  const addToast = (message, type = 'success') => {
    const id = Math.random().toString(36).substr(2, 9);
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3000);
  };

  // Class Selection View State
  const [selectedClassForView, setSelectedClassForView] = useState(null);
  const isBulkAttendanceEnabled = user?.features?.includes('bulk_image_attendance');

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
      // Faculty uses /persons which filters to their assigned classes server-side
      const isFaculty = user?.role === 'faculty';
      const response = isFaculty
        ? await axios.get(`${API_URL}/persons`)
        : await axios.get(`${API_URL}/sync/download?limit=200`);
      const faces = isFaculty ? (response.data.persons || []) : (response.data.faces || []);
      setUsers(faces);
      setLoading(false);
      if (!isFaculty) {
        localStorage.setItem(`people_cache_${user?.vendor_id}`, JSON.stringify(faces));
      }
    } catch (error) {
      console.error("Error fetching users:", error);
      setLoading(false);
    }
  };

  const fetchFacultyLogins = async () => {
    setFacultyLoading(true);
    try {
      const res = await axios.get(`${API_URL}/bulk-registration/faculty-logins`);
      setFacultyLogins(res.data.logins || []);
    } catch (e) {
      console.error('Error fetching faculty logins:', e);
    } finally {
      setFacultyLoading(false);
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
      class_id: '',
      display_id: ''
    });
    setIsModalOpen(true);
  };

  const handleEdit = (user) => {
    setIsEditing(true);
    const dynamicFields = user.custom_data || {};

    // Find class_id if missing but class scope exists (Backward compatibility for bulk imports)
    let classId = user.custom_data?.class_id || '';
    if (!classId && user.custom_data?.class_year && (user.custom_data?.division || user.custom_data?.Section)) {
       const year = user.custom_data.class_year;
       const div = user.custom_data.division || user.custom_data.Section;
       const branch = user.custom_data.branch || user.custom_data.Department;

       const matchedClass = vendorClasses.find(c => 
         String(c.class_year) === String(year) && 
         String(c.division) === String(div) &&
         (!branch || String(c.branch) === String(branch))
       );
       if (matchedClass) classId = matchedClass.id;
    }

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
      class_id: classId,
      display_id: user.display_id || '',
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
          fetchUsers(); // Re-fetch to pull newly calculated display_ids
          addToast("Student deleted successfully.", 'success');
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
    const isFacultyTab = activeTab === 'faculty';
    const confirmMsg = isFacultyTab 
      ? "This will delete ALL faculty login accounts. Students and attendance records will NOT be affected. Are you sure?"
      : "CRITICAL: This will delete ALL registered students, their facial data, and reset the registration configuration. This action cannot be undone. Are you sure?";

    if (window.confirm(confirmMsg)) {
      try {
        const url = isFacultyTab ? `${API_URL}/sync/delete-all?target=faculty` : `${API_URL}/sync/delete-all`;
        const resp = await axios.delete(url);
        
        if (resp.data && resp.data.status === 'success') {
          addToast(isFacultyTab ? "All faculty accounts cleared" : "All people data cleared", 'success');
          if (isFacultyTab) {
            setFacultyLogins([]);
          } else {
            setUsers([]);
            setSelectedClassForView(null);
            fetchConfig(); // Refresh registration config (it resets on clear all)
          }
        } else {
          addToast(resp.data?.error || "Failed to clear all", 'error');
        }
      } catch (error) {
        console.error("Error clearing all:", error);
        addToast(error.response?.data?.error || "Failed to clear all data", 'error');
      }
    }
  };

  const handleEditFaculty = (faculty) => {
    setSelectedFaculty(faculty);
    setFacultyFormData({
      name: faculty.name || '',
      email: faculty.email || '',
      phone: faculty.phone || '',
      designation: faculty.designation || '',
      password: '' // Don't show old password
    });
    setIsFacultyEditModalOpen(true);
  };

  const saveFacultyChanges = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const resp = await axios.put(`${API_URL}/bulk-registration/faculty/${selectedFaculty.email}`, facultyFormData);
      if (resp.data && resp.data.success) {
        addToast("Faculty updated successfully", 'success');
        setIsFacultyEditModalOpen(false);
        fetchFacultyLogins();
      } else {
        addToast(resp.data?.error || "Failed to update faculty", 'error');
      }
    } catch (e) {
      console.error("Error updating faculty:", e);
      addToast(e.response?.data?.error || "Update failed", 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const createFacultySingle = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await axios.post(`${API_URL}/bulk-registration/faculty`, addFacultyFormData);
      if (res.data?.success) {
        addToast('Faculty added successfully', 'success');
        setIsAddFacultyModalOpen(false);
        setAddFacultyFormData({ name: '', email: '', phone: '', designation: '', password: '1234' });
        fetchFacultyLogins();
      } else {
        addToast(res.data?.error || 'Failed to add faculty', 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.error || 'Failed to add faculty', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteFaculty = async (email) => {
    if (!window.confirm(`Delete faculty ${email}? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API_URL}/bulk-registration/faculty/${encodeURIComponent(email)}`);
      setFacultyLogins(prev => prev.filter(f => f.email !== email));
      addToast('Faculty deleted successfully', 'success');
    } catch (e) {
      addToast(e.response?.data?.error || 'Delete failed', 'error');
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
        display_id: formData.display_id,
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
    let result = users;
    
    // Filter by selected class if in class view
    if (selectedClassForView) {
      if (selectedClassForView.id === 'unassigned') {
        result = result.filter(u => !u.custom_data?.class_id && !u.custom_data?.class_year && u.role !== 'faculty');
      } else {
        result = result.filter(u => 
          String(u.custom_data?.class_id) === String(selectedClassForView.id) ||
          (
            String(u.custom_data?.class_year) === String(selectedClassForView.class_year) &&
            String(u.custom_data?.division) === String(selectedClassForView.division) &&
            (!u.custom_data?.branch || String(u.custom_data?.branch) === String(selectedClassForView.branch))
          )
        );
      }
    }

    if (!searchTerm) return result;
    const lowerSearch = searchTerm.toLowerCase();
    return result.filter(u => {
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
  }, [users, searchTerm, selectedClassForView]);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{user?.role === 'faculty' ? 'My Students' : 'People Management'}</h1>
          <p className="text-slate-500">{user?.role === 'faculty' ? 'Students enrolled in your assigned classes.' : `Manage ${personLabel.toLowerCase()}s and their facial data.`}</p>
        </div>
        
        {user?.role !== 'faculty' && (
          <div className="flex items-center gap-2">
            {activeTab === 'people' && (
              <>
                <button
                  onClick={openAddModal}
                  className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 font-medium transition-all shadow-lg shadow-blue-500/20"
                >
                  <Plus size={18} /> Add {personLabel}
                </button>
                <button
                  onClick={() => setIsBulkImportModalOpen(true)}
                  className="flex items-center gap-2 bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded-lg hover:bg-slate-50 font-medium transition-all shadow-sm"
                >
                  <Upload size={18} /> Bulk Import
                </button>
              </>
            )}
            {activeTab === 'faculty' && (
              <>
                <button
                  onClick={() => setIsAddFacultyModalOpen(true)}
                  className="flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 font-medium transition-all shadow-lg shadow-indigo-500/20"
                >
                  <Plus size={18} /> Add Faculty
                </button>
                <button
                  onClick={() => setIsFacultyUploadModalOpen(true)}
                  className="flex items-center gap-2 bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded-lg hover:bg-slate-50 font-medium transition-all shadow-sm"
                >
                  <Upload size={18} /> Bulk Upload Faculty
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Tab switcher — only show for non-faculty admins */}
      {user?.role !== 'faculty' && (user?.features?.includes('bulk_image_attendance') || user?.features?.includes('classes')) && (
        <div className="flex gap-1 border-b border-slate-200">
          <button
            onClick={() => setActiveTab('people')}
            className={`px-4 py-2.5 text-sm font-semibold transition-colors rounded-t-lg ${activeTab === 'people' ? 'bg-white border border-b-white border-slate-200 text-blue-600' : 'text-slate-500 hover:text-slate-700'}`}
          >
            {personLabel}s
          </button>
          <button
            onClick={() => { setActiveTab('faculty'); fetchFacultyLogins(); }}
            className={`px-4 py-2.5 text-sm font-semibold transition-colors rounded-t-lg ${activeTab === 'faculty' ? 'bg-white border border-b-white border-slate-200 text-indigo-600' : 'text-slate-500 hover:text-slate-700'}`}
          >
            Faculty Logins
          </button>
        </div>
      )}

      {/* Faculty Logins Tab */}
      {activeTab === 'faculty' && (<div className="bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
            <div>
              <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                <Shield size={20} className="text-indigo-600" />
                Faculty Accounts
              </h3>
              <p className="text-sm text-slate-500 mt-1 italic">Logins created via Excel upload. Default password is <span className="text-amber-600 font-bold">1234</span> until changed.</p>
            </div>
            <div className="flex gap-2">
              <button 
                onClick={handleClearAll}
                className="flex items-center gap-2 px-4 py-2 bg-white border border-rose-200 text-rose-600 font-bold rounded-lg hover:bg-rose-50 transition-all shadow-sm"
              >
                <Trash2 size={16} />
                Clear All Faculty
              </button>
              <button 
                onClick={fetchFacultyLogins}
                disabled={facultyLoading}
                className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 text-slate-600 font-bold rounded-lg hover:bg-slate-50 transition-all shadow-sm disabled:opacity-50"
              >
                <Upload size={16} className={facultyLoading ? 'animate-spin' : ''} />
                Refresh
              </button>
            </div>
          </div>
          {facultyLoading ? (
            <div className="py-12 text-center text-slate-400 text-sm">Loading faculty...</div>
          ) : facultyLogins.length === 0 ? (
            <div className="py-16 text-center text-slate-400">
              <User size={40} className="mx-auto mb-3 opacity-20" />
              <p className="text-sm">No faculty logins yet.</p>
              <p className="text-xs mt-1">Use "Upload Faculty Logins" to create them from an Excel file.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 text-xs uppercase tracking-wider">
                    <th className="px-6 py-3 font-semibold">Email (Username)</th>
                    <th className="px-6 py-3 font-semibold">Current Password</th>
                    <th className="px-6 py-3 font-semibold">Last Login</th>
                    <th className="px-6 py-3 font-semibold">Status</th>
                    <th className="px-6 py-3 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {facultyLogins.map((f, idx) => (
                    <tr key={idx} className="hover:bg-slate-50/60 transition-colors">
                      <td className="px-6 py-3">
                        <span className="font-mono text-indigo-600 font-medium text-xs">{f.email}</span>
                      </td>
                      <td className="px-6 py-3">
                        <code className="bg-amber-50 text-amber-700 px-2 py-0.5 rounded font-mono font-bold text-xs border border-amber-100">
                          {f.password_plain || '••••••••'}
                        </code>
                      </td>
                      <td className="px-6 py-3 text-slate-500 text-xs">{f.last_login || 'Never'}</td>
                      <td className="px-6 py-3">
                        {f.status === 'DEFAULT' ? (
                          <span className="inline-flex items-center gap-1.5 text-amber-600 text-xs font-semibold">
                            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                            Pending First Login
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-green-600 text-xs font-semibold">
                            <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
                            Password Set
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-3 text-right">
                        <div className="flex justify-end space-x-2">
                          <button
                            onClick={() => handleEditFaculty(f)}
                            className="p-1 text-slate-400 hover:text-indigo-600 transition-colors"
                            title="Edit Password"
                          >
                            <Edit2 size={15} />
                          </button>
                          <button
                            onClick={() => handleDeleteFaculty(f.email)}
                            className="p-1 text-slate-400 hover:text-red-500 transition-colors"
                            title="Delete Faculty"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Filters & Search + Table — only shown on people tab */}
      {activeTab === 'people' && (
        <>
          {isBulkAttendanceEnabled && !selectedClassForView ? (
            <div className="mt-4">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-bold text-slate-800">Select Class</h2>
                  <p className="text-sm text-slate-500">View and manage students by their assigned classes.</p>
                </div>
              </div>
              
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {vendorClasses.map((cls) => {
                  const studentsInClass = users.filter(u => 
                    String(u.custom_data?.class_id) === String(cls.id) ||
                    (
                      String(u.custom_data?.class_year) === String(cls.class_year) &&
                      String(u.custom_data?.division) === String(cls.division) &&
                      (!u.custom_data?.branch || String(u.custom_data?.branch) === String(cls.branch))
                    )
                  ).length;

                  return (
                    <button
                      key={cls.id}
                      onClick={() => setSelectedClassForView(cls)}
                      className="flex flex-col p-5 bg-white border border-slate-200 rounded-xl hover:border-blue-500 hover:shadow-md transition-all group text-left relative overflow-hidden"
                    >
                      <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
                        <BookOpen size={64} className="-rotate-12 translate-x-4 translate-y-2" />
                      </div>
                      
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center text-blue-600 group-hover:bg-blue-600 group-hover:text-white transition-all">
                          <BookOpen size={20} />
                        </div>
                        <span className="text-xs font-bold text-blue-600 bg-blue-50 px-2.5 py-1 rounded-full">{cls.division}</span>
                      </div>
                      
                      <div className="relative z-10">
                        <h3 className="font-bold text-slate-800 text-lg leading-tight group-hover:text-blue-700 transition-colors">
                          {cls.class_year}
                        </h3>
                        <p className="text-sm text-slate-500 font-medium mt-1">{cls.branch}</p>
                      </div>
                      
                      <div className="mt-4 pt-4 border-t border-slate-100 flex items-center justify-between text-xs font-bold text-slate-400">
                        <span>{studentsInClass} STUDENTS</span>
                        <span className="text-blue-500 group-hover:translate-x-1 transition-transform">VIEW ALL →</span>
                      </div>
                    </button>
                  );
                })}
                
                {/* Direct Access for unassigned students */}
                <button
                   onClick={() => setSelectedClassForView({ id: 'unassigned', class_year: 'Unassigned', branch: 'No Class' })}
                   className="flex flex-col p-5 bg-slate-50 border border-slate-200 border-dashed rounded-xl hover:bg-slate-100 transition-all text-left"
                >
                   <div className="w-10 h-10 bg-slate-200 rounded-lg flex items-center justify-center text-slate-500 mb-3">
                     <User size={20} />
                   </div>
                   <h3 className="font-bold text-slate-600">Unassigned</h3>
                   <p className="text-sm text-slate-400 mt-1">Students not in any class</p>
                   <div className="mt-auto pt-4 text-[10px] font-bold text-slate-400">VIEW REMAINING</div>
                </button>
              </div>
            </div>
          ) : (
            <>
              {isBulkAttendanceEnabled && selectedClassForView && (
                <div className="flex items-center justify-between mb-8">
                  <div className="flex items-center gap-4">
                    <button
                      onClick={() => setSelectedClassForView(null)}
                      className="p-2 hover:bg-white rounded-xl transition-all border border-transparent hover:border-slate-200 shadow-sm group"
                    >
                      <ChevronLeft size={24} className="text-slate-400 group-hover:text-blue-600" />
                    </button>
                    <div>
                      <h2 className="text-3xl font-black text-slate-800 tracking-tight flex items-center gap-3">
                        {selectedClassForView.class_year} - {selectedClassForView.branch}
                        <span className="text-sm font-bold bg-blue-100 text-blue-700 px-3 py-1 rounded-full uppercase tracking-wider">
                          Division {selectedClassForView.division || selectedClassForView.Section}
                        </span>
                      </h2>
                      <p className="text-slate-500 font-medium mt-1">Manage students and registration records for this class</p>
                    </div>
                  </div>
                  <button 
                    onClick={handleClearAll}
                    className="flex items-center gap-2 px-5 py-2.5 bg-white border border-rose-200 text-rose-600 font-bold rounded-xl hover:bg-rose-50 transition-all shadow-sm group"
                  >
                    <Trash2 size={18} className="group-hover:scale-110 transition-transform" />
                    Clear All Students
                  </button>
                </div>
              )}
              {/* Table */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden text-sm">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 text-xs uppercase tracking-wider">
                        <th className="px-6 py-4 font-bold">{nameHeader}</th>
                        {tableColumns.map(col => (
                          <th key={col.field} className="px-6 py-4 font-bold">
                            {col.label}
                          </th>
                        ))}
                        {user?.role !== 'faculty' && <th className="px-6 py-4 font-bold text-right">Actions</th>}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {loading ? (
                        <tr>
                          <td colSpan={tableColumns.length + 2} className="px-6 py-8 text-center text-slate-400 italic">Loading students...</td>
                        </tr>
                      ) : filteredUsers.length === 0 ? (
                        <tr>
                          <td colSpan={tableColumns.length + 2} className="px-6 py-8 text-center text-slate-400">No records found.</td>
                        </tr>
                      ) : (
                        filteredUsers.map((person, idx) => (
                          <tr key={idx} className="hover:bg-slate-50/60 transition-colors">
                            <td className="px-6 py-4 whitespace-nowrap">
                              <div className="flex items-center">
                                {person.face_image || person.image_url ? (
                                  <img
                                    src={
                                      person.image_url
                                        ? person.image_url
                                        : (person.face_image.startsWith('http')
                                          ? person.face_image
                                          : (person.face_image.startsWith('data:')
                                            ? person.face_image
                                            : `data:image/jpeg;base64,${person.face_image}`))
                                    }
                                    alt={person.name}
                                    className="h-10 w-10 rounded-xl object-cover mr-3 border border-slate-200 shadow-sm"
                                  />
                                ) : (
                                  <div className="h-10 w-10 rounded-xl bg-slate-100 flex items-center justify-center text-slate-400 font-bold text-sm mr-3 border border-slate-200">
                                    {person.name?.charAt(0)}
                                  </div>
                                )}
                                <div>
                                  <div className="text-sm font-bold text-slate-800 tracking-tight">{person.name}</div>
                                  <div className="text-[10px] text-slate-400 font-mono uppercase">#{person.display_id || person.id}</div>
                                </div>
                              </div>
                            </td>

                            {tableColumns.map(col => (
                              <td key={col.field} className="px-6 py-4 whitespace-nowrap text-slate-600 font-medium">
                                {getCellValue(person, col.field)}
                              </td>
                            ))}

                            {user?.role !== 'faculty' && (
                              <td className="px-6 py-4 whitespace-nowrap text-right">
                                <div className="flex justify-end space-x-2">
                                  <button
                                    onClick={() => handleEdit(person)}
                                    className="p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-all"
                                  >
                                    <Edit2 size={16} />
                                  </button>
                                  <button
                                    onClick={() => handleDelete(person.id, person.name)}
                                    className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-all"
                                  >
                                    <Trash2 size={16} />
                                  </button>
                                </div>
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Pagination info */}
              <div className="mt-4 flex items-center justify-between text-xs text-slate-500 font-medium bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
                <div>
                  Showing <span className="font-bold text-slate-800">1</span> to <span className="font-bold text-slate-800">{filteredUsers.length}</span> of <span className="font-bold text-slate-800">{filteredUsers.length}</span> results
                </div>
                <div className="flex gap-2">
                   <button className="px-3 py-1.5 border border-slate-200 rounded-lg opacity-50 cursor-not-allowed">Previous</button>
                   <button className="px-3 py-1.5 border border-slate-200 rounded-lg opacity-50 cursor-not-allowed">Next</button>
                </div>
              </div>
            </>
          )}
        </>
      )}

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

              {/* Student ID / Roll Number */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">
                  Student Roll No / ID
                  <span className="text-xs text-slate-400 ml-2">(Optional - Auto-assigned if empty)</span>
                </label>
                <input
                  type="number"
                  value={formData.display_id || ''}
                  onChange={(e) => setFormData({ ...formData, display_id: e.target.value })}
                  placeholder="e.g. 1"
                  className="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                />
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
                  setBulkImportPhase('cards');
                  setSelectedBulkClass(null);
                }} 
                className="p-2 hover:bg-slate-200 rounded-lg transition-colors"
              >
                <X size={20} className="text-slate-500" />
              </button>
            </div>
            
            <div className={`p-8 text-center ${bulkImportPhase === 'cards' ? 'max-h-[70vh] overflow-y-auto' : ''}`}>
              {bulkImportPhase === 'cards' ? (
                <>
                  <BookOpen size={48} className="mx-auto text-blue-500 mb-4 opacity-80" />
                  <h3 className="text-lg font-bold text-slate-800 mb-2">Select Target Class</h3>
                  <p className="text-sm text-slate-500 mb-6">Which class are these students from? Their records will be auto-assigned to this class.</p>
                  
                  <div className="grid grid-cols-1 gap-3">
                    {vendorClasses.map((cls) => (
                      <button
                        key={cls.id}
                        onClick={() => {
                          setSelectedBulkClass(cls);
                          setBulkImportPhase('upload');
                        }}
                        className="flex flex-col items-start p-4 bg-slate-50 hover:bg-white border border-slate-200 hover:border-blue-400 rounded-xl transition-all group text-left shadow-sm hover:shadow-md"
                      >
                        <div className="flex items-center justify-between w-full mb-1">
                          <span className="font-bold text-slate-800 group-hover:text-blue-600 transition-colors">
                            {cls.class_year} - {cls.branch} ({cls.division})
                          </span>
                          <span className="text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-bold">SELECT</span>
                        </div>
                        <span className="text-xs text-slate-500">{cls.subjects || 'Multiple Subjects'}</span>
                      </button>
                    ))}
                    
                    <button
                      onClick={() => {
                        setSelectedBulkClass(null);
                        setBulkImportPhase('upload');
                      }}
                      className="flex items-center justify-center p-4 border border-dashed border-slate-300 rounded-xl hover:border-slate-400 hover:bg-slate-50 transition-all text-slate-500 text-sm font-medium"
                    >
                      Skip Class Assignment
                    </button>
                  </div>
                </>
              ) : !bulkImportProgress ? (
                <>
                  <button 
                    onClick={() => setBulkImportPhase('cards')}
                    className="flex items-center gap-1.5 text-xs font-bold text-blue-600 hover:text-blue-700 mb-6 transition-colors"
                  >
                    <ChevronLeft size={14} /> Back to Class Selection
                  </button>
                  
                  <div className="w-20 h-20 bg-blue-50 rounded-3xl flex items-center justify-center mx-auto mb-6 text-blue-600 ring-4 ring-blue-50/50">
                    <Upload size={32} />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800 mb-2">Upload {selectedBulkClass ? `${selectedBulkClass.class_year} - ${selectedBulkClass.branch}` : 'Registration'} File</h3>
                  <p className="text-slate-500 text-sm mb-6 leading-relaxed">
                    {selectedBulkClass 
                      ? `Select the Excel/CSV file for students of ${selectedBulkClass.class_year} ${selectedBulkClass.division}.`
                      : `Upload a CSV or Excel file containing your ${personLabel.toLowerCase()} data. Headers will be used as registration fields.`
                    }
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
                          
                          if (selectedBulkClass) {
                            formData.append('class_id', selectedBulkClass.id);
                            formData.append('class_year', selectedBulkClass.class_year);
                            formData.append('division', selectedBulkClass.division);
                            formData.append('branch', selectedBulkClass.branch);
                          }
                          
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
                                setBulkImportPhase('cards');
                                setSelectedBulkClass(null);
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

      {isFacultyUploadModalOpen && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <div>
                <h2 className="text-lg font-bold text-slate-800">Upload Faculty Logins</h2>
                <p className="text-xs text-slate-500 mt-0.5">Extracts emails from any column and creates faculty accounts with password 1234</p>
              </div>
              <button onClick={() => { setIsFacultyUploadModalOpen(false); setFacultyUploadProgress(null); setFacultyUploadResult(null); setFacultyUploadError(null); }} className="p-2 rounded-lg hover:bg-slate-100 transition-colors">
                <X size={20} className="text-slate-500" />
              </button>
            </div>

            <div className="p-6">
              {!facultyUploadProgress && (
                <>
                  <p className="text-slate-500 text-sm mb-6 leading-relaxed">
                    Upload a CSV or Excel file containing teacher data. Any cell with an <strong>@ symbol</strong> will be treated as an email and a faculty login will be created for it.
                    <br /><br />
                    Default password: <code className="bg-amber-50 text-amber-700 px-2 py-0.5 rounded font-mono font-bold">1234</code> — faculty will be forced to change it on first login.
                  </p>
                  <label className="flex items-center justify-center gap-2 w-full py-3 px-4 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-all cursor-pointer font-medium shadow-lg shadow-indigo-500/30">
                    <input
                      type="file"
                      className="hidden"
                      accept=".csv, .xls, .xlsx"
                      onChange={async (e) => {
                        const file = e.target.files[0];
                        if (!file) return;
                        const formData = new FormData();
                        formData.append('file', file);
                        setFacultyUploadProgress('uploading');
                        setFacultyUploadError(null);
                        try {
                          const res = await axios.post(`${API_URL}/bulk-registration/upload-faculty`, formData, {
                            headers: { 'Content-Type': 'multipart/form-data' }
                          });
                          if (res.data.success) {
                            setFacultyUploadResult(res.data);
                            setFacultyUploadProgress('success');
                            fetchFacultyLogins();
                          } else {
                            setFacultyUploadError(res.data.error || 'Upload failed');
                            setFacultyUploadProgress(null);
                          }
                        } catch (err) {
                          setFacultyUploadError(err.response?.data?.error || 'Connection error');
                          setFacultyUploadProgress(null);
                        }
                      }}
                    />
                    <Upload size={18} />
                    Select File
                  </label>
                </>
              )}

              {facultyUploadProgress === 'uploading' && (
                <div className="py-12 flex flex-col items-center">
                  <div className="relative w-16 h-16 mb-6">
                    <div className="absolute inset-0 border-4 border-slate-100 rounded-full"></div>
                    <div className="absolute inset-0 border-4 border-indigo-600 rounded-full border-t-transparent animate-spin"></div>
                  </div>
                  <p className="text-slate-700 font-medium">Extracting emails & creating logins...</p>
                </div>
              )}

              {facultyUploadProgress === 'success' && facultyUploadResult && (
                <div className="py-8 text-center">
                  <div className="w-16 h-16 bg-green-50 rounded-full flex items-center justify-center mx-auto mb-4 text-green-600 ring-4 ring-green-50/50">
                    <Shield size={28} />
                  </div>
                  <h3 className="text-lg font-bold text-slate-800 mb-1">Logins Created!</h3>
                  <p className="text-slate-500 text-sm">{facultyUploadResult.message}</p>
                  <p className="text-xs text-slate-400 mt-2">Faculty can now log in with their email and password <code className="bg-amber-50 text-amber-700 px-1.5 rounded font-mono font-bold">1234</code></p>
                  <button
                    onClick={() => { setIsFacultyUploadModalOpen(false); setFacultyUploadProgress(null); setFacultyUploadResult(null); }}
                    className="mt-6 px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-all font-medium text-sm"
                  >
                    Done
                  </button>
                </div>
              )}

              {facultyUploadError && (
                <div className="mt-4 p-4 bg-red-50 border border-red-100 rounded-xl flex items-start gap-3 text-left">
                  <X size={18} className="text-red-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-red-800 text-sm font-semibold mb-0.5">Upload Error</p>
                    <p className="text-red-600 text-xs leading-relaxed">{facultyUploadError}</p>
                  </div>
                </div>
              )}
            </div>

            <div className="px-6 py-4 bg-slate-50/50 border-t border-slate-100 text-center">
              <p className="text-[10px] text-slate-400 uppercase tracking-widest font-bold">Supported: CSV, XLS, XLSX</p>
            </div>
          </div>
        </div>
      )}
      {/* Add Faculty (Single) Modal */}
      {isAddFacultyModalOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="bg-white rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden border border-slate-200"
          >
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <div>
                <h2 className="text-xl font-bold text-slate-800">Add Faculty</h2>
                <p className="text-xs text-slate-500 mt-0.5 uppercase font-bold tracking-tight">Create a new faculty login account</p>
              </div>
              <button onClick={() => setIsAddFacultyModalOpen(false)} className="p-2 hover:bg-slate-200 rounded-lg transition-colors">
                <X size={20} className="text-slate-500" />
              </button>
            </div>

            <form onSubmit={createFacultySingle} className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-bold text-slate-700">Full Name</label>
                  <input
                    type="text"
                    value={addFacultyFormData.name}
                    onChange={(e) => setAddFacultyFormData({ ...addFacultyFormData, name: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none"
                    placeholder="Enter name"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-bold text-slate-700">Phone Number</label>
                  <input
                    type="text"
                    value={addFacultyFormData.phone}
                    onChange={(e) => setAddFacultyFormData({ ...addFacultyFormData, phone: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none"
                    placeholder="Enter phone"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-slate-700">Email <span className="text-red-500">*</span></label>
                <input
                  type="email"
                  required
                  value={addFacultyFormData.email}
                  onChange={(e) => setAddFacultyFormData({ ...addFacultyFormData, email: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none font-medium"
                  placeholder="faculty@example.com"
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-slate-700">Designation / Role</label>
                <input
                  type="text"
                  value={addFacultyFormData.designation}
                  onChange={(e) => setAddFacultyFormData({ ...addFacultyFormData, designation: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none"
                  placeholder="e.g. Professor, HOD"
                />
              </div>

              <div className="space-y-2 pt-2 border-t border-slate-100">
                <label className="text-sm font-bold text-slate-700">
                  Initial Password
                  <span className="text-[10px] font-bold text-slate-400 font-mono tracking-tight ml-2">(default: 1234)</span>
                </label>
                <input
                  type="text"
                  value={addFacultyFormData.password}
                  onChange={(e) => setAddFacultyFormData({ ...addFacultyFormData, password: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none font-mono"
                  placeholder="1234"
                />
                <p className="text-[10px] text-slate-400 italic">Faculty will be prompted to change this on first login.</p>
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setIsAddFacultyModalOpen(false)}
                  className="flex-1 px-4 py-3 bg-white border border-slate-200 rounded-xl text-slate-600 hover:bg-slate-50 font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || !addFacultyFormData.email}
                  className="flex-1 px-4 py-3 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 font-bold shadow-lg shadow-indigo-500/30 disabled:opacity-50"
                >
                  {submitting ? 'Creating...' : 'Create Faculty'}
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}

      {/* Faculty Edit Modal */}
      {isFacultyEditModalOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <motion.div 
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="bg-white rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden border border-slate-200"
          >
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <div>
                <h2 className="text-xl font-bold text-slate-800">Edit Faculty Profile</h2>
                <p className="text-xs text-slate-500 mt-0.5 tracking-tight uppercase font-bold">Updating {selectedFaculty?.email}</p>
              </div>
              <button onClick={() => setIsFacultyEditModalOpen(false)} className="p-2 hover:bg-slate-200 rounded-lg transition-colors">
                <X size={20} className="text-slate-500" />
              </button>
            </div>
            
            <form onSubmit={saveFacultyChanges} className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-bold text-slate-700">Full Name</label>
                  <input
                    type="text"
                    value={facultyFormData.name}
                    onChange={(e) => setFacultyFormData({ ...facultyFormData, name: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none"
                    placeholder="Enter name"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-bold text-slate-700">Phone Number</label>
                  <input
                    type="text"
                    value={facultyFormData.phone}
                    onChange={(e) => setFacultyFormData({ ...facultyFormData, phone: e.target.value })}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none"
                    placeholder="Enter phone"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-slate-700">Email (Username)</label>
                <input
                  type="email"
                  value={facultyFormData.email}
                  onChange={(e) => setFacultyFormData({ ...facultyFormData, email: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none font-medium"
                  placeholder="faculty@example.com"
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-bold text-slate-700">Designation / Role</label>
                <input
                  type="text"
                  value={facultyFormData.designation}
                  onChange={(e) => setFacultyFormData({ ...facultyFormData, designation: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:outline-none font-medium"
                  placeholder="e.g. Professor, HOD"
                />
              </div>

              <div className="space-y-2 pt-2 border-t border-slate-100">
                <label className="text-sm font-bold text-slate-700 flex items-center gap-2">
                  Reset Password
                  <span className="text-[10px] font-bold text-slate-400 font-mono tracking-tight">(OPTIONAL)</span>
                </label>
                <input
                  type="text"
                  value={facultyFormData.password}
                  onChange={(e) => setFacultyFormData({ ...facultyFormData, password: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none font-mono"
                  placeholder="New password"
                />
                <p className="text-[10px] text-slate-400 italic">Leave empty to keep current password. Faculty will be notified of change.</p>
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setIsFacultyEditModalOpen(false)}
                  className="flex-1 px-4 py-3 bg-white border border-slate-200 rounded-xl text-slate-600 hover:bg-slate-50 font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="flex-1 px-4 py-3 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 font-bold shadow-lg shadow-indigo-500/30 group"
                >
                  {submitting ? 'Updating...' : 'Save Profile'}
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}

      {/* Toast Notifications */}
      <AnimatePresence>
        {toasts.map(toast => (
          <Toast 
            key={toast.id} 
            message={toast.message} 
            type={toast.type} 
            onClose={() => setToasts(prev => prev.filter(t => t.id !== toast.id))} 
          />
        ))}
      </AnimatePresence>
    </div>
  );
};

export default People;
