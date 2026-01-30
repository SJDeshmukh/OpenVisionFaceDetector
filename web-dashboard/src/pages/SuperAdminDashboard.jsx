import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Check, X, Shield, User, Lock, DollarSign, Calendar, Pencil, ToggleLeft, ToggleRight, Search, Filter, ArrowLeft, ArrowRight, Eye, Settings } from 'lucide-react';
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
    admin_username: '', admin_password: '',
    user_username: '', user_password: '',
    frontend_bundle_id: 'default_attendance',
    backend_service_id: 'default_api',
    features: []
  });
  const [registrationConfig, setRegistrationConfig] = useState([]);
  const [editingVendor, setEditingVendor] = useState(null);
  
  // Features Config
  const [availableFeatures, setAvailableFeatures] = useState([]);
  const [bundleConfig, setBundleConfig] = useState({});

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

  // --- New Tab & Details State ---
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'vendor_details'
  const [detailViewMode, setDetailViewMode] = useState('list'); // 'list' | 'vendor' | 'employee'
  const [selectedVendorForDetail, setSelectedVendorForDetail] = useState(null);
  const [vendorEmployees, setVendorEmployees] = useState([]);
  const [selectedEmployeeForDetail, setSelectedEmployeeForDetail] = useState(null);
  const [employeeReport, setEmployeeReport] = useState(null);
  const [reportDateRange, setReportDateRange] = useState({
    start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
    end: new Date().toISOString().split('T')[0]
  });

  const { socket, joinSuperAdmin } = useSocket();
  useEffect(() => {
    fetchVendors();
    fetchFeatures();
    fetchStats();

    socket.on('connect', () => {
        joinSuperAdmin();
    });

    socket.on('vendor_updated', (data) => {
        console.log("Vendor Updated:", data);
        fetchVendors(); // Refresh vendor list (limits, usage)
        fetchStats(); // Refresh global stats
    });

    socket.on('active_devices_update', (data) => {
        console.log("Active Devices Update:", data);
        setStats(prev => ({
            ...prev,
            active_streaming_devices: data.count
        }));
    });

    socket.on('device_heartbeat', (data) => {
         // Optional: Toast notification or just rely on periodic stats update
         // console.log("Device Heartbeat:", data);
    });

    return () => {
        socket.off('vendor_updated');
        socket.off('active_devices_update');
        socket.off('device_heartbeat');
    };
  }, [socket]);
  
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
  
  const fetchFeatures = async () => {
    try {
        const response = await axios.get(`${API_URL}/admin/features`, {
            headers: { Authorization: `Bearer ${user?.token}` }
        });
        setAvailableFeatures(response.data.features || []);
        setBundleConfig(response.data.bundles || {});
    } catch (error) {
        console.error("Error fetching features:", error);
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
      if (editingVendor) {
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
            backend_service_id: newVendor.backend_service_id
        }, {
            headers: { Authorization: `Bearer ${user?.token}` }
        });

        await axios.put(`${API_URL}/admin/vendors/${editingVendor.id}/subscription`, {
            start_date: newVendor.start_date,
            end_date: newVendor.end_date,
            cost_per_user: newVendor.cost_per_user,
            cost_per_employee: newVendor.cost_per_employee,
            max_users: newVendor.max_users,
            max_employees: newVendor.max_employees,
            plan_type: 'custom',
            features: newVendor.features
        }, {
            headers: { Authorization: `Bearer ${user?.token}` }
        });

        // Save Registration Config
        await axios.put(`${API_URL}/admin/vendors/${editingVendor.id}/registration-config`, {
            config: registrationConfig
        }, {
            headers: { Authorization: `Bearer ${user?.token}` }
        });

        alert("Vendor Updated Successfully!");
      } else {
        // Create Mode
        const response = await axios.post(`${API_URL}/admin/vendors`, { 
            ...newVendor, 
            max_users: newVendor.max_users || 5,
            max_employees: newVendor.max_employees || 50
        }, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });

        const newVendorId = response.data.vendor_id;
        
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
        admin_username: '', admin_password: '',
        user_username: '', user_password: '',
        features: []
      });
      setRegistrationConfig([]);
      fetchVendors();
    } catch (error) {
      alert("Error: " + (error.response?.data?.error || error.message));
    }
  };

  const handleEditClick = async (vendor) => {
    setEditingVendor(vendor);
    setNewVendor({
      company_name: vendor.company_name || '',
      contact_person: vendor.contact_person || '',
      phone: vendor.phone || '',
      email: vendor.email || '',
      start_date: vendor.start_date || '',
      end_date: vendor.end_date ? vendor.end_date.split(' ')[0] : '',
      cost_per_user: vendor.cost_per_user || '',
      cost_per_employee: vendor.cost_per_employee || '',
      max_users: vendor.max_users || '',
      max_employees: vendor.max_employees || '',
      admin_username: vendor.admin_username || '',
      admin_password: '', // Keep blank
      user_username: vendor.user_username || '',
      user_password: '',   // Keep blank
      frontend_bundle_id: vendor.frontend_bundle_id || 'default_attendance',
      backend_service_id: vendor.backend_service_id || 'default_api',
      features: vendor.features || []
    });

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
    today.setHours(0,0,0,0);
    end.setHours(0,0,0,0);
    const diffTime = end - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); 
    return diffDays;
  };

  // --- New Helper Functions for Vendor Details Tab ---
  const fetchVendorEmployees = async (vendorId) => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_URL}/persons`, {
        headers: { 
            Authorization: `Bearer ${user?.token}`,
            'X-Vendor-ID': vendorId
        }
      });
      setVendorEmployees(response.data.persons);
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
      const response = await axios.get(`${API_URL}/reports/payroll`, {
        params: {
            start_date: reportDateRange.start,
            end_date: reportDateRange.end
        },
        headers: { 
            Authorization: `Bearer ${user?.token}`,
            'X-Vendor-ID': vendorId
        }
      });
      
      const report = response.data.payroll.find(p => p.name === employee.name);
      setEmployeeReport(report);
      setSelectedEmployeeForDetail(employee);
      setDetailViewMode('employee');
    } catch (error) {
       console.error(error);
       alert("Error fetching report");
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
          <button 
            onClick={() => {
              setEditingVendor(null);
              setNewVendor({ 
                company_name: '', contact_person: '', phone: '', email: '',
                start_date: '', end_date: '', cost: '', max_users: '',
                admin_username: '', admin_password: '',
                user_username: '', user_password: ''
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
      </div>

      {activeTab === 'overview' && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
            <StatCard label="Total Vendors" value={stats.total_vendors} icon={<Shield className="text-blue-600" size={24} />} />
            <StatCard label="Active Vendors" value={stats.active_vendors} icon={<Check className="text-green-600" size={24} />} />
            <StatCard label="Total Employees" value={stats.total_employees} icon={<User className="text-purple-600" size={24} />} />
            <StatCard label="Active Devices" value={stats.active_streaming_devices} icon={<ToggleLeft className="text-orange-600" size={24} />} />
            <StatCard label="Monthly Revenue" value={`₹${(stats.monthly_recurring_revenue || 0).toLocaleString()}`} icon={<DollarSign className="text-emerald-600" size={24} />} />
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
        <table className="w-full text-left">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
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
                                <span className={`font-mono font-bold ${(vendor.device_count || 0) > (vendor.max_users || 0) ? 'text-red-600' : 'text-slate-700'}`}>
                                    {vendor.device_count || 0} / {vendor.max_users || '∞'}
                                </span>
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
                         {vendor.web_login_enabled !== 0 ? <ToggleRight className="text-green-500" size={20}/> : <ToggleLeft className="text-slate-400" size={20}/>}
                      </div>
                   </div>
                </td>
                <td className="p-4">
                  <div className="flex gap-2">
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
                        onClick={() => { setSelectedVendorForDetail(vendor); fetchVendorEmployees(vendor.id); }}
                        className="p-5 border border-slate-200 rounded-xl cursor-pointer hover:border-indigo-500 hover:shadow-md transition-all group bg-white"
                   >
                     <div className="flex items-start gap-4 mb-3">
                        <div className="w-12 h-12 rounded-full bg-indigo-50 flex items-center justify-center text-indigo-600 font-bold text-lg border border-indigo-100">
                            {vendor.company_name.substring(0,2).toUpperCase()}
                        </div>
                        <div>
                            <h3 className="font-bold text-slate-800 text-lg group-hover:text-indigo-600 transition-colors">{vendor.company_name}</h3>
                            <p className="text-sm text-slate-500">{vendor.contact_person}</p>
                        </div>
                     </div>
                     <div className="pt-3 border-t border-slate-100 flex justify-between items-center">
                        <span className="text-sm text-slate-500">Employees: <span className="font-semibold text-slate-700">{vendor.employee_count || 0}</span></span>
                        <span className="flex items-center gap-1 text-indigo-600 font-medium text-sm group-hover:translate-x-1 transition-transform">View Details <ArrowRight size={16}/></span>
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
                
                {vendorEmployees.length === 0 ? (
                    <div className="text-center py-12 text-slate-400 bg-slate-50 rounded-xl border border-dashed border-slate-200">
                        No employees found for this vendor.
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6">
                        {vendorEmployees.map(emp => (
                            <div key={emp.id} 
                                onClick={() => fetchEmployeeReport(selectedVendorForDetail.id, emp)}
                                className="bg-white rounded-xl overflow-hidden border border-slate-200 cursor-pointer hover:shadow-lg hover:border-indigo-300 transition-all group"
                            >
                                <div className="h-48 bg-slate-100 w-full overflow-hidden relative">
                                    {emp.face_image ? (
                                        <img src={emp.face_image.startsWith('data:') ? emp.face_image : `data:image/jpeg;base64,${emp.face_image}`} alt={emp.name} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"/>
                                    ) : (
                                        <div className="w-full h-full flex flex-col items-center justify-center text-slate-400">
                                            <User size={48} className="mb-2 opacity-20"/>
                                            <span className="text-xs uppercase tracking-wide">No Photo</span>
                                        </div>
                                    )}
                                    <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center pb-4">
                                        <span className="text-white font-medium text-sm flex items-center gap-2"><Eye size={14}/> View Report</span>
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
                )}
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
                                <img src={selectedEmployeeForDetail.face_image.startsWith('data:') ? selectedEmployeeForDetail.face_image : `data:image/jpeg;base64,${selectedEmployeeForDetail.face_image}`} alt={selectedEmployeeForDetail.name} className="w-full h-full object-cover"/>
                             ) : (
                                <div className="flex items-center justify-center h-full text-slate-400 bg-slate-50">
                                    <User size={64} className="opacity-20"/>
                                </div>
                             )}
                        </div>
                        <h2 className="text-2xl font-bold text-slate-800 mb-1">{selectedEmployeeForDetail.name}</h2>
                        <p className="text-slate-500 mb-6 font-medium">{selectedEmployeeForDetail.designation}</p>
                        
                        <div className="space-y-4">
                            {selectedVendorForDetail.registration_config && selectedVendorForDetail.registration_config.length > 0 ? (
                                selectedVendorForDetail.registration_config
                                    .filter(field => field.enabled !== false)
                                    .map((field, index) => {
                                         const val = (() => {
                                             let custom = {};
                                             try { 
                                                 custom = typeof selectedEmployeeForDetail.custom_data === 'string' 
                                                    ? JSON.parse(selectedEmployeeForDetail.custom_data) 
                                                    : selectedEmployeeForDetail.custom_data || {}; 
                                             } catch(e){}
                                             
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
                            )}
                            <div className="flex justify-between items-center pb-1">
                                <span className="text-slate-500 text-sm">Vendor</span>
                                <span className="font-semibold text-slate-700">{selectedVendorForDetail.company_name}</span>
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
                                    <Calendar size={16} className="text-slate-400"/>
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
                          <span className={`px-2 py-1 rounded text-xs font-bold ${
                            inv.status === 'paid' ? 'bg-green-100 text-green-700' :
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
                      onChange={e => setNewVendor({...newVendor, company_name: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Contact Person</label>
                    <input 
                      type="text" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none"
                      value={newVendor.contact_person}
                      onChange={e => setNewVendor({...newVendor, contact_person: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Phone</label>
                    <input 
                      type="text" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none"
                      value={newVendor.phone}
                      onChange={e => setNewVendor({...newVendor, phone: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Email</label>
                    <input 
                      type="email" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-indigo-500 outline-none"
                      value={newVendor.email}
                      onChange={e => setNewVendor({...newVendor, email: e.target.value})}
                    />
                  </div>
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
                      onChange={e => setNewVendor({...newVendor, start_date: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">End Date</label>
                    <input 
                      type="date" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.end_date}
                      onChange={e => setNewVendor({...newVendor, end_date: e.target.value})}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm font-medium text-slate-700 mb-1">Cost Per Device (₹)</label>
                        <input 
                            name="cost_per_user" 
                            value={newVendor.cost_per_user} 
                            onChange={e => setNewVendor({...newVendor, cost_per_user: e.target.value})} 
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
                            onChange={e => setNewVendor({...newVendor, cost_per_employee: e.target.value})} 
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
                    <label className="block text-sm font-medium text-slate-700 mb-1">Max Phones (Devices)</label>
                    <input 
                      type="number" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.max_users}
                      onChange={e => setNewVendor({...newVendor, max_users: e.target.value})}
                      placeholder="Default: 5"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Max Employees</label>
                    <input 
                      type="number" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.max_employees}
                      onChange={e => setNewVendor({...newVendor, max_employees: e.target.value})}
                      placeholder="Default: 50"
                    />
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
                      onChange={e => setNewVendor({...newVendor, backend_service_id: e.target.value})}
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
                            <label key={feature} className="flex items-center space-x-2 p-2 border rounded cursor-pointer hover:bg-slate-50">
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
                                <span className="text-sm capitalize">{feature.replace('_', ' ')}</span>
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
                        onChange={e => setNewVendor({...newVendor, admin_username: e.target.value})}
                      />
                      <input 
                        type="text" 
                        placeholder={editingVendor ? "New Password (Leave blank to keep)" : "Password (Default: default123)"}
                        className="w-full p-2 border rounded text-sm"
                        value={newVendor.admin_password}
                        onChange={e => setNewVendor({...newVendor, admin_password: e.target.value})}
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
                        onChange={e => setNewVendor({...newVendor, user_username: e.target.value})}
                      />
                      <input 
                        type="text" 
                        placeholder={editingVendor ? "New Password (Leave blank to keep)" : "Password (Default: user123)"}
                        className="w-full p-2 border rounded text-sm"
                        value={newVendor.user_password}
                        onChange={e => setNewVendor({...newVendor, user_password: e.target.value})}
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
                      user_username: '', user_password: ''
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
    </div>
  );
};

const StatCard = ({ label, value, icon }) => (
  <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
    <div className="p-3 bg-slate-50 rounded-lg">{icon}</div>
    <div>
      <div className="text-slate-500 text-sm font-medium">{label}</div>
      <div className="text-2xl font-bold text-slate-800">{value}</div>
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
