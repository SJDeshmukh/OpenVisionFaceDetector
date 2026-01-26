import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Check, X, AlertTriangle, Shield, User, Lock, FileText, DollarSign } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const SuperAdminDashboard = () => {
  const { user } = useAuth();
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [passwordModal, setPasswordModal] = useState({ show: false, username: '' });
  const [invoiceModal, setInvoiceModal] = useState({ show: false, vendor: null, invoices: [] });
  const [newPassword, setNewPassword] = useState('');
  const [newVendor, setNewVendor] = useState({ company_name: '', contact_person: '', phone: '', email: '' });

  useEffect(() => {
    fetchVendors();
  }, []);

  const fetchVendors = async () => {
    try {
      const response = await axios.get('http://127.0.0.1:5001/api/admin/vendors', {
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
    try {
      await axios.post('http://127.0.0.1:5001/api/admin/vendors', newVendor, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      setShowModal(false);
      setNewVendor({ company_name: '', contact_person: '', phone: '', email: '' });
      fetchVendors();
      alert("Vendor Created Successfully!");
    } catch (error) {
      alert("Error: " + (error.response?.data?.error || error.message));
    }
  };

  const handlePasswordReset = async (e) => {
    e.preventDefault();
    try {
      await axios.put('http://127.0.0.1:5001/api/admin/users/password', {
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
      await axios.post(`http://127.0.0.1:5001/api/admin/vendors/${id}/suspend`, { action }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      fetchVendors();
    } catch (error) {
      alert("Error updating status");
    }
  };

  const handleViewInvoices = async (vendor) => {
    try {
      const response = await axios.get(`http://127.0.0.1:5001/api/admin/vendors/${vendor.id}/invoices`, {
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
      const response = await axios.post(`http://127.0.0.1:5001/api/admin/vendors/${invoiceModal.vendor.id}/invoices/generate`, {}, {
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
      await axios.put(`http://127.0.0.1:5001/api/admin/invoices/${invoiceId}/status`, { status: 'paid' }, {
        headers: { Authorization: `Bearer ${user?.token}` }
      });
      handleViewInvoices(invoiceModal.vendor); // Refresh
    } catch (error) {
      alert("Error updating status");
    }
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
            onClick={() => setShowModal(true)}
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

      <div className="bg-white rounded-xl shadow-sm overflow-hidden border border-slate-200">
        <table className="w-full text-left">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="p-4 font-semibold text-slate-600">Company</th>
              <th className="p-4 font-semibold text-slate-600">Contact</th>
              <th className="p-4 font-semibold text-slate-600">Status</th>
              <th className="p-4 font-semibold text-slate-600">Plan</th>
              <th className="p-4 font-semibold text-slate-600">Expiry</th>
              <th className="p-4 font-semibold text-slate-600">Users</th>
              <th className="p-4 font-semibold text-slate-600">Actions</th>
            </tr>
          </thead>
          <tbody>
            {vendors.map(vendor => (
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
                  <span className="capitalize px-2 py-1 bg-blue-50 text-blue-700 rounded text-xs font-medium border border-blue-100">
                    {vendor.plan_type || 'None'}
                  </span>
                </td>
                <td className="p-4 text-slate-600">
                  {vendor.end_date || '-'}
                  {vendor.subscription_status === 'Expired' && (
                    <span className="ml-2 text-xs text-red-500 font-bold">(Exp)</span>
                  )}
                </td>
                <td className="p-4 text-slate-600">
                  {vendor.admin_count || 0} / {vendor.max_users || 0}
                </td>
                <td className="p-4">
                  <div className="flex gap-2">
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
            ))}
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
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">Onboard New Vendor</h2>
            <form onSubmit={handleCreateVendor}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Company Name</label>
                  <input 
                    type="text" 
                    required
                    className="w-full p-2 border rounded"
                    value={newVendor.company_name}
                    onChange={e => setNewVendor({...newVendor, company_name: e.target.value})}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Contact Person</label>
                  <input 
                    type="text" 
                    className="w-full p-2 border rounded"
                    value={newVendor.contact_person}
                    onChange={e => setNewVendor({...newVendor, contact_person: e.target.value})}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Phone</label>
                  <input 
                    type="text" 
                    className="w-full p-2 border rounded"
                    value={newVendor.phone}
                    onChange={e => setNewVendor({...newVendor, phone: e.target.value})}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Email</label>
                  <input 
                    type="email" 
                    className="w-full p-2 border rounded"
                    value={newVendor.email}
                    onChange={e => setNewVendor({...newVendor, email: e.target.value})}
                  />
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <button 
                  type="button" 
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded"
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700"
                >
                  Create & Start Trial
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
