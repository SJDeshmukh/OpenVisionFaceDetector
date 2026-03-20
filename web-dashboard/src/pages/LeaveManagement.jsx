import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';
import { 
  CheckCircle, 
  XCircle, 
  Clock, 
  User, 
  FileText, 
  Calendar, 
  MapPin,
  ShieldCheck,
  Search,
  Users
} from 'lucide-react';

const LeaveManagement = () => {
  const { user, staffSession, loginAsStaff } = useAuth();
  const [activeTab, setActiveTab] = useState('pending');
  const [requests, setRequests] = useState([]);
  const [parents, setParents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [generating, setGenerating] = useState(false);
  const [showPinModal, setShowPinModal] = useState(false);
  const [pin, setPin] = useState('');
  
  const currentRole = staffSession?.role || user?.role;

  // Set default tab based on role once user is available
  useEffect(() => {
    if (user?.role === 'user' && !staffSession) {
      setActiveTab('new_request');
    } else {
      setActiveTab('pending');
    }
  }, [user, staffSession]);
  const [formData, setFormData] = useState({
    leave_type: 'home',
    reason: '',
    start_date: '',
    end_date: '',
    start_time: '10:00',
    end_time: '18:00'
  });

  const handleVerifyPin = async (e) => {
    e.preventDefault();
    const res = await loginAsStaff(pin);
    if (res.success) {
      setShowPinModal(false);
      setPin('');
      setActiveTab('pending');
    } else {
      alert(res.error || "Invalid PIN");
    }
  };

  const fetchData = async () => {
    if (user?.role === 'user' && activeTab !== 'history') return;
    setLoading(true);
    try {
      if (activeTab === 'pending') {
        let url = `${API_URL}/leave/admin/pending?role=${currentRole}`;
        if (staffSession?.department) {
          url += `&department=${encodeURIComponent(staffSession.department)}`;
        }
        const res = await axios.get(url);
        setRequests(res.data.requests || []);
      } else if (activeTab === 'parents') {
        const res = await axios.get(`${API_URL}/leave/parent-faces`);
        setParents(res.data.parents || []);
      } else if (activeTab === 'history' && user?.role === 'user') {
        const res = await axios.get(`${API_URL}/leave/student/history`);
        setRequests(res.data.requests || []);
      }
    } catch (err) {
      console.error("Error fetching leave data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [activeTab, currentRole]);

  const handleAction = async (requestId, action) => {
    try {
      await axios.post(`${API_URL}/leave/admin/approve`, {
        request_id: requestId,
        role: currentRole,
        action: action
      });
      fetchData(); // Refresh list
    } catch (err) {
      alert("Error processing request: " + (err.response?.data?.error || err.message));
    }
  };

  const handleSubmitRequest = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const payload = { ...formData };
      
      // Force student_id if logged in as student
      const studentId = user?.person_id || user?.id || user?.username;
      
      if (user?.role === 'user' && studentId) {
        payload.student_id = studentId;
      }
      
      if (!payload.student_id) {
        alert("Error: Student ID is missing. Please re-login.");
        setLoading(false);
        return;
      }

      await axios.post(`${API_URL}/leave/request`, payload);
      alert("Leave request submitted successfully! Pending parent approval.");
      setFormData({
        leave_type: 'home',
        reason: '',
        start_date: '',
        end_date: '',
        start_time: '10:00',
        end_time: '18:00'
      });
      if (user?.role === 'user') setActiveTab('history');
    } catch (err) {
      alert("Error submitting request: " + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateLogins = async () => {
    if (!window.confirm("This will generate login accounts for all students who don't have one yet. Continue?")) return;
    setGenerating(true);
    try {
      const res = await axios.post(`${API_URL}/leave/admin/generate-logins`);
      alert(res.data.message);
    } catch (err) {
      alert("Error generating logins: " + (err.response?.data?.error || err.message));
    } finally {
      setGenerating(false);
    }
  };

  const filteredRequests = requests.filter(req => 
    (req.student_name || "").toLowerCase().includes(searchTerm.toLowerCase()) ||
    (req.reason || "").toLowerCase().includes(searchTerm.toLowerCase())
  );

  const filteredParents = parents.filter(p => 
    p.username?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    p.student_number?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <ShieldCheck className="text-blue-600" />
            Leave Management
          </h1>
          <p className="text-slate-500">Review and approve student leave permissions.</p>
        </div>

        <div className="flex bg-slate-100 p-1 rounded-lg">
          {user?.role === 'user' && !staffSession ? (
            <>
              <button
                onClick={() => setActiveTab('new_request')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'new_request' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
              >
                New Request
              </button>
              <button
                onClick={() => setActiveTab('history')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'history' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
              >
                My History
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setActiveTab('pending')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'pending' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
              >
                Pending Approvals
              </button>
              <button
                onClick={() => setActiveTab('parents')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'parents' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
              >
                Parent Validation
              </button>
            </>
          )}
        </div>

        {user?.role !== 'user' && (
          <div className="flex gap-2">
            <button
              onClick={() => setShowPinModal(true)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg shadow-sm transition-all focus:ring-2 focus:ring-blue-500/20 text-sm font-medium ${staffSession ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-white text-slate-700 border border-slate-200 hover:bg-slate-50'}`}
            >
              <ShieldCheck size={18} />
              {staffSession ? `${staffSession.name} (${staffSession.role.toUpperCase()})` : "Enter PIN / Switch Role"}
            </button>
            <button
              onClick={handleGenerateLogins}
              disabled={generating}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800 text-white hover:bg-slate-900 rounded-lg shadow-sm transition-all disabled:opacity-50 text-sm font-medium"
            >
              <Users size={18} className="text-blue-400" />
              {generating ? "Generating..." : "Generate Logins"}
            </button>
          </div>
        )}
      </div>

      {/* Search Bar */}
      <div className="relative">
        <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400">
          <Search size={18} />
        </span>
        <input
          type="text"
          placeholder={activeTab === 'pending' ? "Search student or reason..." : "Search parent or student ID..."}
          className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {activeTab === 'new_request' ? (
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <form onSubmit={handleSubmitRequest} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Leave Type</label>
                    <select
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      value={formData.leave_type}
                      onChange={(e) => setFormData({...formData, leave_type: e.target.value})}
                    >
                      <option value="home">Home Visit</option>
                      <option value="night_out">Night Out</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Reason</label>
                    <input
                      type="text"
                      required
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="e.g. Family Function / Medical"
                      value={formData.reason}
                      onChange={(e) => setFormData({...formData, reason: e.target.value})}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Start Date</label>
                    <input
                      type="date"
                      required
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      value={formData.start_date}
                      onChange={(e) => setFormData({...formData, start_date: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">End Date</label>
                    <input
                      type="date"
                      required
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      value={formData.end_date}
                      onChange={(e) => setFormData({...formData, end_date: e.target.value})}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Reporting Time (Start)</label>
                    <input
                      type="time"
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      value={formData.start_time}
                      onChange={(e) => setFormData({...formData, start_time: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Expected Return Time</label>
                    <input
                      type="time"
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      value={formData.end_time}
                      onChange={(e) => setFormData({...formData, end_time: e.target.value})}
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-blue-600 text-white py-3 rounded-xl font-bold hover:bg-blue-700 transition-colors shadow-lg shadow-blue-200 disabled:opacity-50"
                >
                  {loading ? "Submitting..." : "Submit Leave Request"}
                </button>
              </form>
            </div>
          ) : activeTab === 'pending' ? (
            filteredRequests.length > 0 ? (
              filteredRequests.map(req => (
                <div key={req.id} className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex flex-col md:flex-row justify-between gap-4">
                    <div className="flex items-start gap-4">
                      <div className="p-3 bg-blue-50 text-blue-600 rounded-full shrink-0">
                        <User size={24} />
                      </div>
                      <div className="space-y-1">
                        <h3 className="font-bold text-slate-800 text-lg">{req.student_name}</h3>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500 items-center">
                          <span className="flex items-center gap-1">
                            <FileText size={14} /> {req.leave_type === 'home' ? 'Home Visit' : 'Night Out'}
                          </span>
                          <span className="flex items-center gap-1">
                            <Calendar size={14} /> {req.start_date} to {req.end_date}
                          </span>
                          <span className="flex items-center gap-1">
                            <Clock size={14} /> {req.start_time} - {req.end_time}
                          </span>
                        </div>
                        <p className="text-slate-700 bg-slate-50 p-2 rounded border border-slate-100 mt-2 italic text-sm">
                          "{req.reason}"
                        </p>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2 self-end md:self-center">
                      <button
                        onClick={() => handleAction(req.id, 'rejected')}
                        className="flex items-center gap-2 px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg border border-red-100 transition-colors"
                      >
                        <XCircle size={18} /> Reject
                      </button>
                      <button
                        onClick={() => handleAction(req.id, 'approved')}
                        className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white hover:bg-green-700 rounded-lg shadow-sm transition-colors"
                      >
                        <CheckCircle size={18} /> Approve
                      </button>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-12 bg-slate-50 rounded-xl border border-dashed border-slate-300">
                <Clock size={48} className="mx-auto text-slate-300 mb-2" />
                <p className="text-slate-500">No pending leave requests found.</p>
              </div>
            )
          ) : activeTab === 'history' ? (
            <div className="space-y-4">
              {requests.length > 0 ? (
                requests.map(req => (
                  <div key={req.id} className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                    <div className="flex justify-between items-start mb-4">
                      <div>
                        <h3 className="font-bold text-slate-800">{req.leave_type === 'home' ? 'Home Visit' : 'Night Out'}</h3>
                        <p className="text-sm text-slate-500">{req.start_date} to {req.end_date}</p>
                      </div>
                      <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${req.final_status === 'approved' ? 'bg-green-100 text-green-700' : req.final_status === 'rejected' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>
                        {req.final_status}
                      </span>
                    </div>
                    
                    {/* Visual Tracker */}
                    <div className="flex items-center justify-between mt-6 relative px-4">
                      {/* Line */}
                      <div className="absolute top-1/2 left-10 right-10 h-0.5 bg-slate-100 -translate-y-1/2 z-0"></div>
                      
                      {/* Logic for steps */}
                      {[
                        { label: 'Parent', status: req.parent_status },
                        { label: 'Rector', status: req.rector_status },
                        { label: 'HOD', status: req.hod_status }
                      ].map((step, idx) => {
                        const isDone = step.status === 'approved';
                        const isRejected = step.status === 'rejected';
                        return (
                          <div key={idx} className="flex flex-col items-center relative z-10">
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all ${isDone ? 'bg-green-500 border-green-500 text-white' : isRejected ? 'bg-red-500 border-red-500 text-white' : 'bg-white border-slate-200 text-slate-400'}`}>
                              {isDone ? <CheckCircle size={16} /> : isRejected ? <XCircle size={16} /> : <Clock size={16} />}
                            </div>
                            <span className="text-[10px] uppercase font-bold mt-2 tracking-wider text-slate-500">{step.label}</span>
                            <span className={`text-[9px] mt-0.5 ${isDone ? 'text-green-600' : isRejected ? 'text-red-600' : 'text-slate-400'}`}>{step.status.toUpperCase()}</span>
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-4 pt-4 border-t border-slate-50 text-sm text-slate-600 italic">
                      "{req.reason}"
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-12 bg-slate-50 rounded-xl border border-dashed border-slate-300">
                  <Clock size={48} className="mx-auto text-slate-300 mb-2" />
                  <p className="text-slate-500">Your leave request history will appear here.</p>
                </div>
              )}
            </div>
          ) : (
            /* Parent Validation Tab */
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredParents.length > 0 ? (
                filteredParents.map(parent => (
                  <div key={parent.id} className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
                    <div className="aspect-square relative group bg-slate-100">
                      {parent.face_image ? (
                        <img 
                          src={parent.face_image} 
                          alt={parent.username} 
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <User size={64} className="text-slate-300" />
                        </div>
                      )}
                      <div className="absolute top-2 right-2 bg-blue-600 text-white text-[10px] uppercase font-bold px-2 py-0.5 rounded shadow-sm">
                        Registered
                      </div>
                    </div>
                    <div className="p-4 space-y-2">
                      <h3 className="font-bold text-slate-800">{parent.username}</h3>
                      <div className="text-xs text-slate-500 space-y-1">
                        <p className="flex items-center gap-1 uppercase tracking-tighter">
                          <Users size={12} /> Student ID: <span className="text-slate-800 font-medium">{parent.student_number}</span>
                        </p>
                        <p className="flex items-center gap-1">
                          <Clock size={12} /> Phone: <span className="text-slate-800">{parent.contact_phone}</span>
                        </p>
                      </div>
                      <button className="w-full mt-2 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 rounded-md border border-slate-200 transition-colors">
                        View Details
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="col-span-full text-center py-12 bg-slate-50 rounded-xl border border-dashed border-slate-300">
                  <User size={48} className="mx-auto text-slate-300 mb-2" />
                  <p className="text-slate-500">No registered parents found.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {/* PIN Modal */}
      {showPinModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[100] flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl w-full max-w-sm overflow-hidden shadow-2xl animate-in fade-in zoom-in duration-200">
            <div className="p-6 border-b border-slate-50 flex justify-between items-center bg-slate-50/50">
              <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                <ShieldCheck className="text-blue-600" /> Staff Verification
              </h3>
              <button onClick={() => setShowPinModal(false)} className="text-slate-400 hover:text-slate-600 p-1">
                <XCircle size={20} />
              </button>
            </div>
            <form onSubmit={handleVerifyPin} className="p-6 space-y-4">
              <p className="text-sm text-slate-500 leading-relaxed">
                Enter your 4-digit PIN to switch to your administrative role and access pending approvals.
              </p>
              <div className="relative">
                <input
                  type="password"
                  maxLength={4}
                  autoFocus
                  placeholder="Enter 4-digit PIN"
                  className="w-full p-4 border border-slate-200 rounded-xl text-center text-2xl tracking-[1em] font-mono focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all placeholder:tracking-normal placeholder:text-sm"
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
                />
              </div>
              <button
                type="submit"
                disabled={pin.length !== 4}
                className="w-full bg-slate-900 text-white py-3.5 rounded-xl font-bold hover:bg-black transition-all shadow-lg shadow-slate-200 disabled:opacity-50 disabled:shadow-none flex items-center justify-center gap-2"
              >
                Verify & Continue
              </button>
              {staffSession && (
                <button
                  type="button"
                  onClick={() => { setStaffSession(null); setShowPinModal(false); }}
                  className="w-full text-red-600 text-sm font-medium py-2 hover:bg-red-50 rounded-lg transition-colors"
                >
                  Logout Staff Session
                </button>
              )}
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default LeaveManagement;
