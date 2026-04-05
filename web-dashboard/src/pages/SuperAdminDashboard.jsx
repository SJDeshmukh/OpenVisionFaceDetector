import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Plus, Check, X, Shield, User, Users, Lock, DollarSign, Calendar, Pencil, ToggleLeft, ToggleRight, Search, Filter, ArrowLeft, ArrowRight, Eye, Settings, Trash2, Database, Download, RefreshCw, Layers, Upload, Activity, Battery, WifiOff, UploadCloud, Box } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { API_URL, FRONTEND_BUNDLES, BASE_URL } from '../config';
import { useSocket } from '../context/SocketContext';
import RegistrationConfigEditor from '../components/RegistrationConfigEditor';

const SuperAdminDashboard = () => {
  const { user } = useAuth();
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [passwordModal, setPasswordModal] = useState({ show: false, username: '' });
  const [invoiceModal, setInvoiceModal] = useState({ show: false, vendor: null, invoices: [] });
  const [newPassword, setNewPassword] = useState('');
  const [newVendor, setNewVendor] = useState({
    company_name: '', contact_person: '', phone: '', email: '',
    start_date: '', end_date: '',
    cost_per_user: '', cost_per_employee: '', // Explicit costs
    max_users: '', max_employees: '',
    max_web_sessions: '',
    registration_template: '',
    admin_username: '', admin_password: '',
    user_username: '', user_password: '',
    frontend_bundle_id: 'default_attendance',
    backend_service_id: 'default_api',
    features: [],
    vertical: '',
    attendance_type: 'total_time',
    retention_days: '90' // Default to 90 days
  });
  const [businessTypes, setBusinessTypes] = useState([
    {
      value: 'school', label: 'School / College / Tuitions', default_frontend_bundle_id: 'attendance_ui', default_registration_config: [
        { field: 'student_id', label: 'Student ID', type: 'text', required: true, options: [] },
        { field: 'student_phone', label: 'Phone Number of Student', type: 'text', required: true, options: [] }
      ]
    },
    {
      value: 'hostel', label: 'Hostel / Accommodation', default_frontend_bundle_id: 'attendance_ui', default_registration_config: [
        { field: 'student_id', label: 'Student ID', type: 'text', required: true, options: [] },
        { field: 'student_phone', label: 'Phone Number of Student', type: 'text', required: true, options: [] }
      ]
    },
    {
      value: 'class_attendance', label: 'Class Attendance', default_frontend_bundle_id: 'class_attendance_ui', default_registration_config: [
        { field: 'student_number', label: 'Student Number', type: 'text', required: true, options: [] },
        { field: 'class_section', label: 'Class/Section', type: 'text', required: true, options: [] }
      ]
    },
    {
      value: 'wages', label: 'Daily Wages / Workforce', default_frontend_bundle_id: 'attendance_payroll_ui', default_registration_config: [
        { field: 'daily_wage', label: 'Daily Wage', type: 'text', required: false, options: [] },
        { field: 'department', label: 'Department', type: 'text', required: false, options: [] }
      ]
    },
    {
      value: 'factory', label: 'Industrial / Manufacturing', default_frontend_bundle_id: 'attendance_payroll_ui', default_registration_config: [
        { field: 'employee_id', label: 'Employee ID', type: 'text', required: false, options: [] },
        { field: 'department', label: 'Department', type: 'text', required: false, options: [] },
        { field: 'shift', label: 'Shift', type: 'text', required: false, options: [] }
      ]
    },
    { value: 'enterprise', label: 'Enterprise (Custom)', default_frontend_bundle_id: 'default_attendance', default_registration_config: [] }
  ]);
  const [registrationConfig, setRegistrationConfig] = useState([]);
  const [editingVendor, setEditingVendor] = useState(null);

  // Features Config
  const [availableFeatures, setAvailableFeatures] = useState([
    'reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 
    'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 
    'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling', 
    'late_mark', 'bulk_image_attendance', 'classes', 'leave_management'
  ]);
  const [bundleConfig, setBundleConfig] = useState({
    'attendance_ui': ['reports', 'report_detailed', 'mobile_app', 'live_attendance', 'cameras', 'enable_attendance', 'geofencing'],
    'attendance_payroll_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts'],
    'enterprise_custom_ui': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing', 'whatsapp_alerts', 'api_access', 'white_labeling'],
    'default_attendance': ['reports', 'report_detailed', 'report_payroll', 'mobile_app', 'payroll', 'shifts', 'live_attendance', 'cameras', 'add_shift', 'payable_hours', 'enable_attendance', 'night_shift_logic', 'geofencing'],
    'class_attendance_ui': ['reports', 'report_detailed', 'bulk_image_attendance', 'live_attendance', 'cameras', 'enable_attendance', 'classes']
  });
  const [registrationTemplates, setRegistrationTemplates] = useState({
     "school": [
         {"field": "student_id", "label": "Student ID", "enabled": true},
         {"field": "student_phone", "label": "Phone Number of Student", "enabled": true}
     ],
     "hostel": [
         {"field": "student_id", "label": "Student ID", "enabled": true},
         {"field": "student_phone", "label": "Phone Number of Student", "enabled": true}
     ],
     "class_attendance": [
         {"field": "student_number", "label": "Student Number", "enabled": true},
         {"field": "class_section", "label": "Class/Section", "enabled": true},
         {"field": "phone", "label": "Parent Mobile Number", "enabled": false}
     ],
     "factory": [
         {"field": "employee_id", "label": "Employee ID", "enabled": true},
         {"field": "department", "label": "Department", "enabled": true}
     ]
   });
   const [vendorEmployees, setVendorEmployees] = useState([]);
   const [vendorStudentLogins, setVendorStudentLogins] = useState([]);
   const [vendorParents, setVendorParents] = useState([]);
   const [vendorDevices, setVendorDevices] = useState([]);
   const [deviceEdits, setDeviceEdits] = useState({});
   const [deviceSlots, setDeviceSlots] = useState([]);
   const [newSlotName, setNewSlotName] = useState('');

   // --- Leave Management Configuration State ---
   const [showLeaveConfigModal, setShowLeaveConfigModal] = useState(false);
   const [leaveDepts, setLeaveDepts] = useState([]);
   const [leaveStaff, setLeaveStaff] = useState([]);
   const [leaveStudents, setLeaveStudents] = useState([]);
   const [loadingLeaveData, setLoadingLeaveData] = useState(false);
   const [newDept, setNewDept] = useState('');
   const [newStaff, setNewStaff] = useState({ name: '', role: 'rector', pin: '', department: '' });
   const [configLoading, setConfigLoading] = useState(false);

   // Stats State
   const [stats, setStats] = useState({
     total_vendors: 0,
     active_vendors: 0,
     total_employees: 0,
     total_devices: 0,
     active_streaming_devices: 0,
     monthly_recurring_revenue: 0
   });

   // Filter States
   const [searchTerm, setSearchTerm] = useState('');
   const [statusFilter, setStatusFilter] = useState('all');
   const [subscriptionFilter, setSubscriptionFilter] = useState('all');
   const [selectedVendorIds, setSelectedVendorIds] = useState([]);
  const normalizePositiveInt = (value, fallback) => {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 1) return fallback;
    return Math.floor(n);
  };

  // --- New Tab & Details State ---
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'vendor_details'
  const [detailViewMode, setDetailViewMode] = useState('list'); // 'list' | 'vendor' | 'employee'
  const [selectedVendorForDetail, setSelectedVendorForDetail] = useState(null);
  const [selectedEmployeeForDetail, setSelectedEmployeeForDetail] = useState(null);
  const [employeeReport, setEmployeeReport] = useState(null);
  const [reportDateRange, setReportDateRange] = useState({
    start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
    end: new Date().toISOString().split('T')[0]
  });
  const [serverSubEcho, setServerSubEcho] = useState(null);

  const fetchBusinessTypes = async () => {
    try {
      const res = await axios.get(`${API_URL}/public/business-types`);
      const raw = res?.data?.business_types || [];
      const normalized = (Array.isArray(raw) ? raw : [])
        .filter(x => x && typeof x.value === 'string')
        .map(x => ({
          value: x.value,
          label: x.label || x.value,
          default_frontend_bundle_id: x.default_frontend_bundle_id,
          default_registration_config: Array.isArray(x.default_registration_config) ? x.default_registration_config : []
        }));
      if (normalized.length) setBusinessTypes(normalized);
    } catch (e) { }
  };

  const { socket, joinSuperAdmin } = useSocket();
  const maxUsersRef = useRef(null);
  const maxEmployeesRef = useRef(null);
  const maxWebSessionsRef = useRef(null);
  useEffect(() => {
    if (!user || user.role !== 'super_admin') return;

    fetchVendors();
    fetchFeatures();
    fetchStats();
    fetchTemplates();
    fetchBusinessTypes();

    if (!socket) return;
    const doJoin = () => joinSuperAdmin();
    if (socket.connected) {
      doJoin();
    }
    socket.on('connect', doJoin);

    socket.on('vendor_updated', (data) => {
      console.log("Vendor Updated:", data);
      fetchVendors();
      fetchStats();
      if (selectedVendorForDetail?.id) {
        fetchVendorEmployees(selectedVendorForDetail.id);
        fetchVendorStudentLogins(selectedVendorForDetail.id);
        fetchVendorParents(selectedVendorForDetail.id);
        if (detailViewMode === 'employee' && selectedEmployeeForDetail) {
          fetchEmployeeReport(selectedVendorForDetail.id, selectedEmployeeForDetail);
        }
      }
      try {
        const vid = data && data.vendor_id;
        if (editingVendor?.id && vid === editingVendor.id) {
          axios.get(`${API_URL}/admin/vendors/${editingVendor.id}/subscription`, {
            headers: { Authorization: `Bearer ${user?.token}` }
          }).then(resp => setServerSubEcho(resp.data || null)).catch(() => { });
        }
      } catch (_) { }
    });

    socket.on('device_health_update', (data) => {
      console.log("Device Health Update:", data);
      if (selectedVendorForDetail?.id === data.vendor_id) {
        setVendorDevices(prev => prev.map(d =>
          d.device_id === data.device_id
            ? { ...d, last_active_at: data.last_active_at, battery_level: data.battery_level }
            : d
        ));
      }
    });

    socket.on('active_devices_update', (data) => {
      console.log("Active Devices Update:", data);
      setStats(prev => ({
        ...prev,
        active_streaming_devices: data.count
      }));
    });

    return () => {
      socket.off('connect', doJoin);
      socket.off('vendor_updated');
      socket.off('device_health_update');
      socket.off('active_devices_update');
    };
  }, [socket, user, selectedVendorForDetail?.id, detailViewMode, selectedEmployeeForDetail, reportDateRange, editingVendor?.id]);

  const isOnline = (lastActiveAt) => {
    if (!lastActiveAt) return false;
    const last = new Date(lastActiveAt);
    const now = new Date();
    return (now - last) < 5 * 60 * 1000; // 5 minutes threshold
  };

  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_URL}/admin/stats`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setStats(response.data);
    } catch (error) {
      console.error("Error fetching stats:", error);
    }
  };

  const fetchTemplates = async () => {
    try {
      const res = await axios.get(`${API_URL}/admin/registration/templates`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const templates = res.data.templates || {};
      setRegistrationTemplates(templates);
      
      if (Object.keys(templates).length > 0) {
        localStorage.setItem('admin_registration_templates', JSON.stringify(templates));
      }
    } catch (e) {
      console.error("Error fetching templates:", e);
      const cachedTemplates = localStorage.getItem('admin_registration_templates');
      if (cachedTemplates) setRegistrationTemplates(JSON.parse(cachedTemplates));
    }
  };

  const fetchVendorStudentLogins = async (vendorId) => {
    try {
      const resp = await axios.get(`${API_URL}/leave/admin/vendors/${vendorId}/student-logins`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setVendorStudentLogins(resp.data.logins || []);
    } catch (e) { console.error(e); }
  };

  const fetchVendorParents = async (vendorId) => {
    try {
      const resp = await axios.get(`${API_URL}/leave/admin/vendors/${vendorId}/parents`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setVendorParents(resp.data.parents || []);
    } catch (e) { console.error(e); }
  };

  const handleAddDept = async (vendorId) => {
    if (!newDept.trim()) return;
    try {
      await axios.post(`${API_URL}/leave/admin/departments?vendor_id=${vendorId}`, {
        name: newDept.trim()
      }, { 
        headers: { Authorization: `Bearer ${user?.token}` } 
      });
      setNewDept('');
      fetchVendorDepts(vendorId);
    } catch (e) { alert(e.response?.data?.error || e.message); }
  };

  const handleDeleteDept = async (vendorId, dept) => {
    if (!window.confirm(`Delete department "${dept}"?`)) return;
    try {
      await axios.delete(`${API_URL}/leave/admin/departments`, {
        params: { vendor_id: vendorId, name: dept },
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchVendorDepts(vendorId);
    } catch (e) { alert(e.response?.data?.error || e.message); }
  };

  const handleDeleteStaff = async (vendorId, staffId) => {
    if (!window.confirm("Delete this staff member?")) return;
    try {
      await axios.delete(`${API_URL}/leave/admin/staff`, {
        params: { vendor_id: vendorId, id: staffId },
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchLeaveStaff(vendorId);
    } catch (e) { alert(e.response?.data?.error || e.message); }
  };

  const fetchVendorDevices = async (vendorId) => {
    try {
      const res = await axios.get(`${API_URL}/admin/vendors/${vendorId}/devices`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const list = res?.data?.devices || [];
      setVendorDevices(list);
      const edits = {};
      list.forEach(d => { edits[d.device_id] = d.device_name || ''; });
      setDeviceEdits(edits);
    } catch (e) {
      console.error("Error fetching devices:", e?.response?.data || e);
      setVendorDevices([]);
    }
  };

  const fetchVendorDeviceSlots = async (vendorId) => {
    try {
      const res = await axios.get(`${API_URL}/admin/vendors/${vendorId}/device-slots`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setDeviceSlots(res?.data?.slots || []);
    } catch (e) {
      setDeviceSlots([]);
    }
  };

  const saveDeviceSlots = async (vendorId, slots) => {
    try {
      await axios.put(`${API_URL}/admin/vendors/${vendorId}/device-slots`,
        { slots },
        { headers: { Authorization: `Bearer ${user?.token}` } }
      );
      fetchVendorDeviceSlots(vendorId);
    } catch (e) {
      alert("Failed to save device slots");
    }
  };

  const saveDeviceName = async (vendorId, deviceId, labelOverride) => {
    const newName = (labelOverride != null ? String(labelOverride) : (deviceEdits?.[deviceId] ?? '')).trim();
    try {
      await axios.put(`${API_URL}/admin/vendors/${vendorId}/devices/${encodeURIComponent(deviceId)}`,
        { device_name: newName },
        { headers: { Authorization: `Bearer ${user?.token}` } }
      );
      // Reflect change locally
      setVendorDevices(prev => prev.map(d => d.device_id === deviceId ? { ...d, device_name: newName } : d));
      try {
        if (selectedVendorForDetail?.id === vendorId) {
          fetchVendorDeviceSlots(vendorId);
        }
      } catch (_) { }
    } catch (e) {
      const msg = e?.response?.data?.error || e.message || "Failed to update device name";
      alert(msg);
    }
  };

  const logoutVendorDevice = async (vendorId, deviceId) => {
    if (!window.confirm(`Logout device ${deviceId}? This will invalidate its mobile session.`)) return;
    try {
      await axios.post(`${API_URL}/admin/vendors/${vendorId}/devices/${encodeURIComponent(deviceId)}/logout`, {}, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      alert("Device logged out");
    } catch (e) {
      const msg = e?.response?.data?.error || e.message || "Failed to logout device";
      alert(msg);
    }
  };

  const deleteVendorDevice = async (vendorId, deviceId) => {
    if (!window.confirm(`Delete device ${deviceId}? This removes it from records and frees its place.`)) return;
    try {
      await axios.delete(`${API_URL}/admin/vendors/${vendorId}/devices/${encodeURIComponent(deviceId)}`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      alert("Device deleted successfully");
      // Refresh local state
      await fetchVendorDevices(vendorId);
      await fetchVendorDeviceSlots(vendorId);
    } catch (e) {
      const msg = e?.response?.data?.error || e.message || "Failed to delete device";
      alert(msg);
    }
  };

  const adminAssignDeviceSlot = async (vendorId, deviceId, slotName) => {
    try {
      await axios.post(`${API_URL}/admin/vendors/${vendorId}/devices/${encodeURIComponent(deviceId)}/assign-slot`,
        { slot_name: slotName },
        { headers: { Authorization: `Bearer ${user?.token}` } }
      );
      await fetchVendorDevices(vendorId);
      await fetchVendorDeviceSlots(vendorId);
    } catch (e) {
      const msg = e?.response?.data?.error || e.message || "Failed to assign place";
      alert(msg);
    }
  };

  const fetchLeaveStaff = async (vendorId) => {
    try {
      const res = await axios.get(`${API_URL}/leave/admin/staff`, {
        params: { vendor_id: vendorId },
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setLeaveStaff(res.data.staff || []);
    } catch (e) {
      console.error("Error fetching staff:", e);
    }
  };

  const fetchVendorDepts = async (vendorId) => {
    try {
      const res = await axios.get(`${API_URL}/leave/admin/departments`, {
        params: { vendor_id: vendorId },
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setLeaveDepts(res.data.departments || []);
    } catch (e) {
      console.error("Error fetching depts:", e);
    }
  };
  const fetchLeaveStudents = async (vendorId) => {
    try {
      const res = await axios.get(`${API_URL}/admin/vendors/${vendorId}/leave/students`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setLeaveStudents(res.data.students || []);
    } catch (e) {
      console.error("Error fetching leave students:", e);
    }
  };

  const handleOpenLeaveConfig = async (vendor) => {
    setEditingVendor(vendor);
    setShowLeaveConfigModal(true);
    setLoadingLeaveData(true);
    setNewStaff({ name: '', role: 'rector', pin: '', department: '' });
    setNewDept('');
    try {
      await Promise.all([
        fetchVendorDepts(vendor.id),
        fetchLeaveStaff(vendor.id),
        fetchLeaveStudents(vendor.id)
      ]);
    } finally {
      setLoadingLeaveData(false);
    }
  };

  const handleCreateStaff = async (vendorId) => {
    try {
      await axios.post(`${API_URL}/leave/admin/staff?vendor_id=${vendorId}`, 
        { ...newStaff },
        { headers: { Authorization: `Bearer ${user?.token}` } }
      );
      fetchLeaveStaff(vendorId);
      setNewStaff({ name: '', role: 'rector', pin: '', department: '' });
    } catch (e) {
      alert(e.response?.data?.error || "Failed to create staff");
    }
  };


  const deletePlaceSlot = async (vendorId, slotName) => {
    if (!slotName) return;
    if (!window.confirm(`Delete place "${slotName}"? This will unassign any devices using it.`)) return;
    try {
      const impacted = (vendorDevices || []).filter(d => (d.device_name || '').trim() === slotName);
      // 1) Unassign all impacted devices first (backend won't delete assigned slots)
      await Promise.all(
        impacted.map(d => {
          setDeviceEdits(prev => ({ ...prev, [d.device_id]: '' }));
          return saveDeviceName(vendorId, d.device_id, '');
        })
      );
      // 2) Now remove the slot
      const remaining = (deviceSlots || [])
        .filter(x => x.slot_name !== slotName)
        .map(x => x.slot_name);
      await saveDeviceSlots(vendorId, remaining);
    } catch (e) {
      alert("Failed to delete place");
    }
  };

  const toggleSelected = (id, checked) => {
    setSelectedVendorIds(prev => {
      const set = new Set(prev);
      if (checked) set.add(id); else set.delete(id);
      return Array.from(set);
    });
  };

  const runBulkAction = async (payload) => {
    try {
      await axios.post(`${API_URL}/admin/vendors/bulk_action`, payload, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchVendors();
      setSelectedVendorIds([]);
    } catch (e) {
      alert("Bulk action failed");
    }
  };

  const handleBulkSuspend = () => runBulkAction({ vendor_ids: selectedVendorIds, action: 'suspend' });
  const handleBulkActivate = () => runBulkAction({ vendor_ids: selectedVendorIds, action: 'activate' });
  const handleBulkToggleFeature = (feature, enabled) => runBulkAction({ vendor_ids: selectedVendorIds, action: 'toggle_feature', feature, enabled });
  const handleBulkUpdateWebSessions = (n) => runBulkAction({ vendor_ids: selectedVendorIds, action: 'update_web_sessions', max_web_sessions: n });

  const fetchFeatures = async () => {
    try {
      const response = await axios.get(`${API_URL}/admin/features`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const features = response.data.features || [];
      const bundles = response.data.bundles || {};
      setAvailableFeatures(features);
      setBundleConfig(bundles);
      
      // Persist to local storage as fallback
      if (features.length > 0) {
        localStorage.setItem('admin_available_features', JSON.stringify(features));
      }
      if (Object.keys(bundles).length > 0) {
        localStorage.setItem('admin_bundle_config', JSON.stringify(bundles));
      }
    } catch (error) {
      console.error("Error fetching features:", error);
      // Try to load from local storage fallback
      const cachedFeatures = localStorage.getItem('admin_available_features');
      const cachedBundles = localStorage.getItem('admin_bundle_config');
      if (cachedFeatures) setAvailableFeatures(JSON.parse(cachedFeatures));
      if (cachedBundles) setBundleConfig(JSON.parse(cachedBundles));
    }
  };

  const filteredVendors = vendors.filter(vendor => {
    const matchesSearch =
      (vendor.company_name?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (vendor.contact_person?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (vendor.email?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (vendor.phone?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (vendor.admin_username?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
      (vendor.user_username?.toLowerCase() || '').includes(searchTerm.toLowerCase());

    const matchesStatus = statusFilter === 'all' || vendor.status === statusFilter;

    const matchesSubscription = subscriptionFilter === 'all' ||
      (subscriptionFilter === 'Active' && vendor.subscription_status === 'Active') ||
      (subscriptionFilter === 'Expired' && vendor.subscription_status === 'Expired');

    return matchesSearch && matchesStatus && matchesSubscription;
  });

  const fetchVendors = async () => {
    try {
      const response = await axios.get(`${API_URL}/admin/vendors`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setVendors(response.data.vendors);
    } catch (error) {
      console.error('Error fetching vendors:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateVendor = async (e) => {
    e.preventDefault();

    // Validation
    if (newVendor.start_date && newVendor.end_date) {
      if (new Date(newVendor.end_date) < new Date(newVendor.start_date)) {
        alert("End Date cannot be before Start Date");
        return;
      }
    }

    try {
      // Offer restore path if archive has a match
      if (!editingVendor) {
        const check = await axios.get(`${API_URL}/admin/archive/vendors`, {
          params: { company_name: newVendor.company_name, email: newVendor.email },
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        if ((check.data.archived_vendors || []).length > 0) {
          if (window.confirm("Archived data found for this vendor. Do you want to restore instead of creating fresh?")) {
            const restore = await axios.post(`${API_URL}/admin/vendors/restore`, {
              company_name: newVendor.company_name,
              email: newVendor.email
            }, { headers: { Authorization: `Bearer ${user?.token}` } });
            alert(`Vendor Restored. New Vendor ID: ${restore.data.new_vendor_id}`);
            fetchVendors();
            setShowModal(false);
            return;
          }
        }
      }
      if (editingVendor) {
        const liveMaxUsers = maxUsersRef.current ? maxUsersRef.current.value : newVendor.max_users;
        const liveMaxEmployees = maxEmployeesRef.current ? maxEmployeesRef.current.value : newVendor.max_employees;
        const liveMaxWeb = maxWebSessionsRef.current ? maxWebSessionsRef.current.value : newVendor.max_web_sessions;
        // Update Mode
        await axios.put(`${API_URL}/admin/vendors/${editingVendor.id}`, {
          company_name: newVendor.company_name,
          contact_person: newVendor.contact_person,
          phone: newVendor.phone,
          email: newVendor.email,
          admin_username: newVendor.admin_username,
          admin_password: newVendor.admin_password,
          user_username: newVendor.user_username,
          user_password: newVendor.user_password,
          frontend_bundle_id: newVendor.frontend_bundle_id,
          backend_service_id: newVendor.backend_service_id,
          vertical: newVendor.vertical,
          attendance_type: newVendor.attendance_type,
          retention_days: normalizePositiveInt(newVendor.retention_days, 90)
        }, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });

        await axios.put(`${API_URL}/admin/vendors/${editingVendor.id}/subscription`, {
          start_date: newVendor.start_date,
          end_date: newVendor.end_date,
          cost_per_user: newVendor.cost_per_user,
          cost_per_employee: newVendor.cost_per_employee,
          max_users: normalizePositiveInt(liveMaxUsers, 1),
          max_mobile_devices: normalizePositiveInt(liveMaxUsers, 1),
          max_employees: normalizePositiveInt(liveMaxEmployees, 1),
          max_web_sessions: normalizePositiveInt(liveMaxWeb, 1),
          plan_type: 'custom',
          features: newVendor.features
        }, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        try {
          const subResp = await axios.get(`${API_URL}/admin/vendors/${editingVendor.id}/subscription`, {
            headers: { Authorization: `Bearer ${user?.token}` }
          });
          const sub = subResp.data || {};
          setNewVendor(prev => ({
            ...prev,
            max_users: sub.max_users != null ? String(sub.max_users) : prev.max_users,
            max_employees: sub.max_employees != null ? String(sub.max_employees) : prev.max_employees,
            max_web_sessions: sub.max_web_sessions != null ? String(sub.max_web_sessions) : prev.max_web_sessions,
            cost_per_user: sub.cost_per_user != null ? sub.cost_per_user : prev.cost_per_user,
            cost_per_employee: sub.cost_per_employee != null ? sub.cost_per_employee : prev.cost_per_employee
          }));
          setVendors(prev => prev.map(v => v.id === editingVendor.id ? {
            ...v,
            max_users: sub.max_users ?? v.max_users,
            max_employees: sub.max_employees ?? v.max_employees,
            max_web_sessions: sub.max_web_sessions ?? v.max_web_sessions,
            cost_per_user: sub.cost_per_user ?? v.cost_per_user,
            cost_per_employee: sub.cost_per_employee ?? v.cost_per_employee,
            max_mobile_devices: sub.max_mobile_devices ?? v.max_mobile_devices
          } : v));
          fetchVendors();
        } catch (_) { }

        // Save Registration Config
        await axios.put(`${API_URL}/admin/vendors/${editingVendor.id}/registration-config`, {
          config: registrationConfig
        }, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });

        alert("Vendor Updated Successfully!");
      } else {
        const liveMaxUsers = maxUsersRef.current ? maxUsersRef.current.value : newVendor.max_users;
        const liveMaxEmployees = maxEmployeesRef.current ? maxEmployeesRef.current.value : newVendor.max_employees;
        const liveMaxWeb = maxWebSessionsRef.current ? maxWebSessionsRef.current.value : newVendor.max_web_sessions;
        // Create Mode
        const response = await axios.post(`${API_URL}/admin/vendors`, {
          ...newVendor,
          max_users: normalizePositiveInt(liveMaxUsers, 5),
          max_mobile_devices: normalizePositiveInt(liveMaxUsers, 5),
          max_employees: normalizePositiveInt(liveMaxEmployees, 50),
          max_web_sessions: normalizePositiveInt(liveMaxWeb, 1),
          retention_days: normalizePositiveInt(newVendor.retention_days, 90)
        }, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });

        const newVendorId = response.data.vendor_id;
        try {
          const subResp = await axios.get(`${API_URL}/admin/vendors/${newVendorId}/subscription`, {
            headers: { Authorization: `Bearer ${user?.token}` }
          });
          const sub = subResp.data || {};
          setVendors(prev => prev.map(v => v.id === newVendorId ? {
            ...v,
            max_users: sub.max_users ?? v.max_users,
            max_employees: sub.max_employees ?? v.max_employees,
            max_web_sessions: sub.max_web_sessions ?? v.max_web_sessions,
            cost_per_user: sub.cost_per_user ?? v.cost_per_user,
            cost_per_employee: sub.cost_per_employee ?? v.cost_per_employee,
            max_mobile_devices: sub.max_mobile_devices ?? v.max_mobile_devices
          } : v));
          fetchVendors();
        } catch (_) { }

        // Save Registration Config for new vendor
        if (registrationConfig.length > 0) {
          await axios.put(`${API_URL}/admin/vendors/${newVendorId}/registration-config`, {
            config: registrationConfig
          }, {
            headers: { Authorization: `Bearer ${user?.token}` }
          });
        }

        alert(`Vendor Created!\nAdmin: ${response.data.admin_credentials.username}\nUser: ${response.data.user_credentials.username}`);
      }

      setShowModal(false);
      setEditingVendor(null);
      setNewVendor({
        company_name: '', contact_person: '', phone: '', email: '',
        start_date: '', end_date: '',
        cost_per_user: '', cost_per_employee: '',
        max_users: '', max_employees: '',
        max_web_sessions: '',
        registration_template: '',
        admin_username: '', admin_password: '',
        user_username: '', user_password: '',
        features: [],
        vertical: '',
        frontend_bundle_id: 'default_attendance',
        backend_service_id: 'default_api',
        attendance_type: 'total_time',
        retention_days: '90'
      });
      setRegistrationConfig([]);
      fetchVendors();
    } catch (error) {
      alert("Error: " + (error.response?.data?.error || error.message));
    }
  };

  const handleEditClick = async (vendor) => {
    setEditingVendor(vendor);
    try {
      let sub = null;
      try {
        const resp = await axios.get(`${API_URL}/admin/vendors/${vendor.id}/subscription`, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        sub = resp.data || null;
      } catch (e) {
        sub = null;
      }
      setNewVendor({
        company_name: vendor.company_name || '',
        contact_person: vendor.contact_person || '',
        phone: vendor.phone || '',
        email: vendor.email || '',
        start_date: (sub && sub.start_date) ? new Date(sub.start_date).toISOString().split('T')[0] : (vendor.start_date ? new Date(vendor.start_date).toISOString().split('T')[0] : ''),
        end_date: (sub && sub.end_date) ? new Date(sub.end_date).toISOString().split('T')[0] : (vendor.end_date ? new Date(vendor.end_date).toISOString().split('T')[0] : ''),
        cost_per_user: (sub && sub.cost_per_user != null) ? sub.cost_per_user : (vendor.cost_per_user || ''),
        cost_per_employee: (sub && sub.cost_per_employee != null) ? sub.cost_per_employee : (vendor.cost_per_employee || ''),
        max_users: (sub && sub.max_users != null) ? String(sub.max_users) : (vendor.max_users || ''),
        max_employees: (sub && sub.max_employees != null) ? String(sub.max_employees) : (vendor.max_employees || ''),
        max_web_sessions: (sub && sub.max_web_sessions != null) ? String(sub.max_web_sessions) : String(normalizePositiveInt(vendor.max_web_sessions, 1)),
        admin_username: vendor.admin_username || '',
        admin_password: '',
        user_username: vendor.user_username || '',
        user_password: '',
        frontend_bundle_id: vendor.frontend_bundle_id || 'default_attendance',
        backend_service_id: vendor.backend_service_id || 'default_api',
        features: vendor.features || [],
        vertical: vendor.vertical || '',
        attendance_type: vendor.attendance_type || 'total_time',
        retention_days: String(vendor.retention_days || 90)
      });
    } catch (e) {
      setNewVendor({
        company_name: vendor.company_name || '',
        contact_person: vendor.contact_person || '',
        phone: vendor.phone || '',
        email: vendor.email || '',
        start_date: vendor.start_date ? new Date(vendor.start_date).toISOString().split('T')[0] : '',
        end_date: vendor.end_date ? new Date(vendor.end_date).toISOString().split('T')[0] : '',
        cost_per_user: vendor.cost_per_user || '',
        cost_per_employee: vendor.cost_per_employee || '',
        max_users: vendor.max_users || '',
        max_employees: vendor.max_employees || '',
        max_web_sessions: normalizePositiveInt(vendor.max_web_sessions, 1),
        admin_username: vendor.admin_username || '',
        admin_password: '',
        user_username: vendor.user_username || '',
        user_password: '',
        frontend_bundle_id: vendor.frontend_bundle_id || 'default_attendance',
        backend_service_id: vendor.backend_service_id || 'default_api',
        features: vendor.features || [],
        vertical: vendor.vertical || '',
        attendance_type: vendor.attendance_type || 'total_time',
        retention_days: String(vendor.retention_days || 90)
      });
    }

    try {
      const response = await axios.get(`${API_URL}/admin/vendors/${vendor.id}/registration-config`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setRegistrationConfig(response.data.config || []);
    } catch (error) {
      console.error("Error fetching registration config:", error);
      setRegistrationConfig([]);
    }

    setShowModal(true);
  };

  const handleRestoreDatabase = async (file) => {
    if (!file) return;
    if (!window.confirm(`Are you sure you want to restore/merge data from "${file.name}"? This will add records to your current system.`)) return;

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post(`${API_URL}/admin/database/restore`, formData, {
        headers: {
          Authorization: `Bearer ${user?.token}`,
          'Content-Type': 'multipart/form-data'
        }
      });
      alert(response.data.message || "Database restored successfully!");
      fetchVendors();
      fetchStats();
    } catch (error) {
      alert("Restoration failed: " + (error.response?.data?.error || error.message));
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadFullBackup = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_URL}/admin/database/backup`, {
        headers: { Authorization: `Bearer ${user?.token}` },
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'full_system_backup.db');
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      alert("Backup failed: " + (error.response?.data?.error || error.message));
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordReset = async (e) => {
    e.preventDefault();
    try {
      await axios.put(`${API_URL}/admin/users/password`, {
        username: passwordModal.username,
        new_password: newPassword
      }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      alert(`Password for ${passwordModal.username} updated successfully!`);
      setPasswordModal({ show: false, username: '' });
      setNewPassword('');
    } catch (error) {
      alert("Error: " + (error.response?.data?.error || error.message));
    }
  };

  const handleSuspend = async (id, currentStatus) => {
    const action = currentStatus === 'suspended' ? 'activate' : 'suspend';
    if (!window.confirm(`Are you sure you want to ${action} this vendor?`)) return;

    try {
      await axios.post(`${API_URL}/admin/vendors/${id}/suspend`, { action }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchVendors();
    } catch (error) {
      alert("Error updating status");
    }
  };

  const handleToggleWebLogin = async (vendor) => {
    const newStatus = vendor.web_login_enabled === 0; // Toggle
    try {
      await axios.post(`${API_URL}/admin/vendors/${vendor.id}/toggle_web_login`, { enabled: newStatus }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      // Optimistic update or refetch
      setVendors(vendors.map(v => v.id === vendor.id ? { ...v, web_login_enabled: newStatus ? 1 : 0 } : v));
    } catch (error) {
      alert("Error updating web login status");
    }
  };

  const handleDeleteVendor = async (vendor) => {
    if (!window.confirm(`Delete vendor "${vendor.company_name}" and all related data? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API_URL}/admin/vendors/${vendor.id}`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setVendors(prev => prev.filter(v => v.id !== vendor.id));
      fetchStats(); // Refresh dashboard counts
    } catch (error) {
      alert("Error deleting vendor: " + (error.response?.data?.error || error.message));
    }
  };

  const handlePortableExport = async (vendor) => {
    try {
      const response = await axios.get(`${API_URL}/admin/vendors/${vendor.id}/portable-export`, {
        headers: { Authorization: `Bearer ${user?.token}` },
        responseType: 'blob'
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `vendor_${vendor.id}_${vendor.company_name.replace(/\s+/g, '_')}_portable.gz`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      alert("Failed to export vendor data: " + (err.response?.data?.error || err.message));
    }
  };

  const handlePortableImport = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const response = await axios.post(`${API_URL}/admin/vendors/portable-import`, formData, {
        headers: { 
          'Content-Type': 'multipart/form-data',
          Authorization: `Bearer ${user?.token}` 
        }
      });
      alert(`Success! Vendor imported with ID: ${response.data.vendor_id}. Total faces: ${response.data.faces_imported}`);
      fetchVendors();
      fetchStats();
    } catch (err) {
      alert("Failed to import vendor data: " + (err.response?.data?.error || err.message));
    } finally {
      e.target.value = '';
    }
  };
  const handleViewInvoices = async (vendor) => {
    try {
      const response = await axios.get(`${API_URL}/admin/vendors/${vendor.id}/invoices`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setInvoiceModal({ show: true, vendor: vendor, invoices: response.data.invoices });
    } catch (error) {
      alert("Error fetching invoices");
    }
  };

  const handleGenerateInvoice = async () => {
    if (!invoiceModal.vendor) return;
    try {
      const response = await axios.post(`${API_URL}/admin/vendors/${invoiceModal.vendor.id}/invoices/generate`, {}, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      alert(`Invoice Generated! Amount: ₹${response.data.amount}`);
      handleViewInvoices(invoiceModal.vendor); // Refresh list
    } catch (error) {
      alert("Error: " + (error.response?.data?.error || error.message));
    }
  };

  const handleMarkPaid = async (invoiceId) => {
    try {
      await axios.put(`${API_URL}/admin/invoices/${invoiceId}/status`, { status: 'paid' }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      handleViewInvoices(invoiceModal.vendor); // Refresh
    } catch (error) {
      alert("Error updating status");
    }
  };

  const calculateDaysLeft = (endDate) => {
    if (!endDate) return null;
    const end = new Date(endDate);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    end.setHours(0, 0, 0, 0);
    const diffTime = end - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
  };

  const normalizeLimit = (value, { min = 1 } = {}) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return null;
    if (n === 0) return null;
    const v = Math.abs(Math.trunc(n));
    if (min != null && v < min) return min;
    return v;
  };

  const resolveBusinessView = (vendor) => {
    const features = Array.isArray(vendor?.features) ? vendor.features : [];
    if (vendor?.vertical === 'school') return 'school';
    if (features.includes('report_payroll') || features.includes('payroll')) return 'payroll';
    return 'attendance';
  };

  // --- New Helper Functions for Vendor Details Tab ---
  const fetchVendorEmployees = async (vendorId) => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_URL}/admin/vendors/${vendorId}/employees`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setVendorEmployees(response.data.employees || []);
      setDetailViewMode('vendor');
    } catch (error) {
      alert("Error fetching employees: " + (error.response?.data?.error || error.message));
    } finally {
      setLoading(false);
    }
  };

  const fetchEmployeeReport = async (vendorId, employee) => {
    setLoading(true);
    try {
      const view = resolveBusinessView(selectedVendorForDetail);
      if (view !== 'payroll') {
        const att = await axios.get(`${API_URL}/attendance`, {
          params: {
            start_date: reportDateRange.start,
            end_date: reportDateRange.end,
            person_id: employee.id,
            vendor_id: vendorId
          },
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        setEmployeeReport({ name: employee.name, attendance: att.data.attendance || [] });
        setSelectedEmployeeForDetail(employee);
        setDetailViewMode('employee');
        return;
      }
      const response = await axios.get(`${API_URL}/reports/payroll`, {
        params: {
          start_date: reportDateRange.start,
          end_date: reportDateRange.end,
          vendor_id: vendorId
        },
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const report = response.data.payroll.find(p => String(p.person_id) === String(employee.id));
      setEmployeeReport(report);
      setSelectedEmployeeForDetail(employee);
      setDetailViewMode('employee');
    } catch (error) {
      if (error.response && error.response.status === 403) {
        try {
          const att = await axios.get(`${API_URL}/attendance`, {
            params: {
              start_date: reportDateRange.start,
              end_date: reportDateRange.end,
              person_id: employee.id,
              vendor_id: vendorId
            },
            headers: { Authorization: `Bearer ${user?.token}` }
          });
          setEmployeeReport({ name: employee.name, attendance: att.data.attendance || [] });
          setSelectedEmployeeForDetail(employee);
          setDetailViewMode('employee');
        } catch (e2) {
          alert("Error fetching report");
        }
      } else {
        alert("Error fetching report");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleExportEmployees = async () => {
    if (!selectedVendorForDetail) return;
    try {
      const res = await axios.get(`${API_URL}/admin/vendors/${selectedVendorForDetail.id}/employees/export`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${selectedVendorForDetail.company_name}_employees.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("Export failed");
    }
  };

  const handleImportEmployees = async (file) => {
    if (!selectedVendorForDetail || !file) return;
    try {
      const text = await file.text();
      await axios.post(`${API_URL}/admin/vendors/${selectedVendorForDetail.id}/employees/import`, {
        csv_data: text
      }, { headers: { Authorization: `Bearer ${user?.token}` } });
      fetchVendorEmployees(selectedVendorForDetail.id);
      alert("Import succeeded");
    } catch (e) {
      alert("Import failed");
    }
  };

  const handleManualArchival = async () => {
    if (!window.confirm("Trigger automated data archival now? This moves old records to the backup database.")) return;
    try {
      setLoading(true);
      await axios.post(`${API_URL}/admin/archival/run`, {}, { headers: { Authorization: `Bearer ${user?.token}` } });
      alert("Archival process triggered successfully.");
    } catch (e) {
      alert("Archival trigger failed: " + (e.response?.data?.error || e.message));
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadArchivalBackup = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_URL}/admin/archival/download`, {
        headers: { Authorization: `Bearer ${user?.token}` },
        responseType: 'blob'
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'backup_faces.db');
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (e) {
      alert("Backup download failed: " + (e.response?.data?.error || e.message));
    } finally {
      setLoading(false);
    }
  };

  const handleWipeVendorArchivedData = async (vendorId, companyName) => {
    if (!window.confirm(`PERMANENTLY DELETE all archived (backup) data for ${companyName}? This cannot be undone.`)) return;
    try {
      setLoading(true);
      await axios.delete(`${API_URL}/admin/archival/vendors/${vendorId}`, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      alert(`Archived data for ${companyName} wiped successfully.`);
    } catch (e) {
      alert("Wipe failed: " + (e.response?.data?.error || e.message));
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-6 bg-slate-50 min-h-screen">
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Super Admin Dashboard</h1>
          <p className="text-slate-500">Manage Vendors & Subscriptions</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setPasswordModal({ show: true, username: user.username })}
            className="bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 px-4 py-2 rounded-lg flex items-center gap-2"
          >
            <Lock size={18} /> Change My Password
          </button>
          <div className="flex gap-2">
            <label className="bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 px-4 py-2 rounded-lg flex items-center gap-2 cursor-pointer shadow-sm transition-all active:scale-95">
              <UploadCloud size={18} /> Import Portable Vendor
              <input type="file" className="hidden" accept=".gz,.json" onChange={handlePortableImport} />
            </label>
            <button
              onClick={() => {
                setEditingVendor(null);
                setNewVendor({
                  company_name: '', contact_person: '', phone: '', email: '',
                  start_date: '', end_date: '',
                  cost_per_user: '', cost_per_employee: '',
                  max_users: '', max_employees: '',
                  max_web_sessions: '',
                  registration_template: '',
                  admin_username: '', admin_password: '',
                  user_username: '', user_password: '',
                  features: [],
                  vertical: '',
                  frontend_bundle_id: 'default_attendance',
                  backend_service_id: 'default_api',
                  attendance_type: 'total_time',
                  retention_days: '90'
                });
                setRegistrationConfig([]);
                setShowModal(true);
              }}
              className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg flex items-center gap-2"
            >
              <Plus size={18} /> Add New Vendor
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-6 mb-6 border-b border-slate-200">
        <button
          className={`pb-3 px-2 font-medium transition-colors ${activeTab === 'overview' ? 'border-b-2 border-indigo-600 text-indigo-600' : 'text-slate-500 hover:text-slate-700'}`}
          onClick={() => setActiveTab('overview')}
        >
          Attendance / Overview
        </button>
        <button
          className={`pb-3 px-2 font-medium transition-colors ${activeTab === 'vendor_details' ? 'border-b-2 border-indigo-600 text-indigo-600' : 'text-slate-500 hover:text-slate-700'}`}
          onClick={() => {
            setActiveTab('vendor_details');
            setDetailViewMode('list');
            setSelectedVendorForDetail(null);
          }}
        >
          Details of Vendors
        </button>
        <button
          className={`pb-3 px-2 font-medium transition-colors ${activeTab === 'maintenance' ? 'border-b-2 border-indigo-600 text-indigo-600' : 'text-slate-500 hover:text-slate-700'}`}
          onClick={() => setActiveTab('maintenance')}
        >
          System Maintenance
        </button>
      </div>

      {activeTab === 'overview' && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            <StatCard label="Total Vendors" value={stats.total_vendors} icon={<Shield className="text-blue-600" size={24} />} />
            <StatCard label="Active Vendors" value={stats.active_vendors} icon={<Check className="text-green-600" size={24} />} />
            <StatCard label="Total Employees" value={stats.total_employees} icon={<User className="text-purple-600" size={24} />} />
            <StatCard label="Monthly Revenue" value={`₹${(stats.monthly_recurring_revenue || 0).toLocaleString()}`} icon={<DollarSign className="text-emerald-600" size={24} />} />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            <StatCard label="Live Streams" value={stats.active_streaming_devices} icon={<Activity className="text-orange-600" size={24} />} />
            <StatCard
              label="Offline Devices"
              value={stats.offline_devices}
              icon={<WifiOff className="text-slate-400" size={24} />}
              color={stats.offline_devices > 0 ? "text-amber-600" : ""}
            />
            <StatCard
              label="Low Battery"
              value={stats.low_battery_devices}
              icon={<Battery className="text-red-500" size={24} />}
              color={stats.low_battery_devices > 0 ? "text-red-600" : ""}
            />
          </div>

          {/* Filters Section */}
          <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-200 mb-6 flex flex-wrap gap-4 items-center">
            <div className="flex-1 min-w-[200px] relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-slate-400" size={18} />
              <input
                type="text"
                placeholder="Search vendors, contacts, emails..."
                className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <div className="flex items-center gap-2">
              <Filter size={18} className="text-slate-500" />
              <select
                className="p-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none text-slate-600 bg-white"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">All Status</option>
                <option value="active">Active</option>
                <option value="suspended">Suspended</option>
              </select>

              <select
                className="p-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none text-slate-600 bg-white"
                value={subscriptionFilter}
                onChange={(e) => setSubscriptionFilter(e.target.value)}
              >
                <option value="all">All Subscriptions</option>
                <option value="Active">Active</option>
                <option value="Expired">Expired</option>
              </select>
            </div>

            <div className="text-sm text-slate-500 ml-auto">
              Showing {filteredVendors.length} of {vendors.length} vendors
            </div>
          </div>

          <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200">
            <div className="p-3 border-b border-slate-100 flex flex-wrap gap-2 items-center">
              <span className="text-sm text-slate-600">Selected: {selectedVendorIds.length}</span>
              <button onClick={handleBulkSuspend} className="text-xs bg-red-50 text-red-600 px-2 py-1 rounded">Suspend</button>
              <button onClick={handleBulkActivate} className="text-xs bg-green-50 text-green-600 px-2 py-1 rounded">Activate</button>
              <button onClick={() => handleBulkToggleFeature('report_payroll', true)} className="text-xs bg-blue-50 text-blue-600 px-2 py-1 rounded">Enable Payroll</button>
              <button onClick={() => handleBulkToggleFeature('report_payroll', false)} className="text-xs bg-slate-50 text-slate-600 px-2 py-1 rounded">Disable Payroll</button>
              <button onClick={() => handleBulkUpdateWebSessions(1)} className="text-xs bg-indigo-50 text-indigo-600 px-2 py-1 rounded">Set Web Sessions = 1</button>
            </div>
            <table className="w-full text-left">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="p-4 font-semibold text-slate-600">
                    <input type="checkbox" onChange={e => {
                      if (e.target.checked) setSelectedVendorIds(filteredVendors.map(v => v.id));
                      else setSelectedVendorIds([]);
                    }} />
                  </th>
                  <th className="p-4 font-semibold text-slate-600">Company</th>
                  <th className="p-4 font-semibold text-slate-600">Architecture</th>
                  <th className="p-4 font-semibold text-slate-600">Contact</th>
                  <th className="p-4 font-semibold text-slate-600">Status</th>
                  <th className="p-4 font-semibold text-slate-600">Plan & Cost</th>
                  <th className="p-4 font-semibold text-slate-600">Usage / Limits</th>
                  <th className="p-4 font-semibold text-slate-600">Duration</th>
                  <th className="p-4 font-semibold text-slate-600">Logins (Admin/User)</th>
                  <th className="p-4 font-semibold text-slate-600">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredVendors.length === 0 ? (
                  <tr>
                    <td colSpan="9" className="p-8 text-center text-slate-500">
                      No vendors found matching your filters.
                    </td>
                  </tr>
                ) : (
                  filteredVendors.map(vendor => (
                    <tr key={vendor.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="p-4">
                        <input type="checkbox" checked={selectedVendorIds.includes(vendor.id)} onChange={e => toggleSelected(vendor.id, e.target.checked)} />
                      </td>
                      <td className="p-4 font-medium text-slate-800">{vendor.company_name}</td>
                      <td className="p-4 text-xs">
                        <div className="flex flex-col gap-1">
                          <span className="bg-purple-50 text-purple-700 px-2 py-1 rounded border border-purple-100 whitespace-nowrap" title="Frontend Bundle">
                            UI: {vendor.frontend_bundle_id?.replace('_', ' ') || 'Default'}
                          </span>
                          <span className="bg-orange-50 text-orange-700 px-2 py-1 rounded border border-orange-100 whitespace-nowrap" title="Backend Service">
                            API: {vendor.backend_service_id?.replace('_', ' ') || 'Default'}
                          </span>
                        </div>
                      </td>
                      <td className="p-4 text-slate-600">
                        <div>{vendor.contact_person}</div>
                        <div className="text-xs text-slate-400">{vendor.phone}</div>
                      </td>
                      <td className="p-4">
                        <StatusBadge status={vendor.status} />
                      </td>
                      <td className="p-4">
                        <div className="flex flex-col items-start gap-1">
                          <span className="capitalize px-2 py-1 bg-blue-50 text-blue-700 rounded text-xs font-medium border border-blue-100">
                            {vendor.plan_type || 'None'}
                          </span>
                          <div className="flex flex-col">
                            <span className="text-sm font-bold text-slate-700">₹{vendor.cost_per_user || 0}<span className="text-xs font-normal text-slate-400">/user</span></span>
                            <span className="text-xs text-slate-500">Total: ₹{(vendor.cost_per_user || 0) * (vendor.max_users || 0)}</span>
                          </div>
                          {vendor.vertical && (
                            <span className="mt-1 text-xs bg-purple-50 text-purple-700 px-2 py-1 rounded border border-purple-100">
                              Business: {vendor.vertical}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="p-4">
                        <div className="flex flex-col gap-2 text-sm">
                          <div className="flex justify-between items-center min-w-[120px]">
                            <span className="text-slate-500">Employees:</span>
                            <span className={`font-mono font-bold ${(vendor.employee_count || 0) > (vendor.max_employees || 0) ? 'text-red-600' : 'text-slate-700'}`}>
                              {vendor.employee_count || 0} / {vendor.max_employees || '∞'}
                            </span>
                          </div>
                          <div className="flex justify-between items-center min-w-[120px]">
                            <span className="text-slate-500">Phones:</span>
                            <div className="flex flex-col items-end">
                              {(() => {
                                const limit = normalizeLimit(vendor.max_mobile_devices) ?? normalizeLimit(vendor.max_users);
                                const used = Number(vendor.device_count || 0);
                                const over = limit != null ? used > limit : false;
                                return (
                                  <span className={`font-mono font-bold ${over ? 'text-red-600' : 'text-slate-700'}`}>
                                    {used} / {limit ?? '∞'}
                                  </span>
                                );
                              })()}
                              {(vendor.active_device_count || 0) > 0 && (
                                <span className="text-xs text-green-600 font-medium flex items-center gap-1">
                                  <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                                  {vendor.active_device_count} Active
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="p-4 text-slate-600 text-sm">
                        <div className="flex flex-col">
                          <span className="text-xs text-slate-500">From: {vendor.start_date || '?'}</span>
                          <span className={`text-xs ${vendor.subscription_status === 'Expired' ? 'text-red-600 font-bold' : 'text-slate-500'}`}>
                            {vendor.subscription_status === 'Expired' ? 'Expired: ' : 'Next Bill: '}{vendor.end_date || '-'}
                          </span>
                          {vendor.end_date && (
                            <span className={`text-xs font-medium mt-1 ${calculateDaysLeft(vendor.end_date) < 7 ? 'text-red-600' : 'text-blue-600'}`}>
                              {calculateDaysLeft(vendor.end_date)} Days Left
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="p-4 text-slate-600">
                        <div className="flex flex-col gap-1">
                          {vendor.admin_username && (
                            <div className="flex items-center gap-1 text-xs bg-indigo-50 text-indigo-700 px-2 py-1 rounded border border-indigo-100 w-fit" title="Admin Username">
                              <Shield size={12} />
                              <span className="font-mono">{vendor.admin_username}</span>
                            </div>
                          )}
                          {vendor.user_username && (
                            <div className="flex items-center gap-1 text-xs bg-green-50 text-green-700 px-2 py-1 rounded border border-green-100 w-fit" title="User Username">
                              <User size={12} />
                              <span className="font-mono">{vendor.user_username}</span>
                            </div>
                          )}
                          <div className="flex items-center gap-2 mt-1 cursor-pointer hover:opacity-80" onClick={() => handleToggleWebLogin(vendor)} title="Toggle Web Dashboard Access">
                            <span className="text-xs text-slate-500">Web Access:</span>
                            {vendor.web_login_enabled !== 0 ? <ToggleRight className="text-green-500" size={20} /> : <ToggleLeft className="text-slate-400" size={20} />}
                          </div>
                        </div>
                      </td>
                      <td className="p-4">
                        <div className="flex gap-2">
                          {vendor.features?.includes('leave_management') && (
                            <button
                              onClick={() => handleOpenLeaveConfig(vendor)}
                              className="p-1.5 rounded hover:bg-slate-200 text-indigo-600"
                              title="Leave Management Configuration"
                            >
                              <Shield size={16} />
                            </button>
                          )}
                          <button
                            onClick={() => handleEditClick(vendor)}
                            className="p-1.5 rounded hover:bg-slate-200 text-slate-600"
                            title="Edit Vendor Details"
                          >
                            <Pencil size={16} />
                          </button>
                          <button
                            onClick={() => handleSuspend(vendor.id, vendor.status)}
                            className={`p-1.5 rounded hover:bg-slate-200 ${vendor.status === 'suspended' ? 'text-green-600' : 'text-red-600'}`}
                            title={vendor.status === 'suspended' ? 'Activate' : 'Suspend'}
                          >
                            {vendor.status === 'suspended' ? <Check size={16} /> : <X size={16} />}
                          </button>
                          <button
                            onClick={() => handleViewInvoices(vendor)}
                            className="p-1.5 rounded hover:bg-slate-200 text-blue-600"
                            title="View Invoices"
                          >
                            <DollarSign size={16} />
                          </button>
                          {vendor.admin_username && (
                            <button
                              onClick={() => setPasswordModal({ show: true, username: vendor.admin_username })}
                              className="p-1.5 rounded hover:bg-slate-200 text-slate-600"
                              title={`Reset Password for ${vendor.admin_username}`}
                            >
                              <Lock size={16} />
                            </button>
                          )}
                          <button
                            onClick={() => handlePortableExport(vendor)}
                            className="p-1.5 rounded hover:bg-slate-200 text-indigo-600"
                            title="Portable Export (JSON + Biometrics)"
                          >
                            <Box size={16} />
                          </button>
                          <button
                            onClick={() => handleDeleteVendor(vendor)}
                            className="p-1.5 rounded hover:bg-slate-200 text-red-600"
                            title="Delete Vendor"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {activeTab === 'vendor_details' && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          {detailViewMode === 'list' && (
            <div>
              <h2 className="text-xl font-bold mb-6 text-slate-800">Select a Vendor to View Details</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {vendors.map(vendor => (
                  <div key={vendor.id}
                    onClick={() => {
                      setSelectedVendorForDetail(vendor);
                      fetchVendorEmployees(vendor.id);
                      fetchVendorStudentLogins(vendor.id);
                      fetchVendorParents(vendor.id);
                      fetchVendorDevices(vendor.id);
                      fetchVendorDeviceSlots(vendor.id);
                    }}
                    className="p-5 border border-slate-200 rounded-xl cursor-pointer hover:border-indigo-500 hover:shadow-md transition-all group bg-white"
                  >
                    <div className="flex items-start gap-4 mb-3">
                      <div className="w-12 h-12 rounded-full bg-indigo-50 flex items-center justify-center text-indigo-600 font-bold text-lg border border-indigo-100">
                        {vendor.company_name.substring(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <h3 className="font-bold text-slate-800 text-lg group-hover:text-indigo-600 transition-colors">{vendor.company_name}</h3>
                        <p className="text-sm text-slate-500">{vendor.contact_person}</p>
                      </div>
                    </div>
                    <div className="pt-3 border-t border-slate-100 flex justify-between items-center">
                      <span className="text-sm text-slate-500">Employees: <span className="font-semibold text-slate-700">{vendor.employee_count || 0}</span></span>
                      <span className="flex items-center gap-1 text-indigo-600 font-medium text-sm group-hover:translate-x-1 transition-transform">View Details <ArrowRight size={16} /></span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {detailViewMode === 'vendor' && selectedVendorForDetail && (
            <div>
              <button onClick={() => setDetailViewMode('list')} className="mb-6 flex items-center gap-2 text-slate-500 hover:text-slate-800 font-medium transition-colors">
                <ArrowLeft size={18} /> Back to Vendor List
              </button>
              <div className="flex justify-between items-center mb-8 pb-4 border-b border-slate-100">
                <div>
                  <h2 className="text-2xl font-bold text-slate-800">{selectedVendorForDetail.company_name}</h2>
                  <p className="text-slate-500">Employee Directory</p>
                </div>
                <div className="bg-indigo-50 text-indigo-700 px-4 py-2 rounded-lg font-mono text-sm">
                  Vendor ID: {selectedVendorForDetail.id}
                </div>
              </div>

              {/* Devices Panel */}
              <div className="mb-8 bg-white border border-slate-200 rounded-xl shadow-sm">
                <div className="flex items-center justify-between p-4 border-b border-slate-200">
                  <div>
                    <h3 className="font-bold text-slate-800">Mobile Devices</h3>
                    <p className="text-slate-500 text-sm">Name and track devices for this vendor</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => fetchVendorDevices(selectedVendorForDetail.id)}
                      className="text-xs bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-700 px-3 py-1.5 rounded"
                    >
                      Refresh
                    </button>
                  </div>
                </div>
                <div className="p-4">
                  {/* Slot Configuration */}
                  <div className="mb-5">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="font-semibold text-slate-700">Predefined Places (Slots)</h4>
                      <div className="text-xs text-slate-500">
                        Configure labels shown to mobiles on first login
                        {(() => {
                          const limit = normalizeLimit(selectedVendorForDetail?.max_mobile_devices) ?? normalizeLimit(selectedVendorForDetail?.max_users);
                          const used = (deviceSlots || []).length;
                          return (
                            <span className="ml-3 font-mono text-slate-600">
                              {used} / {limit ?? '∞'}
                            </span>
                          );
                        })()}
                      </div>
                    </div>
                    {(() => {
                      const limit = normalizeLimit(selectedVendorForDetail?.max_mobile_devices) ?? normalizeLimit(selectedVendorForDetail?.max_users);
                      const over = limit != null && (deviceSlots || []).length > limit;
                      if (!over) return null;
                      return (
                        <div className="mb-3 p-3 rounded-lg border border-red-200 bg-red-50 text-red-700 text-sm flex items-center justify-between">
                          <span>Over limit. Reduce places to match plan.</span>
                          <button
                            onClick={async () => {
                              const limit2 = normalizeLimit(selectedVendorForDetail?.max_mobile_devices) ?? normalizeLimit(selectedVendorForDetail?.max_users);
                              const slots = Array.from(deviceSlots || []);
                              const unassigned = slots.filter(s => !s.assigned_device_id);
                              const assigned = slots.filter(s => s.assigned_device_id);
                              const extra = slots.length - (limit2 || 0);
                              const removeList = [];
                              for (let i = 0; i < unassigned.length && removeList.length < extra; i++) removeList.push(unassigned[i]);
                              for (let i = 0; i < assigned.length && removeList.length < extra; i++) removeList.push(assigned[i]);
                              for (const s of removeList) {
                                if (s.assigned_device_id) {
                                  await adminAssignDeviceSlot(selectedVendorForDetail.id, s.assigned_device_id, '');
                                }
                              }
                              const keep = slots.filter(s => !removeList.find(r => (r.slot_name === s.slot_name)));
                              const nextNames = keep.slice(0, limit2).map(s => s.slot_name);
                              await saveDeviceSlots(selectedVendorForDetail.id, nextNames);
                              await fetchVendorDeviceSlots(selectedVendorForDetail.id);
                            }}
                            className="text-xs bg-red-600 text-white px-3 py-1.5 rounded border border-red-600 hover:bg-red-700"
                          >
                            Trim to Limit
                          </button>
                        </div>
                      );
                    })()}
                    <div className="flex gap-2 mb-3">
                      <input
                        className="flex-1 p-2 border rounded text-sm"
                        placeholder="Add place e.g., Office"
                        value={newSlotName}
                        onChange={e => setNewSlotName(e.target.value)}
                      />
                      <button
                        onClick={() => {
                          const name = (newSlotName || '').trim();
                          if (!name) return;
                          const limit = normalizeLimit(selectedVendorForDetail?.max_mobile_devices) ?? normalizeLimit(selectedVendorForDetail?.max_users);
                          const current = (deviceSlots || []).length;
                          if (limit != null && current >= limit) {
                            alert(`You have reached the maximum number of places (${limit}) allowed for this vendor.`);
                            return;
                          }
                          const next = Array.from(new Set([...(deviceSlots || []).map(s => s.slot_name), name]));
                          const trimmed = (limit != null && next.length > limit) ? next.slice(0, limit) : next;
                          saveDeviceSlots(selectedVendorForDetail.id, trimmed);
                          setNewSlotName('');
                        }}
                        className="text-xs bg-indigo-600 text-white px-3 py-1.5 rounded border border-indigo-600 hover:bg-indigo-700"
                      >
                        Add
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(deviceSlots || []).map((s) => (
                        <div key={s.id || s.slot_name} className="flex items-center gap-2 border rounded px-2 py-1 text-sm">
                          <span className="font-mono">{s.slot_name}</span>
                          {s.assigned_device_id && (
                            <span className="text-xs text-green-600">assigned</span>
                          )}
                          <button
                            className="text-xs text-red-600 cursor-pointer hover:opacity-80"
                            title="Delete this place"
                            onClick={() => deletePlaceSlot(selectedVendorForDetail.id, s.slot_name)}
                          >
                            delete
                          </button>
                        </div>
                      ))}
                      {(deviceSlots || []).length === 0 && (
                        <div className="text-slate-400 text-sm">No slots configured</div>
                      )}
                    </div>
                  </div>
                  {/* No manual device entry; devices appear after first mobile login and place selection */}
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="text-left text-slate-500">
                          <th className="p-2">Device ID</th>
                          <th className="p-2">Place</th>
                          <th className="p-2">Status</th>
                          <th className="p-2">Battery</th>
                          <th className="p-2">Registered</th>
                          <th className="p-2">Last Active</th>
                          <th className="p-2"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {vendorDevices.length === 0 ? (
                          <tr>
                            <td colSpan="7" className="p-3 text-slate-400">No devices discovered yet.</td>
                          </tr>
                        ) : vendorDevices.map(d => {
                          const online = isOnline(d.last_active_at);
                          return (
                            <tr key={d.id || d.device_id} className="border-t border-slate-100">
                              <td className="p-2 font-mono">{d.device_id}</td>
                              <td className="p-2">
                                <div className="w-full p-2 border rounded text-sm bg-slate-50 text-slate-700">{d.device_name || '-'}</div>
                              </td>
                              <td className="p-2">
                                <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium w-fit ${online ? 'bg-green-50 text-green-700 border border-green-100' : 'bg-slate-50 text-slate-500 border border-slate-100'}`}>
                                  <div className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-green-500 animate-pulse' : 'bg-slate-300'}`}></div>
                                  {online ? 'Online' : 'Offline'}
                                </div>
                              </td>
                              <td className="p-2">
                                {d.battery_level !== null && d.battery_level !== undefined ? (
                                  <div className="flex items-center gap-1 text-slate-600">
                                    <Battery size={14} className={d.battery_level < 20 ? 'text-red-500' : 'text-slate-400'} />
                                    <span className={d.battery_level < 20 ? 'text-red-600 font-bold' : ''}>{Math.round(d.battery_level)}%</span>
                                  </div>
                                ) : '-'}
                              </td>
                              <td className="p-2 text-slate-500">{d.registered_at || '-'}</td>
                              <td className="p-2 text-slate-500" title={d.last_active_at || d.last_login_at}>
                                {d.last_active_at ? new Date(d.last_active_at).toLocaleTimeString() : (d.last_login_at || '-')}
                              </td>
                              <td className="p-2">
                                <div className="flex items-center gap-2">
                                  <button
                                    onClick={() => adminAssignDeviceSlot(selectedVendorForDetail.id, d.device_id, '')}
                                    className="text-xs px-3 py-1.5 rounded border bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                                    title="Clear place"
                                  >
                                    Clear
                                  </button>
                                  <button
                                    onClick={() => logoutVendorDevice(selectedVendorForDetail.id, d.device_id)}
                                    className="text-xs px-3 py-1.5 rounded border bg-white text-amber-700 border-amber-200 hover:bg-amber-50"
                                    title="Logout this device"
                                  >
                                    Logout
                                  </button>
                                  <button
                                    onClick={() => deleteVendorDevice(selectedVendorForDetail.id, d.device_id)}
                                    className="text-xs px-3 py-1.5 rounded border bg-white text-red-600 border-red-200 hover:bg-red-50"
                                    title="Delete this device"
                                  >
                                    Delete
                                  </button>
                                  <select
                                    value=""
                                    onChange={(e) => {
                                      const name = (e.target.value || '').trim();
                                      if (!name) return;
                                      adminAssignDeviceSlot(selectedVendorForDetail.id, d.device_id, name);
                                    }}
                                    className="text-xs px-2 py-1.5 border rounded bg-white text-slate-700 border-slate-300"
                                    title="Assign from predefined places"
                                  >
                                    <option value="">Assign to…</option>
                                    {(deviceSlots || []).map(s => (
                                      <option key={s.slot_name} value={s.slot_name}>{s.slot_name}</option>
                                    ))}
                                  </select>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              {vendorEmployees.length === 0 ? (
                <div className="text-center py-12 text-slate-400 bg-slate-50 rounded-xl border border-dashed border-slate-200">
                  No employees found for this vendor.
                </div>
              ) : (
                <>
                  <div className="flex justify-end gap-3 mb-3">
                    <button onClick={handleExportEmployees} className="text-xs bg-blue-50 text-blue-600 px-3 py-1.5 rounded border border-blue-200">Export CSV</button>
                    <label className="text-xs bg-slate-50 text-slate-700 px-3 py-1.5 rounded border border-slate-200 cursor-pointer">
                      Import CSV
                      <input type="file" accept=".csv,text/csv" className="hidden" onChange={e => handleImportEmployees(e.target.files?.[0])} />
                    </label>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6">
                    {vendorEmployees.map(emp => (
                      <div key={emp.id}
                        onClick={() => fetchEmployeeReport(selectedVendorForDetail.id, emp)}
                        className="bg-white rounded-xl overflow-hidden border border-slate-200 cursor-pointer hover:shadow-lg hover:border-indigo-300 transition-all group"
                      >
                        <div className="h-48 bg-slate-100 w-full overflow-hidden relative">
                          {emp.face_image ? (
                            <img src={emp.face_image.startsWith('data:') ? emp.face_image : `data:image/jpeg;base64,${emp.face_image}`} alt={emp.name} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
                          ) : (
                            <div className="w-full h-full flex flex-col items-center justify-center text-slate-400">
                              <User size={48} className="mb-2 opacity-20" />
                              <span className="text-xs uppercase tracking-wide">No Photo</span>
                            </div>
                          )}
                          <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center pb-4">
                            <span className="text-white font-medium text-sm flex items-center gap-2"><Eye size={14} /> View Report</span>
                          </div>
                        </div>
                        <div className="p-4">
                          <h3 className="font-bold text-lg text-slate-800 mb-1">{emp.name}</h3>
                          <p className="text-sm text-slate-500 mb-2">{emp.designation || 'No Designation'}</p>
                          <span className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full border border-slate-200">{emp.department || 'General'}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}

              <div className="mt-12 pt-8 border-t border-slate-200">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h3 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                      <Lock size={20} className="text-blue-600" />
                      Student Web Logins
                    </h3>
                    <p className="text-sm text-slate-500 mt-1">View and manage student credentials (plain-text passwords visible here)</p>
                  </div>
                  <button
                    onClick={() => fetchVendorStudentLogins(selectedVendorForDetail.id)}
                    className="flex items-center gap-2 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg border border-slate-200 transition-all font-medium text-sm"
                  >
                    <RefreshCw size={14} /> Refresh Logins
                  </button>
                </div>

                {vendorStudentLogins.length === 0 ? (
                  <div className="text-center py-16 text-slate-400 bg-slate-50/50 rounded-2xl border border-dashed border-slate-200">
                    <User size={48} className="mx-auto mb-3 opacity-20" />
                    <p>No student logins generated yet for this vendor.</p>
                  </div>
                ) : (
                  <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-sm">
                        <thead>
                          <tr className="bg-slate-50/50 text-slate-600 border-b border-slate-200">
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Student ID</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Full Name</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Initial Password</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Last Login</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {vendorStudentLogins.map((login, idx) => (
                            <tr key={idx} className="hover:bg-blue-50/30 transition-colors group">
                              <td className="p-4">
                                <span className="font-mono font-bold text-blue-600 bg-blue-50 px-2 py-1 rounded">{login.username}</span>
                              </td>
                              <td className="p-4 font-medium text-slate-700">{login.full_name || '-'}</td>
                              <td className="p-4">
                                <div className="flex items-center gap-2">
                                  <code className="bg-amber-50 text-amber-700 px-2 py-1 rounded font-mono font-bold text-xs border border-amber-100">
                                    {login.password_plain || '********'}
                                  </code>
                                </div>
                              </td>
                              <td className="p-4 text-slate-500 font-mono text-xs">{login.last_login || 'Never'}</td>
                              <td className="p-4">
                                {login.password_plain ? (
                                  <span className="flex items-center gap-1.5 text-amber-600 text-xs font-bold">
                                    <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></div>
                                    First Login Pending
                                  </span>
                                ) : (
                                  <span className="flex items-center gap-1.5 text-green-600 text-xs font-bold">
                                    <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                                    Password Changed
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-12 pt-8 border-t border-slate-200">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h3 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                      <Users size={20} className="text-indigo-600" />
                      Registered Parents
                    </h3>
                    <p className="text-sm text-slate-500 mt-1">View parents who have registered their faces for leave validation</p>
                  </div>
                  <button
                    onClick={() => fetchVendorParents(selectedVendorForDetail.id)}
                    className="flex items-center gap-2 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg border border-slate-200 transition-all font-medium text-sm"
                  >
                    <RefreshCw size={14} /> Refresh Parents
                  </button>
                </div>

                {vendorParents.length === 0 ? (
                  <div className="text-center py-16 text-slate-400 bg-slate-50/50 rounded-2xl border border-dashed border-slate-200">
                    <Users size={48} className="mx-auto mb-3 opacity-20" />
                    <p>No parents registered yet for this vendor.</p>
                  </div>
                ) : (
                  <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-sm">
                        <thead>
                          <tr className="bg-slate-50/50 text-slate-600 border-b border-slate-200">
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Parent Name</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Student Linked</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Contact Phone</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Registration Date</th>
                            <th className="p-4 font-bold uppercase tracking-wider text-[10px]">Photo</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {vendorParents.map((parent, idx) => (
                            <tr key={idx} className="hover:bg-indigo-50/30 transition-colors group">
                              <td className="p-4">
                                <span className="font-medium text-slate-700">{parent.username}</span>
                              </td>
                              <td className="p-4">
                                <div className="flex flex-col">
                                  <span className="font-bold text-slate-800">{parent.student_name || 'Unknown'}</span>
                                  <span className="text-xs text-slate-500 font-mono">{parent.student_number}</span>
                                </div>
                              </td>
                              <td className="p-4 text-slate-600">{parent.contact_phone || '-'}</td>
                              <td className="p-4 text-slate-500 font-mono text-xs">{parent.created_at || '-'}</td>
                              <td className="p-4">
                                {parent.face_image ? (
                                  <div className="w-10 h-10 rounded-lg overflow-hidden border border-slate-200">
                                    <img src={parent.face_image} alt={parent.username} className="w-full h-full object-cover" />
                                  </div>
                                ) : (
                                  <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center text-slate-400">
                                    <User size={16} />
                                  </div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {detailViewMode === 'employee' && selectedEmployeeForDetail && (
            <div>
              <button onClick={() => setDetailViewMode('vendor')} className="mb-6 flex items-center gap-2 text-slate-500 hover:text-slate-800 font-medium transition-colors">
                <ArrowLeft size={18} /> Back to {selectedVendorForDetail.company_name}
              </button>

              <div className="flex flex-col lg:flex-row gap-6">
                {/* Employee Profile Card */}
                <div className="w-full lg:w-1/3 bg-white border border-slate-200 rounded-xl p-6 h-fit shadow-sm">
                  <div className="aspect-square rounded-xl overflow-hidden bg-slate-100 mb-6 border border-slate-100">
                    {selectedEmployeeForDetail.face_image ? (
                      <img src={selectedEmployeeForDetail.face_image.startsWith('data:') ? selectedEmployeeForDetail.face_image : `data:image/jpeg;base64,${selectedEmployeeForDetail.face_image}`} alt={selectedEmployeeForDetail.name} className="w-full h-full object-cover" />
                    ) : (
                      <div className="flex items-center justify-center h-full text-slate-400 bg-slate-50">
                        <User size={64} className="opacity-20" />
                      </div>
                    )}
                  </div>
                  {(() => {
                    try {
                      const custom = typeof selectedEmployeeForDetail.custom_data === 'string'
                        ? JSON.parse(selectedEmployeeForDetail.custom_data)
                        : selectedEmployeeForDetail.custom_data || {};
                      const imgs = custom && custom.face_images_list && Array.isArray(custom.face_images_list) ? custom.face_images_list : [];
                      if (imgs.length === 0) return null;
                      return (
                        <div className="grid grid-cols-2 gap-3 mb-6">
                          {imgs.slice(0, 2).map((b64, idx) => (
                            <div key={idx} className="aspect-square rounded-lg overflow-hidden bg-slate-100 border border-slate-100">
                              <img src={`data:image/jpeg;base64,${b64}`} alt={`side ${idx + 1}`} className="w-full h-full object-cover" />
                            </div>
                          ))}
                        </div>
                      );
                    } catch (e) { return null; }
                  })()}
                  <h2 className="text-2xl font-bold text-slate-800 mb-1">{selectedEmployeeForDetail.name}</h2>
                  <p className="text-slate-500 mb-6 font-medium">{selectedEmployeeForDetail.designation}</p>

                  <div className="space-y-4">
                    {(() => {
                      let reg = [];
                      try {
                        reg = Array.isArray(selectedVendorForDetail.registration_config)
                          ? selectedVendorForDetail.registration_config
                          : JSON.parse(selectedVendorForDetail.registration_config || '[]');
                      } catch (e) { reg = []; }
                      return reg && reg.length > 0 ? (
                        reg
                          .filter(field => field.enabled !== false && field.field !== 'student_number')
                          .map((field, index) => {
                            const val = (() => {
                              let custom = {};
                              try {
                                custom = typeof selectedEmployeeForDetail.custom_data === 'string'
                                  ? JSON.parse(selectedEmployeeForDetail.custom_data)
                                  : selectedEmployeeForDetail.custom_data || {};
                              } catch (e) { }

                              if (custom[field.field]) return custom[field.field];
                              if (selectedEmployeeForDetail[field.field]) return selectedEmployeeForDetail[field.field];
                              return '-';
                            })();

                            return (
                              <div key={index} className="flex justify-between items-center border-b border-slate-100 pb-3">
                                <span className="text-slate-500 text-sm">{field.label || field.field}</span>
                                <span className="font-semibold text-slate-700">{val}</span>
                              </div>
                            );
                          })
                      ) : (
                        <>
                          <div className="flex justify-between items-center border-b border-slate-100 pb-3">
                            <span className="text-slate-500 text-sm">Department</span>
                            <span className="font-semibold text-slate-700">{selectedEmployeeForDetail.department}</span>
                          </div>
                          <div className="flex justify-between items-center border-b border-slate-100 pb-3">
                            <span className="text-slate-500 text-sm">Phone</span>
                            <span className="font-semibold text-slate-700">{selectedEmployeeForDetail.phone || 'N/A'}</span>
                          </div>
                          <div className="flex justify-between items-center border-b border-slate-100 pb-3">
                            <span className="text-slate-500 text-sm">Daily Wage</span>
                            <span className="font-semibold text-slate-700">₹{selectedEmployeeForDetail.daily_wage || 0}</span>
                          </div>
                        </>
                      );
                    })()}
                    <div className="mt-4 pt-4 border-t border-slate-100">
                      <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Student Login Credentials</h4>
                      <div className="space-y-3">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500 text-sm">Student ID (Username)</span>
                          <span className="font-mono font-bold text-blue-700 bg-blue-100 px-3 py-1 rounded border border-blue-200 shadow-sm">
                            {selectedEmployeeForDetail.student_username || '-'}
                          </span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500 text-sm">Password (Visible)</span>
                          <span className="font-mono font-bold text-amber-700 bg-amber-100 px-3 py-1 rounded border border-amber-200 shadow-sm">
                            {selectedEmployeeForDetail.password_plain || '-'}
                          </span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500 text-sm">Mobile Number</span>
                          <span className="font-semibold text-slate-700 text-sm">{selectedEmployeeForDetail.phone || '-'}</span>
                        </div>
                      </div>
                    </div>

                    {/* Parent Section */}
                    {selectedEmployeeForDetail.parent_face && (
                      <div className="mt-4 pt-4 border-t border-slate-100">
                        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">Parent/Guardian Face</h4>
                        <div className="flex gap-4 items-center">
                          <div className="w-24 h-24 rounded-xl overflow-hidden bg-slate-100 border border-slate-100 shadow-sm">
                            <img 
                              src={selectedEmployeeForDetail.parent_face.startsWith('data:') ? selectedEmployeeForDetail.parent_face : `data:image/jpeg;base64,${selectedEmployeeForDetail.parent_face}`} 
                              alt="Parent" 
                              className="w-full h-full object-cover" 
                            />
                          </div>
                          <div className="space-y-1">
                            <div className="text-xs text-slate-400 font-bold uppercase tracking-tight">Name</div>
                            <div className="font-bold text-slate-800">{selectedEmployeeForDetail.parent_name || 'N/A'}</div>
                            <div className="text-xs text-slate-400 font-bold uppercase tracking-tight mt-1">Phone</div>
                            <div className="text-sm font-medium text-slate-600">{selectedEmployeeForDetail.parent_phone || 'N/A'}</div>
                          </div>
                        </div>
                      </div>
                    )}

                    <div className="mt-4 pt-4 border-t border-slate-100">
                      <div className="flex justify-between items-center pb-1">
                        <span className="text-slate-500 text-sm">Vendor Name</span>
                        <span className="font-semibold text-slate-700">{selectedVendorForDetail.company_name}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Report Section */}
                <div className="flex-1">
                  <div className="bg-slate-800 text-white rounded-xl p-6 mb-6">
                    <h3 className="text-lg font-bold mb-4 flex justify-between items-center">
                      Performance Report
                    </h3>
                    <div className="flex items-center gap-4 bg-slate-700/50 p-3 rounded-lg border border-slate-600">
                      <div className="flex items-center gap-2">
                        <Calendar size={16} className="text-slate-400" />
                        <input
                          type="date"
                          value={reportDateRange.start}
                          onChange={(e) => {
                            setReportDateRange(prev => ({ ...prev, start: e.target.value }));
                            // Trigger refetch if needed or let user click a button. 
                            // For better UX, we can add a "Update" button or use useEffect.
                            // Since fetch is manual, we'll add an update button.
                          }}
                          className="bg-transparent text-sm text-white focus:outline-none [&::-webkit-calendar-picker-indicator]:invert"
                        />
                      </div>
                      <span className="text-slate-500">-</span>
                      <div className="flex items-center gap-2">
                        <input
                          type="date"
                          value={reportDateRange.end}
                          onChange={(e) => setReportDateRange(prev => ({ ...prev, end: e.target.value }))}
                          className="bg-transparent text-sm text-white focus:outline-none [&::-webkit-calendar-picker-indicator]:invert"
                        />
                      </div>
                      <button
                        onClick={() => fetchEmployeeReport(selectedVendorForDetail.id, selectedEmployeeForDetail)}
                        className="ml-auto bg-indigo-500 hover:bg-indigo-600 text-white text-xs px-3 py-1.5 rounded-md transition-colors font-medium"
                      >
                        Update Report
                      </button>
                    </div>
                  </div>

                  {employeeReport ? (
                    <div className="grid grid-cols-2 gap-4">
                      {selectedVendorForDetail?.vertical === 'school' ? (
                        <>
                          <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                            <div className="text-slate-500 text-sm mb-1">Days Present</div>
                            <div className="text-3xl font-bold text-green-600">
                              {(() => {
                                const att = employeeReport.attendance || [];
                                const days = new Set(att.map(l => new Date((l.timestamp || '').replace(' ', 'T')).toDateString()));
                                return days.size;
                              })()}
                            </div>
                            <div className="text-xs text-slate-400 mt-2">Days with activity</div>
                          </div>
                          <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                            <div className="text-slate-500 text-sm mb-1">Late Marks</div>
                            <div className="text-3xl font-bold text-orange-500">
                              {(() => {
                                const att = employeeReport.attendance || [];
                                return att.filter(l => l.is_late === 1 || l.is_late === true || l.is_late === '1').length;
                              })()}
                            </div>
                            <div className="text-xs text-slate-400 mt-2">Check-ins after grace period</div>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                            <div className="text-slate-500 text-sm mb-1">Total Hours Worked</div>
                            <div className="text-3xl font-bold text-indigo-600">{employeeReport.total_hours_str}</div>
                            <div className="text-xs text-slate-400 mt-2">Recorded duration</div>
                          </div>
                          <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                            <div className="text-slate-500 text-sm mb-1">Days Present</div>
                            <div className="text-3xl font-bold text-green-600">{employeeReport.days_present}</div>
                            <div className="text-xs text-slate-400 mt-2">Days with activity</div>
                          </div>
                          <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                            <div className="text-slate-500 text-sm mb-1">Late Marks</div>
                            <div className="text-3xl font-bold text-orange-500">{employeeReport.late_marks_count}</div>
                            <div className="text-xs text-slate-400 mt-2">Check-ins after grace period</div>
                          </div>
                          <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                            <div className="text-slate-500 text-sm mb-1">Estimated Payout</div>
                            <div className="text-3xl font-bold text-slate-800">₹{employeeReport.final_payout}</div>
                            <div className="text-xs text-slate-400 mt-2">Based on daily wage</div>
                          </div>
                        </>
                      )}
                      <div className="col-span-2 bg-blue-50 p-4 rounded-xl border border-blue-100 mt-2">
                        <div className="flex gap-2 items-start">
                          <div className="p-1 bg-blue-100 rounded text-blue-600 mt-0.5">
                            <Shield size={16} />
                          </div>
                          <div>
                            <h4 className="font-bold text-blue-800 text-sm">Super Admin View</h4>
                            <p className="text-blue-600 text-xs mt-1">
                              This report is generated using the vendor's context. You are seeing exactly what the vendor sees in their dashboard.
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-12 text-center">
                      <div className="animate-spin w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                      <p className="text-slate-500">Generating Report...</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'maintenance' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <div className="flex items-center gap-4 mb-4">
                <div className="p-3 bg-indigo-50 rounded-lg text-indigo-600">
                  <Database size={24} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">Global Data Archival</h3>
                  <p className="text-slate-500 text-sm">Manage storage by moving old records to the backup database.</p>
                </div>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg border border-slate-100">
                  <div>
                    <div className="font-bold text-slate-700">Manual Archive Trigger</div>
                    <div className="text-xs text-slate-500">Force the archival process to run across all vendors now.</div>
                  </div>
                  <button
                    onClick={handleManualArchival}
                    className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                  >
                    <RefreshCw size={16} /> Run Archival
                  </button>
                </div>
                <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg border border-slate-100">
                  <div>
                    <div className="font-bold text-slate-700">Download Backup DB</div>
                    <div className="text-xs text-slate-500">Download the entire backup database file (SQLite format).</div>
                  </div>
                  <button
                    onClick={handleDownloadArchivalBackup}
                    className="flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                  >
                    <Download size={16} /> Download .db
                  </button>
                </div>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <div className="flex items-center gap-4 mb-4">
                <div className="p-3 bg-red-50 rounded-lg text-red-600">
                  <Trash2 size={24} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">Archive Cleanup</h3>
                  <p className="text-slate-500 text-sm">Permanently wipe archived data for specific vendors.</p>
                </div>
              </div>
              <div className="overflow-hidden border border-slate-100 rounded-lg">
                <div className="max-h-[300px] overflow-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-slate-600 sticky top-0 border-b border-slate-100">
                      <tr>
                        <th className="p-3 font-semibold">Vendor</th>
                        <th className="p-3 font-semibold text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {vendors.map(v => (
                        <tr key={v.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50 transition-colors">
                          <td className="p-3 font-medium text-slate-700">{v.company_name}</td>
                          <td className="p-3 text-right">
                            <button
                              onClick={() => handleWipeVendorArchivedData(v.id, v.company_name)}
                              className="text-red-600 hover:text-red-700 font-medium text-xs bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded transition-colors"
                            >
                              Wipe Archive
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <div className="flex items-center gap-4 mb-4">
                <div className="p-3 bg-amber-50 rounded-lg text-amber-600">
                  <Upload size={24} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">Disaster Recovery (Restore)</h3>
                  <p className="text-slate-500 text-sm">Upload a backup SQLite database to merge its data into the primary system.</p>
                </div>
              </div>

              {/* Full System Backup Section */}
              <div className="bg-slate-50 p-4 rounded-lg border border-slate-200 mb-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-indigo-100 rounded-lg text-indigo-600">
                    <Download size={20} />
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-800 text-sm">Full System Backup</h4>
                    <p className="text-slate-500 text-xs">Download a complete copy of all vendors, employees, and settings.</p>
                  </div>
                </div>
                <button
                  onClick={handleDownloadFullBackup}
                  disabled={loading}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors flex items-center gap-2 shadow-sm"
                >
                  <Download size={16} />
                  Download .db
                </button>
              </div>

              <div className="space-y-4">
                <div className="p-4 bg-amber-50 rounded-lg border border-amber-100 mb-2">
                  <div className="flex gap-2">
                    <Shield size={16} className="text-amber-600 mt-1 shrink-0" />
                    <div className="text-xs text-amber-700">
                      <b>Idempotent Merge:</b> This process will add missing records from the backup. Existing records with the same IDs will <b>not</b> be overwritten. This is safe to run multiple times.
                    </div>
                  </div>
                </div>
                <div className="flex flex-col gap-3">
                  <label className="flex flex-col items-center justify-center border-2 border-dashed border-slate-200 rounded-xl p-6 cursor-pointer hover:bg-slate-50 transition-colors text-center">
                    <div className="p-2 bg-slate-100 rounded-full text-slate-500 mb-2">
                      <Upload size={20} />
                    </div>
                    <span className="text-sm font-medium text-slate-700">Click to upload backup .db or .sqlite</span>
                    <span className="text-xs text-slate-400 mt-1">Maximum file size: 500MB</span>
                    <input
                      type="file"
                      accept=".db,.sqlite"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) handleRestoreDatabase(file);
                        e.target.value = ''; // Reset for next selection
                      }}
                    />
                  </label>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex gap-3">
            <Shield className="text-amber-600 mt-0.5" size={20} />
            <div>
              <h4 className="font-bold text-amber-800 text-sm">SuperAdmin Maintenance Notice</h4>
              <p className="text-amber-700 text-xs mt-1">
                Archival happens automatically based on per-vendor retention settings.
                Manual triggers are intended for immediate storage space recovery.
                Wiping data here deletes it permanently from the backup database.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Password Reset Modal */}
      {passwordModal.show && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-sm">
            <h2 className="text-xl font-bold mb-4">Reset Password</h2>
            <p className="text-sm text-slate-500 mb-4">
              Enter new password for <b>{passwordModal.username}</b>
            </p>
            <form onSubmit={handlePasswordReset}>
              <div className="mb-4">
                <input
                  type="password"
                  required
                  placeholder="New Password"
                  className="w-full p-2 border rounded"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                />
              </div>
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setPasswordModal({ show: false, username: '' })}
                  className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700"
                >
                  Update Password
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Invoice Modal */}
      {invoiceModal.show && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-3xl h-[80vh] flex flex-col">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-xl font-bold">Invoices - {invoiceModal.vendor?.company_name}</h2>
              <button
                onClick={handleGenerateInvoice}
                className="bg-green-600 hover:bg-green-700 text-white px-3 py-1.5 rounded text-sm flex items-center gap-2"
              >
                <Plus size={16} /> Generate Invoice
              </button>
            </div>

            <div className="flex-1 overflow-auto">
              <table className="w-full text-left">
                <thead className="bg-slate-50 sticky top-0">
                  <tr>
                    <th className="p-3 font-semibold text-slate-600">Date</th>
                    <th className="p-3 font-semibold text-slate-600">Amount</th>
                    <th className="p-3 font-semibold text-slate-600">Status</th>
                    <th className="p-3 font-semibold text-slate-600">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {invoiceModal.invoices.length === 0 ? (
                    <tr><td colSpan="4" className="p-4 text-center text-slate-500">No invoices found</td></tr>
                  ) : (
                    invoiceModal.invoices.map(inv => (
                      <tr key={inv.id} className="border-b border-slate-100">
                        <td className="p-3">{inv.invoice_date}</td>
                        <td className="p-3">
                          <div className="font-medium">₹{inv.amount}</div>
                          {inv.details && (
                            <div className="mt-1">
                              <div className="text-xs text-slate-500">Breakdown</div>
                              <div className="text-xs">
                                {(() => {
                                  try {
                                    const details = typeof inv.details === 'string' ? JSON.parse(inv.details) : inv.details;
                                    return (
                                      <div className="flex flex-col gap-1 mt-1">
                                        {(details.active_users > 0 || details.max_devices > 0) && (
                                          <span className="bg-slate-100 px-1 rounded">
                                            Devs: {details.active_users || details.max_devices} x ₹{details.cost_per_user || details.cost_per_device}
                                          </span>
                                        )}
                                        {details.max_employees > 0 && (
                                          <span className="bg-slate-100 px-1 rounded">
                                            Emps: {details.max_employees} x ₹{details.cost_per_employee}
                                          </span>
                                        )}
                                      </div>
                                    );
                                  } catch (e) { return '-'; }
                                })()}
                              </div>
                            </div>
                          )}
                        </td>
                        <td className="p-3">
                          <span className={`px-2 py-1 rounded text-xs font-bold ${inv.status === 'paid' ? 'bg-green-100 text-green-700' :
                            inv.status === 'overdue' ? 'bg-red-100 text-red-700' :
                              'bg-yellow-100 text-yellow-700'
                            }`}>
                            {inv.status.toUpperCase()}
                          </span>
                        </td>
                        <td className="p-3">
                          {inv.status !== 'paid' && (
                            <button
                              onClick={() => handleMarkPaid(inv.id)}
                              className="text-xs bg-blue-50 text-blue-600 hover:bg-blue-100 px-2 py-1 rounded"
                            >
                              Mark Paid
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex justify-end mt-4 pt-4 border-t">
              <button
                onClick={() => setInvoiceModal({ show: false, vendor: null, invoices: [] })}
                className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-xl font-bold mb-6">{editingVendor ? 'Edit Vendor Details' : 'Onboard New Vendor'}</h2>
            <form onSubmit={handleCreateVendor}>

              {/* Section 1: Company Details */}
              <div className="mb-6">
                <h3 className="text-sm uppercase tracking-wide text-slate-500 font-bold mb-3 flex items-center gap-2">
                  <Shield size={16} /> Company Details
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Company Name *</label>
                    <input
                      type="text"
                      required
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none"
                      value={newVendor.company_name}
                      onChange={e => setNewVendor({ ...newVendor, company_name: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Contact Person</label>
                    <input
                      type="text"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none"
                      value={newVendor.contact_person}
                      onChange={e => setNewVendor({ ...newVendor, contact_person: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Phone</label>
                    <input
                      type="text"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none"
                      value={newVendor.phone}
                      onChange={e => setNewVendor({ ...newVendor, phone: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Email</label>
                    <input
                      type="email"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none"
                      value={newVendor.email}
                      onChange={e => setNewVendor({ ...newVendor, email: e.target.value })}
                    />
                  </div>
                </div>
                <div className="mt-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">Business Vertical *</label>
                  <select
                    className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none bg-white"
                    value={newVendor.vertical}
                    onChange={e => {
                      const v = e.target.value;
                      const bt = businessTypes.find(x => x.value === v);
                      let bundleId = bt?.default_frontend_bundle_id || newVendor.frontend_bundle_id || 'default_attendance';
                      const presetFeatures = bundleConfig[bundleId] || [];
                      
                      // Auto-populate registration fields if available for this vertical
                      const presetReg = bt?.default_registration_config?.length 
                        ? [...bt.default_registration_config] 
                        : registrationConfig;
                      
                      setRegistrationConfig(presetReg);
                      setNewVendor({
                        ...newVendor,
                        vertical: v,
                        frontend_bundle_id: bundleId,
                        features: presetFeatures
                      });
                    }}
                  >
                    <option value="">Select Business</option>
                    {businessTypes.map(bt => (
                      <option key={bt.value} value={bt.value}>{bt.label}</option>
                    ))}
                  </select>
                </div>
                <div className="mt-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">Attendance Calculation Method</label>
                  <select
                    className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none bg-white"
                    value={newVendor.attendance_type}
                    onChange={e => setNewVendor({ ...newVendor, attendance_type: e.target.value })}
                  >
                    <option value="total_time">Total Time (Sum of all Check-ins/Check-outs)</option>
                    <option value="first_last">First Check-in & Last Check-out (Full day span)</option>
                  </select>
                  <p className="text-xs text-slate-500 mt-1 italic">
                    * Total Time: Sums duration of valid sessions. First-Last: Calculates span from earliest check-in to latest check-out.
                  </p>
                </div>
              </div>

              {/* Section 2: Plan Configuration */}
              <div className="mb-6 bg-blue-50 p-4 rounded-lg border border-blue-100">
                <h3 className="text-sm uppercase tracking-wide text-blue-700 font-bold mb-3 flex items-center gap-2">
                  <Calendar size={16} /> Subscription Plan
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Start Date</label>
                    <input
                      type="date"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.start_date}
                      onChange={e => setNewVendor({ ...newVendor, start_date: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">End Date</label>
                    <input
                      type="date"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.end_date}
                      onChange={e => setNewVendor({ ...newVendor, end_date: e.target.value })}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-1">Cost Per Device (₹)</label>
                      <input
                        name="cost_per_user"
                        value={newVendor.cost_per_user}
                        onChange={e => setNewVendor({ ...newVendor, cost_per_user: e.target.value })}
                        placeholder="e.g. 200"
                        className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                        type="number"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-1">Cost Per Employee (₹)</label>
                      <input
                        name="cost_per_employee"
                        value={newVendor.cost_per_employee}
                        onChange={e => setNewVendor({ ...newVendor, cost_per_employee: e.target.value })}
                        placeholder="e.g. 120"
                        className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                        type="number"
                      />
                    </div>
                  </div>
                  <div className="text-xs text-slate-500 mt-1 mb-2 italic">
                    * Recommended Pricing: ₹120/Employee, ₹200/Device
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">
                      Max Phones (Devices)
                      {serverSubEcho && (
                        <span className="ml-2 text-xs text-slate-500">(Saved: {serverSubEcho.max_mobile_devices ?? serverSubEcho.max_users})</span>
                      )}
                    </label>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.max_users}
                      ref={maxUsersRef}
                      onChange={e => setNewVendor({ ...newVendor, max_users: e.target.value })}
                      placeholder="Default: 5"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">
                      Max Employees
                      {serverSubEcho && (
                        <span className="ml-2 text-xs text-slate-500">(Saved: {serverSubEcho.max_employees})</span>
                      )}
                    </label>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.max_employees}
                      ref={maxEmployeesRef}
                      onChange={e => setNewVendor({ ...newVendor, max_employees: e.target.value })}
                      placeholder="Default: 50"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">
                      Max Admin Web Sessions
                      {serverSubEcho && (
                        <span className="ml-2 text-xs text-slate-500">(Saved: {serverSubEcho.max_web_sessions})</span>
                      )}
                    </label>
                    <input
                      type="number"
                      step="1"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.max_web_sessions}
                      ref={maxWebSessionsRef}
                      onChange={e => setNewVendor({ ...newVendor, max_web_sessions: e.target.value })}
                      min="1"
                      placeholder="Default: 1"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Registration Template</label>
                    <select
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.registration_template || ''}
                      onChange={e => {
                        const key = e.target.value;
                        setNewVendor({ ...newVendor, registration_template: key });
                        if (key && registrationTemplates && registrationTemplates[key]) {
                          setRegistrationConfig(registrationTemplates[key]);
                        } else if (!key) {
                          setRegistrationConfig([]);
                        }
                      }}
                    >
                      <option value="">None</option>
                      {Object.keys(registrationTemplates).map(key => (
                        <option key={key} value={key}>{key}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Data Retention (Days)</label>
                    <input
                      type="number"
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.retention_days}
                      onChange={e => setNewVendor({ ...newVendor, retention_days: e.target.value })}
                      placeholder="e.g. 90"
                    />
                    <p className="text-[10px] text-slate-400 mt-1 italic">
                      * Data older than this will be moved to backup DB & deleted from primary.
                    </p>
                  </div>
                </div>
              </div>

              {/* Section: Architecture Config */}
              <div className="mb-6">
                <h3 className="text-sm uppercase tracking-wide text-slate-500 font-bold mb-3 flex items-center gap-2">
                  <Settings size={16} /> Architecture Config
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Frontend Bundle</label>
                    <select
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none bg-white"
                      value={newVendor.frontend_bundle_id}
                      onChange={e => {
                        const bundleId = e.target.value;
                        setNewVendor({
                          ...newVendor,
                          frontend_bundle_id: bundleId,
                          features: bundleConfig[bundleId] || []
                        });
                      }}
                    >
                      {Object.keys(FRONTEND_BUNDLES).map(bundleId => (
                        <option key={bundleId} value={bundleId}>
                          {bundleId.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Backend Service</label>
                    <select
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none bg-white"
                      value={newVendor.backend_service_id}
                      onChange={e => setNewVendor({ ...newVendor, backend_service_id: e.target.value })}
                    >
                      <option value="default_api">Default API Service</option>
                      <option value="high_performance_api">High Performance API</option>
                      <option value="dedicated_db_api">Dedicated DB API</option>
                    </select>
                  </div>
                </div>

                {/* Features Selection */}
                <div className="mt-4 border-t pt-4">
                  <label className="block text-sm font-medium text-slate-700 mb-2">Enabled Features (Multi-Select)</label>
                  <div className="grid grid-cols-2 gap-2">
                    {availableFeatures.map(feature => (
                      <label key={feature} className="flex items-center gap-2 p-2 border rounded cursor-pointer hover:bg-slate-50 transition-all">
                        <input
                          type="checkbox"
                          checked={newVendor.features?.includes(feature)}
                          onChange={e => {
                            const checked = e.target.checked;
                            setNewVendor(prev => {
                              let newFeatures = checked
                                ? [...(prev.features || []), feature]
                                : (prev.features || []).filter(f => f !== feature);

                              // Auto-enable dependencies
                              if (checked) {
                                if (feature === 'payroll') {
                                  if (!newFeatures.includes('report_payroll')) newFeatures.push('report_payroll');
                                  if (!newFeatures.includes('reports')) newFeatures.push('reports');
                                }
                                if (feature === 'report_payroll' || feature === 'report_detailed') {
                                  if (!newFeatures.includes('reports')) newFeatures.push('reports');
                                }

                                // New Feature Dependencies
                                if (feature === 'payable_hours') {
                                  if (!newFeatures.includes('payroll')) newFeatures.push('payroll');
                                  if (!newFeatures.includes('report_payroll')) newFeatures.push('report_payroll');
                                  if (!newFeatures.includes('reports')) newFeatures.push('reports');
                                }

                                if (feature === 'night_shift_logic' || feature === 'add_shift') {
                                  if (!newFeatures.includes('shifts')) newFeatures.push('shifts');
                                }

                                // Additional Feature Dependencies
                                if (feature === 'geofencing') {
                                  if (!newFeatures.includes('mobile_app')) newFeatures.push('mobile_app');
                                }

                                if (feature === 'whatsapp_alerts') {
                                  if (!newFeatures.includes('reports')) newFeatures.push('reports');
                                }
                              }
                              return { ...prev, features: newFeatures };
                            });
                          }}
                          className="rounded text-indigo-600 focus:ring-indigo-500"
                        />
                        <span className="text-sm capitalize flex-1">{feature.replace('_', ' ')}</span>
                        {feature === 'leave_management' && newVendor.features?.includes('leave_management') && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              if (editingVendor) {
                                handleOpenLeaveConfig(editingVendor);
                              } else {
                                alert("Please save the vendor first before configuring leave management.");
                              }
                            }}
                            className={`ml-auto text-[10px] px-2 py-1 rounded transition-colors flex items-center gap-1.5 shadow-sm ${
                              editingVendor 
                                ? "bg-indigo-600 text-white hover:bg-indigo-700" 
                                : "bg-slate-200 text-slate-500 cursor-not-allowed"
                            }`}
                            title={editingVendor ? "Configure Leave Management" : "Save vendor first to configure"}
                          >
                            <Settings size={12} />
                            <span className="font-bold">CONFIG</span>
                          </button>
                        )}
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              {/* Registration Configuration */}
              <RegistrationConfigEditor
                config={registrationConfig}
                onChange={setRegistrationConfig}
              />

              <div className="h-6"></div>

              {/* Section 3: Login Credentials */}
              <div className="mb-6">
                <h3 className="text-sm uppercase tracking-wide text-slate-500 font-bold mb-3 flex items-center gap-2">
                  <Lock size={16} /> Login Credentials
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="border p-3 rounded-lg bg-slate-50">
                    <div className="text-xs font-bold text-slate-500 mb-2 uppercase">Admin Login</div>
                    <div className="space-y-2">
                      <input
                        type="text"
                        placeholder="Username (Default: admin_ID)"
                        className="w-full p-2 border rounded text-sm"
                        value={newVendor.admin_username}
                        onChange={e => setNewVendor({ ...newVendor, admin_username: e.target.value })}
                      />
                      <input
                        type="text"
                        placeholder={editingVendor ? "New Password (Leave blank to keep)" : "Password (Default: default123)"}
                        className="w-full p-2 border rounded text-sm"
                        value={newVendor.admin_password}
                        onChange={e => setNewVendor({ ...newVendor, admin_password: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="border p-3 rounded-lg bg-slate-50">
                    <div className="text-xs font-bold text-slate-500 mb-2 uppercase">User/Kiosk Login</div>
                    <div className="space-y-2">
                      <input
                        type="text"
                        placeholder="Username (Default: user_ID)"
                        className="w-full p-2 border rounded text-sm"
                        value={newVendor.user_username}
                        onChange={e => setNewVendor({ ...newVendor, user_username: e.target.value })}
                      />
                      <input
                        type="text"
                        placeholder={editingVendor ? "New Password (Leave blank to keep)" : "Password (Default: user123)"}
                        className="w-full p-2 border rounded text-sm"
                        value={newVendor.user_password}
                        onChange={e => setNewVendor({ ...newVendor, user_password: e.target.value })}
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t">
                <button
                  type="button"
                  onClick={() => {
                    setShowModal(false);
                    setEditingVendor(null);
                    setNewVendor({
                      company_name: '', contact_person: '', phone: '', email: '',
                      start_date: '', end_date: '', cost: '', max_users: '',
                      admin_username: '', admin_password: '',
                      user_username: '', user_password: '',
                      vertical: '',
                      frontend_bundle_id: 'default_attendance',
                      backend_service_id: 'default_api',
                      features: [],
                      attendance_type: 'total_time',
                      retention_days: '90'
                    });
                  }}
                  className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-6 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 font-medium"
                >
                  {editingVendor ? 'Update Vendor' : 'Create Vendor'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Leave Management Configuration Modal */}
      {showLeaveConfigModal && editingVendor && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-[60]">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col border border-slate-200 animate-in fade-in zoom-in duration-200">
            {/* Modal Header */}
            <div className="p-6 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <div>
                <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                  <Shield size={20} className="text-blue-600" />
                  Leave Management Configuration
                </h2>
                <p className="text-sm text-slate-500 mt-0.5">Setup departments and assigning staff for {editingVendor.company_name}</p>
              </div>
              <button 
                onClick={() => {
                  setShowLeaveConfigModal(false);
                  setNewStaff({ name: '', role: 'rector', pin: '', department: '' });
                  setNewDept('');
                }}
                className="p-2 hover:bg-slate-200 rounded-full text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto p-8 grid grid-cols-1 lg:grid-cols-2 gap-8 bg-white">
              {/* Left Column: Departments */}
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                    <Layers size={18} className="text-indigo-600" />
                    Department Registry
                  </h3>
                  <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-1 rounded-full font-bold">
                    {leaveDepts.length} Departments
                  </span>
                </div>
                
                <div className="flex gap-2 p-1 bg-slate-50 rounded-xl border border-slate-100 shadow-sm focus-within:ring-2 focus-within:ring-indigo-500/20 transition-all">
                  <input
                    type="text"
                    placeholder="Class name (e.g. 10th A, CSE 1)"
                    className="flex-1 bg-transparent border-none focus:ring-0 text-sm px-3 outline-none"
                    value={newDept}
                    onChange={(e) => setNewDept(e.target.value)}
                  />
                  <button 
                    onClick={() => handleAddDept(editingVendor.id)}
                    className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-indigo-700 transition-colors shadow-sm"
                  >
                    Add
                  </button>
                </div>

                <div className="grid grid-cols-1 gap-2">
                  {leaveDepts.length === 0 ? (
                    <div className="text-center py-12 border-2 border-dashed border-slate-100 rounded-2xl text-slate-400">
                      <p className="text-sm">No departments registered yet.</p>
                    </div>
                  ) : (
                    leaveDepts.map((dept, idx) => (
                      <div key={idx} className="flex items-center justify-between p-3 bg-white border border-slate-100 rounded-xl hover:shadow-md transition-shadow group">
                        <span className="font-medium text-slate-700">{dept}</span>
                        <button 
                          onClick={() => handleDeleteDept(editingVendor.id, dept)}
                          className="p-1.5 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-md transition-all opacity-0 group-hover:opacity-100"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Right Column: Staff Members */}
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                    <Users size={18} className="text-emerald-600" />
                    Leave Staff (Rector/HOD)
                  </h3>
                  <span className="text-xs bg-emerald-50 text-emerald-700 px-2 py-1 rounded-full font-bold">
                    {leaveStaff.length} Members
                  </span>
                </div>

                <div className="bg-slate-50 p-6 rounded-2xl border border-slate-100 space-y-4 shadow-inner">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-[10px] uppercase font-bold text-slate-400 mb-1 ml-1">Staff Name</label>
                      <input 
                        type="text" 
                        placeholder="Full Name" 
                        className="w-full p-2.5 bg-white border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all shadow-sm"
                        value={newStaff.name}
                        onChange={e => setNewStaff({ ...newStaff, name: e.target.value })}
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] uppercase font-bold text-slate-400 mb-1 ml-1">Role</label>
                      <select 
                        className="w-full p-2.5 bg-white border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all shadow-sm"
                        value={newStaff.role}
                        onChange={e => setNewStaff({ ...newStaff, role: e.target.value })}
                      >
                        <option value="rector">Rector</option>
                        <option value="hod">HOD</option>
                      </select>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-[10px] uppercase font-bold text-slate-400 mb-1 ml-1">PIN Code (4 digits)</label>
                      <input 
                        type="text" 
                        maxLength={4}
                        placeholder="e.g. 1234" 
                        className="w-full p-2.5 bg-white border border-slate-200 rounded-xl text-sm font-mono tracking-widest focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all shadow-sm"
                        value={newStaff.pin}
                        onChange={e => setNewStaff({ ...newStaff, pin: e.target.value.replace(/\D/g, '') })}
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] uppercase font-bold text-slate-400 mb-1 ml-1">Department (HOD Only)</label>
                      <select 
                        className="w-full p-2.5 bg-white border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all shadow-sm disabled:opacity-50"
                        value={newStaff.department}
                        disabled={newStaff.role !== 'hod'}
                        onChange={e => setNewStaff({ ...newStaff, department: e.target.value })}
                      >
                        <option value="">Select Department</option>
                        {leaveDepts.map((d, i) => (
                          <option key={i} value={d}>{d}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <button 
                    onClick={() => handleCreateStaff(editingVendor.id)}
                    className="w-full bg-emerald-600 text-white py-3 rounded-xl text-sm font-bold hover:bg-emerald-700 transition-all shadow-md shadow-emerald-600/20 flex items-center justify-center gap-2"
                  >
                    <Plus size={18} />
                    Register Staff Member
                  </button>
                </div>

                <div className="grid grid-cols-1 gap-3 overflow-y-auto max-h-[300px] pr-2">
                  {leaveStaff.length === 0 ? (
                    <div className="text-center py-12 border-2 border-dashed border-slate-100 rounded-2xl text-slate-400">
                      <p className="text-sm">No rectors or Hods registered yet.</p>
                    </div>
                  ) : (
                    leaveStaff.map(staff => (
                      <div key={staff.id} className="flex items-center justify-between p-4 bg-white border border-slate-100 rounded-2xl shadow-sm hover:shadow-md transition-all group">
                        <div className="flex items-center gap-3">
                          <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold ${staff.role === 'rector' ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'}`}>
                            {staff.name.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <p className="font-bold text-slate-800 text-sm">{staff.name}</p>
                            <p className="text-[10px] text-slate-500 uppercase font-medium">
                              {staff.role} {staff.department ? `• ${staff.department}` : ''}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-4">
                          <div className="text-right">
                            <p className="text-[10px] text-slate-400 font-bold uppercase">PIN Code</p>
                            <p className="font-mono font-bold text-slate-800 tracking-widest">{staff.pin}</p>
                          </div>
                          <button 
                            onClick={() => handleDeleteStaff(editingVendor.id, staff.id)}
                            className="p-2 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* Bottom Section: Student Web Logins */}
            <div className="p-8 border-t border-slate-100 bg-slate-50/10">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                    <User className="text-blue-600" size={18} />
                    Student Web Logins
                  </h3>
                  <p className="text-xs text-slate-500 mt-1">Review student account credentials and password status</p>
                </div>
                <button 
                  onClick={() => fetchLeaveStudents(editingVendor.id)}
                  className="p-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 transition-all shadow-sm"
                  title="Refresh List"
                >
                  <RefreshCw size={16} />
                </button>
              </div>

              {leaveStudents.length === 0 ? (
                <div className="bg-white p-12 text-center rounded-3xl border-2 border-dashed border-slate-200 text-slate-400">
                  <User size={48} className="mx-auto mb-3 opacity-20" />
                  <p className="font-medium">No student logins found for this vendor.</p>
                  <p className="text-xs mt-1">Students are added automatically on login.</p>
                </div>
              ) : (
                <div className="overflow-hidden bg-white rounded-2xl border border-slate-200 shadow-sm">
                  <div className="overflow-x-auto max-h-[300px]">
                    <table className="w-full text-left border-collapse sticky-header">
                      <thead className="sticky top-0 bg-slate-50 text-slate-500 z-10">
                        <tr className="border-b border-slate-100">
                          <th className="p-4 text-[10px] font-bold uppercase">Student Name</th>
                          <th className="p-4 text-[10px] font-bold uppercase">Username (ID)</th>
                          <th className="p-4 text-[10px] font-bold uppercase">Phone (Initial Pass)</th>
                          <th className="p-4 text-[10px] font-bold uppercase">Status</th>
                          <th className="p-4 text-[10px] font-bold uppercase">Current Pass (Plain)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-50">
                        {leaveStudents.map((stu, i) => (
                          <tr key={i} className="hover:bg-slate-50/50 transition-colors">
                            <td className="p-4">
                              <p className="text-sm font-bold text-slate-800">{stu.name}</p>
                            </td>
                            <td className="p-4">
                              <span className="text-xs font-mono bg-slate-100 text-slate-700 px-2 py-1 rounded">
                                {stu.student_id}
                              </span>
                            </td>
                            <td className="p-4 text-sm text-slate-600">{stu.phone || 'N/A'}</td>
                            <td className="p-4">
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                                stu.status === 'Changed' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
                              }`}>
                                {stu.status.toUpperCase()}
                              </span>
                            </td>
                            <td className="p-4 text-sm font-mono text-slate-500">{stu.password_plain}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-6 border-t border-slate-100 bg-slate-50/50 flex justify-end">
              <button 
                onClick={() => {
                  setShowLeaveConfigModal(false);
                  setNewStaff({ name: '', role: 'rector', pin: '', department: '' });
                  setNewDept('');
                }}
                className="bg-slate-900 text-white px-8 py-3 rounded-xl font-bold hover:bg-black transition-all shadow-lg shadow-slate-200"
              >
                Close & Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const StatCard = ({ label, value, icon, color }) => (
  <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
    <div className="p-3 bg-slate-50 rounded-lg">{icon}</div>
    <div>
      <div className="text-slate-500 text-sm font-medium">{label}</div>
      <div className={`text-2xl font-bold ${color || 'text-slate-800'}`}>{value}</div>
    </div>
  </div>
);

const StatusBadge = ({ status }) => {
  const styles = {
    active: 'bg-green-100 text-green-700 border-green-200',
    suspended: 'bg-red-100 text-red-700 border-red-200',
    expired: 'bg-orange-100 text-orange-700 border-orange-200'
  };

  return (
    <span className={`px-2 py-1 rounded-full text-xs font-semibold border capitalize ${styles[status] || styles.active}`}>
      {status}
    </span>
  );
};

export default SuperAdminDashboard;
