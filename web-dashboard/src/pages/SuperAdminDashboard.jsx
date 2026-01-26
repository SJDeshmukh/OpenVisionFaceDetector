import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Check, X, AlertTriangle, Shield, User, Lock, FileText, DollarSign, Calendar, Pencil, ToggleLeft, ToggleRight, Search, Filter } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';

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
    start_date: '', end_date: '', cost: '', max_users: '',
    admin_username: '', admin_password: '',
    user_username: '', user_password: ''
  });
  const [editingVendor, setEditingVendor] = useState(null);
  
  // Filter States
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [subscriptionFilter, setSubscriptionFilter] = useState('all');

  useEffect(() => {
    fetchVendors();
  }, []);

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
            user_password: newVendor.user_password
        }, {
            headers: { Authorization: `Bearer ${user?.token}` }
        });

        await axios.put(`${API_URL}/admin/vendors/${editingVendor.id}/subscription`, {
            start_date: newVendor.start_date,
            end_date: newVendor.end_date,
            cost_per_user: newVendor.cost,
            max_users: newVendor.max_users,
            plan_type: 'custom'
        }, {
            headers: { Authorization: `Bearer ${user?.token}` }
        });

        alert("Vendor Updated Successfully!");
      } else {
        // Create Mode
        const response = await axios.post(`${API_URL}/admin/vendors`, { ...newVendor, max_users: newVendor.max_users || 100 }, {
          headers: { Authorization: `Bearer ${user?.token}` }
        });
        alert(`Vendor Created!\nAdmin: ${response.data.admin_credentials.username}\nUser: ${response.data.user_credentials.username}`);
      }

      setShowModal(false);
      setEditingVendor(null);
      setNewVendor({ 
        company_name: '', contact_person: '', phone: '', email: '',
        start_date: '', end_date: '', cost: '', max_users: '',
        admin_username: '', admin_password: '',
        user_username: '', user_password: ''
      });
      fetchVendors();
    } catch (error) {
      alert("Error: " + (error.response?.data?.error || error.message));
    }
  };

  const handleEditClick = (vendor) => {
    setEditingVendor(vendor);
    setNewVendor({
      company_name: vendor.company_name || '',
      contact_person: vendor.contact_person || '',
      phone: vendor.phone || '',
      email: vendor.email || '',
      start_date: vendor.start_date || '',
      end_date: vendor.end_date ? vendor.end_date.split(' ')[0] : '',
      cost: vendor.cost_per_user || '',
      max_users: vendor.max_users || '',
      admin_username: vendor.admin_username || '',
      admin_password: '', // Keep blank
      user_username: vendor.user_username || '',
      user_password: ''   // Keep blank
    });
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

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-6 bg-slate-50 min-h-screen">
      <div className="flex justify-between items-center mb-8">
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
              setShowModal(true);
            }}
            className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg flex items-center gap-2"
          >
            <Plus size={18} /> Add New Vendor
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Vendors" value={vendors.length} icon={<Shield className="text-blue-500" />} />
        <StatCard label="Active Subscriptions" value={vendors.filter(v => v.subscription_status === 'Active').length} icon={<Check className="text-green-500" />} />
        <StatCard label="Suspended" value={vendors.filter(v => v.status === 'suspended').length} icon={<X className="text-red-500" />} />
        <StatCard label="Total MRR" value={`₹${vendors.reduce((sum, v) => sum + (v.cost_per_user || 0) * (v.max_users || 0), 0)}`} icon={<span className="text-xl font-bold text-slate-600">₹</span>} />
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
              <th className="p-4 font-semibold text-slate-600">Contact</th>
              <th className="p-4 font-semibold text-slate-600">Status</th>
              <th className="p-4 font-semibold text-slate-600">Plan & Cost</th>
              <th className="p-4 font-semibold text-slate-600">Duration</th>
              <th className="p-4 font-semibold text-slate-600">Logins (Admin/User)</th>
              <th className="p-4 font-semibold text-slate-600">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredVendors.length === 0 ? (
              <tr>
                <td colSpan="7" className="p-8 text-center text-slate-500">
                  No vendors found matching your filters.
                </td>
              </tr>
            ) : (
              filteredVendors.map(vendor => (
              <tr key={vendor.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="p-4 font-medium text-slate-800">{vendor.company_name}</td>
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
                            <div className="text-xs text-slate-500 mt-1">
                              {(() => {
                                try {
                                  const d = JSON.parse(inv.details);
                                  return (
                                    <div className="flex flex-col gap-0.5">
                                      <span>Users: {d.active_users} × ₹{d.cost_per_user}</span>
                                      {d.setup_fee > 0 && <span className="text-orange-600">+ Setup: ₹{d.setup_fee}</span>}
                                    </div>
                                  );
                                } catch (e) { return null; }
                              })()}
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
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Plan Cost (₹)</label>
                    <input 
                      type="number" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.cost}
                      onChange={e => setNewVendor({...newVendor, cost: e.target.value})}
                      placeholder="e.g. 5000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Max Users</label>
                    <input 
                      type="number" 
                      className="w-full p-2 border rounded focus:ring-2 focus:ring-blue-500 outline-none bg-white"
                      value={newVendor.max_users}
                      onChange={e => setNewVendor({...newVendor, max_users: e.target.value})}
                      placeholder="Default: 100"
                    />
                  </div>
                </div>
              </div>

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
