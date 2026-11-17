import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
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
  Users,
  RotateCcw,
  Settings,
  Plus,
  Trash2,
  ChevronUp,
  ChevronDown,
  ChevronRight,
  Edit2,
  X,
  Ban,
  AlertTriangle
} from 'lucide-react';
import { getBusinessTerminology, usesStudentRecords, isHostelVertical } from '../lib/businessTerminology';

const LeaveManagement = () => {
  const { user, staffSession, loginAsStaff, logout, logoutStaff } = useAuth();
  const terminology = getBusinessTerminology(user?.vertical);
  const isStudentFlow = usesStudentRecords(user?.vertical);
  const isHostel = isHostelVertical(user?.vertical);
  const isRegularUser = (user?.role === 'user' || user?.role === 'student') && !staffSession;

  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const validTabs = ['new_request', 'pending', 'tracking', 'parents', 'history', 'workflow'];
  const [activeTab, setActiveTab] = useState(() => {
    if (tabParam && validTabs.includes(tabParam)) return tabParam;
    return isRegularUser ? 'new_request' : 'pending';
  });

  useEffect(() => {
    const requestedTab = searchParams.get('tab');
    if (requestedTab && validTabs.includes(requestedTab)) {
      setActiveTab(requestedTab);
    }
  }, [searchParams]);
  const [requests, setRequests] = useState([]);
  const [trackingData, setTrackingData] = useState([]);
  const [parents, setParents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submissionStage, setSubmissionStage] = useState('idle');
  const submissionInFlightRef = React.useRef(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [dateFilter, setDateFilter] = useState('');
  const [generating, setGenerating] = useState(false);
  const [showPinModal, setShowPinModal] = useState(false);
  const [pin, setPin] = useState('');
  const [workflow, setWorkflow] = useState(null);
  const [studentWorkflow, setStudentWorkflow] = useState(null);
  const [dataError, setDataError] = useState('');
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const isSuperAdmin = user?.role === 'super_admin';
  const canViewWorkflow = ['super_admin', 'vendor_admin', 'admin', 'owner', 'rector', 'hod', 'staff'].includes(user?.role) || !isRegularUser;
  const canConfigureWorkflow = isSuperAdmin;
  
  const [editingLeave, setEditingLeave] = useState(null);
  const [editFormData, setEditFormData] = useState({
    leave_type: 'home',
    reason: '',
    start_date: '',
    end_date: '',
    start_time: '10:00',
    end_time: '18:00'
  });
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [previewImage, setPreviewImage] = useState(null);

  const handleOpenEdit = (req) => {
    setEditingLeave(req);
    setEditFormData({
      leave_type: req.leave_type || (isStudentFlow ? 'home' : 'casual'),
      reason: req.reason || '',
      start_date: req.start_date || '',
      end_date: req.end_date || '',
      start_time: req.start_time || '10:00',
      end_time: req.end_time || '18:00'
    });
  };

  const handleUpdateLeave = async (e) => {
    e.preventDefault();
    if (!editingLeave) return;
    if (editFormData.start_date && editFormData.end_date && editFormData.start_date > editFormData.end_date) {
      alert("Error: Start date cannot be after end date.");
      return;
    }
    setEditSubmitting(true);
    try {
      await axios.put(`${API_URL}/leave/request/${editingLeave.id}`, editFormData, isRegularUser ? {} : staffRequestConfig);
      alert("Leave request updated successfully!");
      setEditingLeave(null);
      fetchData();
    } catch (err) {
      alert("Error updating leave request: " + (err.response?.data?.error || err.message));
    } finally {
      setEditSubmitting(false);
    }
  };

  const [toast, setToast] = useState(null);
  const toastTimeoutRef = React.useRef(null);

  const showToast = ({ type = 'info', title, message, subtext, overlap, actionText, onAction, duration = 6000 }) => {
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    setToast({ type, title, message, subtext, overlap, actionText, onAction });
    if (duration > 0) {
      toastTimeoutRef.current = setTimeout(() => {
        setToast(null);
      }, duration);
    }
  };

  useEffect(() => {
    return () => {
      if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    };
  }, []);

  const isLeaveStarted = (req) => {
    if (!req?.start_date) return false;
    try {
      const [y, m, d] = req.start_date.split('-').map(Number);
      const [h, min] = (req.start_time || '00:00').split(':').map(Number);
      const startDateTime = new Date(y, m - 1, d, h || 0, min || 0);
      return new Date() >= startDateTime;
    } catch (e) {
      return false;
    }
  };

  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [cancelTarget, setCancelTarget] = useState(null);
  const [cancellationReason, setCancellationReason] = useState('');
  const [submittingCancel, setSubmittingCancel] = useState(false);

  const handleOpenCancelModal = (req) => {
    setCancelTarget(req);
    setCancellationReason('');
    setCancelModalOpen(true);
  };

  const handleConfirmCancel = async () => {
    if (!cancellationReason.trim()) {
      showToast({
        type: 'error',
        title: 'Cancellation Reason Required',
        message: 'Please provide a reason for cancelling this leave.',
        duration: 4000,
      });
      return;
    }
    setSubmittingCancel(true);
    try {
      const res = await axios.post(`${API_URL}/leave/student/cancel-request`, {
        request_id: cancelTarget.id,
        cancellation_reason: cancellationReason.trim()
      }, isRegularUser ? {} : staffRequestConfig);
      showToast({
        type: 'success',
        title: 'Cancellation Submitted',
        message: res.data.message || 'Leave cancellation requested! Awaiting parent approval on mobile app.',
        duration: 5000,
      });
      setCancelModalOpen(false);
      setCancelTarget(null);
      setCancellationReason('');
      fetchData();
    } catch (err) {
      const errData = err.response?.data || {};
      showToast({
        type: 'error',
        title: 'Cancellation Failed',
        message: errData.error || err.message || 'Failed to submit cancellation request.',
        duration: 6000,
      });
    } finally {
      setSubmittingCancel(false);
    }
  };
  
  const currentRole = staffSession?.role || user?.role;
  const staffRequestConfig = staffSession?.access_token
    ? { headers: { 'X-Leave-Staff-Token': staffSession.access_token } }
    : {};

  // Set default tab based on role once user is available
  useEffect(() => {
    if (isRegularUser) {
      setActiveTab('new_request');
    } else {
      setActiveTab('pending');
    }
  }, [isRegularUser]);

  const [formData, setFormData] = useState({
    leave_type: isStudentFlow ? 'home' : 'casual',
    reason: '',
    start_date: '',
    end_date: '',
    start_time: '10:00',
    end_time: '18:00'
  });

  useEffect(() => {
    setFormData(prev => ({
      ...prev,
      leave_type: isStudentFlow ? 'home' : 'casual'
    }));
  }, [isStudentFlow]);

  const formatLeaveType = (type) => {
    const map = {
      home: 'Home Visit',
      night_out: 'Night Out',
      outing: 'Day Outing',
      medical: 'Medical Leave',
      casual: 'Casual Leave (CL)',
      sick: 'Sick Leave (SL)',
      privilege: 'Privilege Leave (PL)',
      half_day: 'Half Day Leave',
      comp_off: 'Comp Off',
      unpaid: 'Leave Without Pay',
      other: 'Leave',
    };
    return map[String(type || '').toLowerCase()] || String(type || 'Leave').replace('_', ' ');
  };

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

  const fetchData = async (isSilent = false) => {
    if (isRegularUser && !['new_request', 'history'].includes(activeTab)) return;
    if (!isSilent) {
      setLoading(true);
      setDataError('');
      if (['pending', 'history'].includes(activeTab)) setRequests([]);
    }
    try {
      if (activeTab === 'new_request' && isRegularUser) {
        const res = await axios.get(`${API_URL}/leave/student/workflow`);
        setStudentWorkflow(res.data.workflow || null);
      } else if (activeTab === 'pending') {
        let url = `${API_URL}/leave/admin/pending?role=${currentRole}`;
        if (staffSession?.department) {
          url += `&department=${encodeURIComponent(staffSession.department)}`;
        }
        const res = await axios.get(url, staffRequestConfig);
        setRequests(res.data.requests || []);
      } else if (activeTab === 'history') {
        let url;
        if (isRegularUser) {
          url = `${API_URL}/leave/student/history`;
        } else {
          url = `${API_URL}/leave/admin/history?role=${currentRole}&status=${statusFilter}`;
          if (staffSession?.department) {
            url += `&department=${encodeURIComponent(staffSession.department)}`;
          }
        }
        const res = await axios.get(url, isRegularUser ? {} : staffRequestConfig);
        setRequests(res.data.history || res.data.requests || []);
      } else if (activeTab === 'tracking') {
        let url = `${API_URL}/leave/admin/tracking?role=${currentRole}`;
        if (staffSession?.department) {
          url += `&department=${encodeURIComponent(staffSession.department)}`;
        }
        const res = await axios.get(url, staffRequestConfig);
        setTrackingData(res.data.tracking || []);
      } else if (activeTab === 'parents') {
        const res = await axios.get(`${API_URL}/leave/parent-faces`);
        setParents(res.data.parents || []);
      } else if (activeTab === 'workflow') {
        const res = await axios.get(`${API_URL}/leave/admin/workflow`);
        setWorkflow(res.data.workflow || null);
      }
    } catch (err) {
      console.error("Error fetching leave data:", err);
      if (!isSilent) {
        setDataError(err.response?.data?.error || 'Unable to load leave information. Please refresh and try again.');
      }
    } finally {
      if (!isSilent) setLoading(false);
    }
  };

  // Real-time automatic background synchronization every 4 seconds
  useEffect(() => {
    if (!['pending', 'history', 'tracking'].includes(activeTab)) return;
    const interval = setInterval(() => {
      if (!document.hidden) {
        fetchData(true);
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [activeTab, currentRole, statusFilter]);

  useEffect(() => {
    fetchData();
  }, [activeTab, currentRole, statusFilter]);

  const handleAction = async (requestId, action) => {
    try {
      await axios.post(`${API_URL}/leave/admin/approve`, {
        request_id: requestId,
        role: currentRole,
        action: action,
        department: staffSession?.department || undefined
      }, staffRequestConfig);
      fetchData(); // Refresh list
    } catch (err) {
      alert("Error processing request: " + (err.response?.data?.error || err.message));
    }
  };

  const handleDeleteParent = async (parentId, name) => {
    if (!window.confirm(`Are you sure you want to delete the parent record and registered face for ${name || 'this student'}? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API_URL}/leave/parent-faces/${parentId}`);
      fetchData();
    } catch (err) {
      alert("Error deleting parent: " + (err.response?.data?.error || err.message));
    }
  };

  const handleSubmitRequest = async (e) => {
    e.preventDefault();
    if (submissionInFlightRef.current) return;
    if (formData.start_date && formData.end_date && formData.start_date > formData.end_date) {
      showToast({
        type: 'error',
        title: 'Invalid Date Range',
        message: 'Start date cannot be after end date.',
        duration: 4000,
      });
      return;
    }

    const payload = { ...formData };
    const personId = user?.person_id || user?.id || user?.username;

    if (isRegularUser && personId) {
      payload.student_id = personId;
    }

    if (!payload.student_id) {
      showToast({
        type: 'error',
        title: 'Account Incomplete',
        message: `${terminology.person} ID is missing. Please re-login.`,
        duration: 5000,
      });
      return;
    }

    submissionInFlightRef.current = true;
    setLoading(true);
    setSubmissionStage('drafting');
    const sendingTimer = window.setTimeout(() => setSubmissionStage('sending'), 420);

    try {
      await Promise.all([
        axios.post(`${API_URL}/leave/request`, payload),
        new Promise(resolve => window.setTimeout(resolve, 720)),
      ]);
      window.clearTimeout(sendingTimer);
      setSubmissionStage('sent');
      showToast({
        type: 'success',
        title: 'Leave Application Submitted',
        message: 'Your leave request has been submitted successfully and sent for approval.',
        duration: 5000,
      });
      setFormData({
        leave_type: isStudentFlow ? 'home' : 'casual',
        reason: '',
        start_date: '',
        end_date: '',
        start_time: '10:00',
        end_time: '18:00'
      });
      await new Promise(resolve => window.setTimeout(resolve, 1100));
      setSubmissionStage('idle');
      if (isRegularUser) setActiveTab('history');
    } catch (err) {
      window.clearTimeout(sendingTimer);
      setSubmissionStage('idle');
      const errData = err.response?.data || {};
      if (errData.error_code === 'LEAVE_OVERLAP' && errData.overlap) {
        const ov = errData.overlap;
        showToast({
          type: 'overlap',
          title: 'Overlapping Leave Dates Conflict',
          message: `You already have a leave request (${formatLeaveType(ov.leave_type)}) from ${ov.start_date} to ${ov.end_date} (Status: ${String(ov.final_status).toUpperCase()}).`,
          subtext: 'Overlapping leave dates are not allowed. If your travel plans have changed, you can cancel your previous leave request in the History tab.',
          overlap: ov,
          actionText: 'View in My History',
          onAction: () => {
            setActiveTab('history');
            setToast(null);
          },
          duration: 12000,
        });
      } else {
        showToast({
          type: 'error',
          title: 'Unable to Submit Leave',
          message: errData.error || err.message || 'An error occurred while submitting your leave request.',
          duration: 6000,
        });
      }
    } finally {
      submissionInFlightRef.current = false;
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

  const handleResetPassword = async () => {
    if (!window.confirm("This will reset your password to your registered mobile number and LOG YOU OUT. Are you sure?")) return;
    
    try {
      await axios.post(`${API_URL}/auth/student/reset-to-default`, {});
      alert("Password reset successfully! Please login again with your mobile number.");
      logout();
    } catch (err) {
      alert("Error resetting password: " + (err.response?.data?.error || err.message));
    }
  };

  const updateWorkflowStage = (index, patch) => {
    setWorkflow(prev => ({
      ...prev,
      stages: prev.stages.map((stage, stageIndex) => stageIndex === index ? { ...stage, ...patch } : stage)
    }));
  };

  const moveWorkflowStage = (index, offset) => {
    setWorkflow(prev => {
      const stages = [...prev.stages];
      const target = index + offset;
      if (target < 0 || target >= stages.length) return prev;
      [stages[index], stages[target]] = [stages[target], stages[index]];
      return { ...prev, stages };
    });
  };

  const addWorkflowStage = () => {
    setWorkflow(prev => ({
      ...(prev || { name: 'Leave Approval' }),
      stages: [
        ...(prev?.stages || []),
        {
          display_name: 'New Approver',
          actor_type: 'staff',
          role_key: `approver_${(prev?.stages?.length || 0) + 1}`,
          department_scoped: false,
          auth_method: 'staff_pin'
        }
      ]
    }));
  };

  const saveWorkflow = async () => {
    if (!workflow?.stages?.length) return alert('Add at least one approval stage.');
    if (!window.confirm('Save this workflow for new leave requests? Existing requests will keep their current path.')) return;
    setSavingWorkflow(true);
    try {
      const res = await axios.put(`${API_URL}/leave/admin/workflow`, {
        name: workflow.name,
        stages: workflow.stages
      });
      setWorkflow(res.data.workflow);
      alert(res.data.message || 'Workflow saved successfully.');
    } catch (err) {
      alert('Unable to save workflow: ' + (err.response?.data?.error || err.message));
    } finally {
      setSavingWorkflow(false);
    }
  };

  const filteredRequests = requests.filter(req => {
    const query = searchTerm.toLowerCase();
    const matchesSearch =
      (req.student_name || req.name || req.employee_name || "").toLowerCase().includes(query) ||
      (req.reason || "").toLowerCase().includes(query) ||
      formatLeaveType(req.leave_type).toLowerCase().includes(query);
    const matchesDate = !dateFilter || [req.created_at, req.start_date, req.end_date]
      .some(value => String(value || '').startsWith(dateFilter));
    return matchesSearch && matchesDate;
  });

  const filteredParents = parents.filter(p => 
    (p.username?.toLowerCase().includes(searchTerm.toLowerCase()) ||
     p.student_number?.toLowerCase().includes(searchTerm.toLowerCase())) &&
    (dateFilter === '' || (p.created_at && p.created_at.startsWith(dateFilter)))
  );

  return (
    <div className="space-y-6">
      {submissionStage !== 'idle' && (
        <div className="leave-submit-overlay" role="status" aria-live="polite" aria-busy={submissionStage !== 'sent'}>
          <div className="leave-submit-feedback" data-stage={submissionStage}>
            <div className="leave-submit-visual" aria-hidden="true">
              {submissionStage === 'sent' ? (
                <span className="leave-submit-check">
                  <CheckCircle size={48} strokeWidth={2.4} />
                </span>
              ) : (
                <span className="leave-mail-loader" />
              )}
            </div>
            <div className="leave-submit-copy">
              <p className="leave-submit-kicker">
                {submissionStage === 'sent' ? 'Successfully submitted' : 'Leave application'}
              </p>
              <h2>
                {submissionStage === 'drafting' && 'Drafting your request'}
                {submissionStage === 'sending' && 'Sending for approval'}
                {submissionStage === 'sent' && 'Leave request sent'}
              </h2>
              <p>
                {submissionStage === 'drafting' && 'Preparing your dates and approval route.'}
                {submissionStage === 'sending' && 'Submitting to your configured approval chain.'}
                {submissionStage === 'sent' && 'Your request is now ready for the first approver.'}
              </p>
            </div>
            <div className="leave-submit-progress" aria-hidden="true">
              <span className="is-complete" />
              <span className={submissionStage !== 'drafting' ? 'is-complete' : ''} />
              <span className={submissionStage === 'sent' ? 'is-complete' : ''} />
            </div>
          </div>
        </div>
      )}

      {/* Interactive Modern Toast / Alert Notification */}
      {toast && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-[200] max-w-lg w-[calc(100%-2rem)] px-2 animate-in fade-in slide-in-from-top-4 duration-200">
          {toast.type === 'overlap' ? (
            <div className="bg-white rounded-2xl border-2 border-amber-400 p-4 shadow-2xl shadow-amber-500/10 flex flex-col gap-3">
              <div className="flex items-start gap-3">
                <div className="p-2.5 bg-amber-100 text-amber-700 rounded-xl shrink-0 mt-0.5">
                  <AlertTriangle size={22} className="text-amber-600 animate-pulse" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="font-bold text-amber-950 text-sm">{toast.title}</h4>
                    <button
                      onClick={() => setToast(null)}
                      className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors"
                      title="Dismiss"
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <p className="text-xs text-amber-900 mt-1 leading-relaxed">{toast.message}</p>
                  {toast.overlap && (
                    <div className="mt-2.5 p-2.5 bg-amber-50 border border-amber-200 rounded-xl text-xs flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="text-[10px] uppercase font-bold text-amber-700 tracking-wider block">Existing Leave</span>
                        <span className="font-semibold text-slate-800">{formatLeaveType(toast.overlap.leave_type)}</span>
                        <span className="text-slate-500 ml-1.5 font-mono">({toast.overlap.start_date} &rarr; {toast.overlap.end_date})</span>
                      </div>
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-amber-200 text-amber-900">
                        {toast.overlap.final_status}
                      </span>
                    </div>
                  )}
                  {toast.subtext && (
                    <p className="text-[11px] text-amber-800/80 mt-2 leading-relaxed">
                      {toast.subtext}
                    </p>
                  )}
                </div>
              </div>
              {toast.actionText && toast.onAction && (
                <div className="flex justify-end pt-2 border-t border-amber-100">
                  <button
                    onClick={toast.onAction}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-bold transition-colors shadow-xs"
                  >
                    <span>{toast.actionText}</span>
                    <ChevronRight size={14} />
                  </button>
                </div>
              )}
            </div>
          ) : toast.type === 'error' ? (
            <div className="bg-white rounded-2xl border border-rose-300 p-4 shadow-2xl flex items-start gap-3">
              <div className="p-2 bg-rose-100 text-rose-600 rounded-xl shrink-0 mt-0.5">
                <XCircle size={20} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="font-bold text-rose-950 text-sm">{toast.title}</h4>
                  <button
                    onClick={() => setToast(null)}
                    className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>
                <p className="text-xs text-rose-800 mt-1 leading-relaxed">{toast.message}</p>
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-2xl border border-emerald-300 p-4 shadow-2xl flex items-start gap-3">
              <div className="p-2 bg-emerald-100 text-emerald-600 rounded-xl shrink-0 mt-0.5">
                <CheckCircle size={20} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="font-bold text-emerald-950 text-sm">{toast.title}</h4>
                  <button
                    onClick={() => setToast(null)}
                    className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>
                <p className="text-xs text-emerald-800 mt-1 leading-relaxed">{toast.message}</p>
              </div>
            </div>
          )}
        </div>
      )}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <ShieldCheck className="text-blue-600" />
            {isHostel ? "Leave & Gate Pass Management" : "Leave Management"}
          </h1>
          <p className="text-slate-500">
            {isRegularUser
              ? (isHostel ? "Apply for hostel leave/gate pass and view approval status." : isStudentFlow ? "Apply for campus leave and view your status." : "Submit and track employee leave requests.")
              : (isHostel ? "Review and approve resident leave requests and gate passes." : isStudentFlow ? "Review and approve student leave permissions." : "Review and approve employee leave requests.")}
          </p>
        </div>

        <div className="flex bg-slate-100 p-1 rounded-lg">
          {!isRegularUser && (
            <button
              onClick={() => setShowPinModal(true)}
              className="px-4 py-2 rounded-md text-sm font-medium text-slate-700 hover:bg-white hover:text-blue-600 transition-colors flex items-center gap-1.5"
            >
              <ShieldCheck size={15} /> {staffSession ? `${staffSession.name || staffSession.role}${staffSession.department ? ` · ${staffSession.department}` : ''}` : 'Staff PIN'}
            </button>
          )}
          {isRegularUser ? (
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
                onClick={() => setActiveTab('tracking')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'tracking' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
              >
                {isHostel ? "Gate Pass Tracking" : "Leave Tracking"}
              </button>
              {isStudentFlow && (
                <button
                  onClick={() => setActiveTab('parents')}
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'parents' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
                >
                  {isHostel ? "Parent Verification" : "Parent Validation"}
                </button>
              )}
              <button
                onClick={() => setActiveTab('history')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'history' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
              >
                Leave History
              </button>
              {canViewWorkflow && (
                <button
                  onClick={() => setActiveTab('workflow')}
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'workflow' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
                >
                  Workflow Setup {isSuperAdmin ? '' : '(View Only)'}
                </button>
              )}
            </>
          )}
        </div>

      </div>

      {/* Search Bar & Filters */}
      {activeTab !== 'workflow' && <div className="flex flex-col md:flex-row gap-4">
        <div className="relative flex-1">
          <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400">
            <Search size={18} />
          </span>
          <input
            type="text"
            placeholder={activeTab === 'parents' ? "Search parent or student ID..." : `Search ${terminology.person.toLowerCase()} or reason...`}
            className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        
        {activeTab === 'history' && !isRegularUser && (
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-slate-700">Status:</label>
            <select
              className="p-2 border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none text-sm bg-white"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All Status</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
        )}
        
        {(activeTab === 'parents' || activeTab === 'history') && (
          <div className="flex items-center gap-2">
            <Calendar size={18} className="text-slate-400" />
            <input
              type="date"
              className="p-2 border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none text-sm"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
            />
            {dateFilter && (
              <button 
                onClick={() => setDateFilter('')}
                className="text-xs text-blue-600 font-bold hover:underline"
              >
                Clear
              </button>
            )}
          </div>
        )}
      </div>}

      {dataError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          {dataError}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {activeTab === 'workflow' ? (
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-6">
              {!isSuperAdmin && (
                <div className="flex items-center gap-3 p-4 bg-slate-50 border border-slate-200 rounded-xl text-slate-700 text-sm">
                  <ShieldCheck size={20} className="text-blue-600 shrink-0" />
                  <div>
                    <p className="font-bold text-slate-800">Workflow Setup (View Only)</p>
                    <p className="text-xs text-slate-500">The leave approval workflow hierarchy is centrally managed and locked for this organization.</p>
                  </div>
                </div>
              )}
              <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div className="flex-1">
                  <label className="block text-sm font-bold text-slate-700 mb-2">Workflow name</label>
                  <input
                    value={workflow?.name || ''}
                    disabled={!isSuperAdmin}
                    onChange={(e) => setWorkflow(prev => ({ ...(prev || { stages: [] }), name: e.target.value }))}
                    className="w-full p-3 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-700"
                    placeholder="Student Leave Approval"
                  />
                  <p className="text-xs text-slate-500 mt-2">
                    Version {workflow?.version || 'new'} · Changes apply only to newly submitted requests.
                  </p>
                </div>
                {isSuperAdmin && (
                  <button onClick={addWorkflowStage} className="flex items-center justify-center gap-2 px-4 py-3 border border-blue-200 text-blue-700 rounded-lg hover:bg-blue-50 font-bold">
                    <Plus size={18} /> Add Stage
                  </button>
                )}
              </div>

              <div className="space-y-3">
                {(workflow?.stages || []).map((stage, index) => (
                  <div key={`${stage.stage_key || 'new'}-${index}`} className="grid grid-cols-1 lg:grid-cols-[auto_1.4fr_1fr_1fr_auto_auto] gap-3 items-center p-4 border border-slate-200 rounded-xl bg-slate-50/60">
                    <div className="w-9 h-9 rounded-full bg-blue-600 text-white font-bold flex items-center justify-center">{index + 1}</div>
                    <div>
                      <label className="text-[10px] uppercase font-bold text-slate-400">Stage name</label>
                      <input
                        value={stage.display_name || ''}
                        disabled={!isSuperAdmin}
                        onChange={(e) => updateWorkflowStage(index, { display_name: e.target.value })}
                        className="w-full p-2 border border-slate-200 rounded-lg bg-white disabled:bg-slate-100 disabled:text-slate-700"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] uppercase font-bold text-slate-400">Approver type</label>
                      <select
                        value={stage.actor_type || 'staff'}
                        disabled={!isSuperAdmin}
                        onChange={(e) => updateWorkflowStage(index, e.target.value === 'parent'
                          ? { actor_type: 'parent', role_key: 'parent', auth_method: 'face', department_scoped: false }
                          : { actor_type: 'staff', role_key: stage.role_key === 'parent' ? `approver_${index + 1}` : stage.role_key, auth_method: 'staff_pin' })}
                        className="w-full p-2 border border-slate-200 rounded-lg bg-white disabled:bg-slate-100 disabled:text-slate-700"
                      >
                        <option value="staff">Staff</option>
                        <option value="parent">Parent</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] uppercase font-bold text-slate-400">Role key</label>
                      <input
                        value={stage.role_key || ''}
                        disabled={!isSuperAdmin || stage.actor_type === 'parent'}
                        onChange={(e) => updateWorkflowStage(index, { role_key: e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_') })}
                        className="w-full p-2 border border-slate-200 rounded-lg bg-white disabled:bg-slate-100 disabled:text-slate-700"
                        placeholder="warden"
                      />
                    </div>
                    <label className="flex items-center gap-2 text-sm text-slate-600 whitespace-nowrap">
                      <input
                        type="checkbox"
                        disabled={!isSuperAdmin || stage.actor_type === 'parent'}
                        checked={Boolean(stage.department_scoped)}
                        onChange={(e) => updateWorkflowStage(index, { department_scoped: e.target.checked })}
                      />
                      Department scoped
                    </label>
                    {isSuperAdmin ? (
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => moveWorkflowStage(index, -1)} disabled={index === 0} className="p-2 text-slate-500 hover:bg-white rounded disabled:opacity-30" title="Move up"><ChevronUp size={18} /></button>
                        <button onClick={() => moveWorkflowStage(index, 1)} disabled={index === workflow.stages.length - 1} className="p-2 text-slate-500 hover:bg-white rounded disabled:opacity-30" title="Move down"><ChevronDown size={18} /></button>
                        <button onClick={() => setWorkflow(prev => ({ ...prev, stages: prev.stages.filter((_, i) => i !== index) }))} className="p-2 text-red-500 hover:bg-red-50 rounded" title="Remove stage"><Trash2 size={18} /></button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-end text-xs text-slate-400 font-medium">
                        Stage #{index + 1}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="flex items-center justify-between border-t border-slate-100 pt-5">
                <p className="text-xs text-slate-500">Parent stages always require face authentication. Staff stages use an assigned staff PIN session.</p>
                {isSuperAdmin ? (
                  <button onClick={saveWorkflow} disabled={savingWorkflow || !workflow?.stages?.length} className="flex items-center gap-2 px-5 py-3 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50">
                    <Settings size={18} /> {savingWorkflow ? 'Saving...' : 'Save Workflow'}
                  </button>
                ) : (
                  <span className="text-xs font-semibold px-3 py-1.5 bg-slate-100 text-slate-500 rounded-lg border border-slate-200">
                    Configuration Locked
                  </span>
                )}
              </div>
            </div>
          ) : activeTab === 'new_request' ? (
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              {studentWorkflow?.stages?.length > 0 && (
                <div className="mb-6 rounded-xl border border-blue-100 bg-blue-50/60 p-4">
                  <div className="flex flex-col gap-1 mb-4">
                    <h3 className="font-bold text-slate-800 flex items-center gap-2">
                      <ShieldCheck size={18} className="text-blue-600" /> Approval path
                    </h3>
                    <p className="text-xs text-slate-500">
                      Your request will move through these approvals in order.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {studentWorkflow.stages.map((stage, index) => (
                      <React.Fragment key={stage.stage_key || `${stage.display_name}-${index}`}>
                        <div className="flex min-w-36 items-center gap-3 rounded-lg border border-blue-100 bg-white px-3 py-2 shadow-sm">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
                            {index + 1}
                          </span>
                          <div>
                            <p className="text-sm font-bold text-slate-800">{stage.display_name}</p>
                            {stage.department_scoped && (
                              <p className="text-[10px] font-medium uppercase tracking-wide text-blue-600">Your department</p>
                            )}
                          </div>
                        </div>
                        {index < studentWorkflow.stages.length - 1 && (
                          <ChevronRight size={18} className="text-blue-300" aria-hidden="true" />
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              )}
              <form onSubmit={handleSubmitRequest} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Leave Type</label>
                    <select
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 bg-white text-slate-800"
                      value={formData.leave_type}
                      onChange={(e) => setFormData({...formData, leave_type: e.target.value})}
                    >
                      {isStudentFlow ? (
                        <>
                          <option value="home">Home Visit</option>
                          <option value="night_out">Night Out</option>
                          <option value="outing">Day Outing</option>
                          <option value="medical">Medical Leave</option>
                        </>
                      ) : (
                        <>
                          <option value="casual">Casual Leave (CL)</option>
                          <option value="sick">Sick Leave (SL)</option>
                          <option value="privilege">Privilege / Earned Leave (PL)</option>
                          <option value="half_day">Half Day Leave</option>
                          <option value="comp_off">Compensatory Off (Comp Off)</option>
                          <option value="unpaid">Leave Without Pay (LWP)</option>
                          <option value="other">Other</option>
                        </>
                      )}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">Reason</label>
                    <input
                      type="text"
                      required
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder={isStudentFlow ? "e.g. Family Function / Medical" : "e.g. Personal work / Medical / Urgent matter"}
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
                    <label className="block text-sm font-medium text-slate-700 mb-1">{isStudentFlow ? "Reporting Time (Start)" : "Start Time (Optional)"}</label>
                    <input
                      type="time"
                      className="w-full p-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
                      value={formData.start_time}
                      onChange={(e) => setFormData({...formData, start_time: e.target.value})}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1">{isStudentFlow ? "Expected Return Time" : "End Time (Optional)"}</label>
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

              {/* Reset Password section for students */}
              <div className="mt-8 pt-6 border-t border-slate-100 italic">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                  <div>
                    <h4 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                       <RotateCcw size={16} className="text-slate-400" /> Security Settings
                    </h4>
                    <p className="text-xs text-slate-500 mt-1">Reset your custom password back to your mobile number</p>
                  </div>
                  <button
                    onClick={handleResetPassword}
                    className="flex items-center gap-2 px-4 py-2 text-slate-600 hover:bg-slate-50 rounded-lg border border-slate-200 transition-colors text-xs font-bold uppercase tracking-wider"
                  >
                    Reset Password
                  </button>
                </div>
              </div>
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
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-bold text-slate-800 text-lg">{req.student_name || req.name || req.employee_name}</h3>
                          {req.no_hod_configured && (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200">
                              ⚠ No HOD configured for {req.student_branch || 'branch'}
                            </span>
                          )}
                          {req.student_branch && !req.no_hod_configured && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-600">
                              Branch: {req.student_branch}
                            </span>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500 items-center">
                          <span className="flex items-center gap-1">
                            <FileText size={14} /> {formatLeaveType(req.leave_type)}
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
                        {/* Parent Face Verification Badge & Thumbnail if parent approved */}
                        {(req.approval_steps?.some(s => s.captured_face) || req.parent_captured_face) && (
                          <div className="mt-2.5 flex items-center gap-3 p-2 bg-emerald-50/80 border border-emerald-200/70 rounded-lg">
                            <div
                              className="w-12 h-12 rounded-lg overflow-hidden border-2 border-emerald-500 shadow-2xs cursor-pointer hover:scale-105 transition-transform shrink-0"
                              onClick={() => {
                                const stepWithFace = req.approval_steps?.find(s => s.captured_face);
                                const faceSrc = stepWithFace?.captured_face || req.parent_captured_face;
                                if (faceSrc) setPreviewImage(faceSrc.startsWith('data:') ? faceSrc : `data:image/jpeg;base64,${faceSrc}`);
                              }}
                              title="Click to view full verified parent photo"
                            >
                              <img
                                src={(() => {
                                  const stepWithFace = req.approval_steps?.find(s => s.captured_face);
                                  const faceSrc = stepWithFace?.captured_face || req.parent_captured_face;
                                  return faceSrc.startsWith('data:') ? faceSrc : `data:image/jpeg;base64,${faceSrc}`;
                                })()}
                                alt="Verified parent"
                                className="w-full h-full object-cover"
                              />
                            </div>
                            <div>
                              <span className="text-[10px] uppercase font-bold text-emerald-800">Parent Verified</span>
                              <p className="text-[11px] text-emerald-700 font-medium">Approved with face verification (Click to enlarge)</p>
                            </div>
                          </div>
                        )}
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
              {filteredRequests.length > 0 ? (
                filteredRequests.map(req => (
                  <div key={req.id} className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                    <div className="flex justify-between items-start mb-4">
                      <div className="flex items-center gap-3">
                        {!isRegularUser && (
                          <div className="p-2 bg-blue-50 text-blue-600 rounded-full shrink-0">
                            <User size={20} />
                          </div>
                        )}
                        <div>
                          <h3 className="font-bold text-slate-800">
                            {!isRegularUser ? (req.student_name || req.name || req.employee_name) : formatLeaveType(req.leave_type)}
                          </h3>
                          <div className="flex items-center gap-3 text-sm text-slate-500">
                            {!isRegularUser && (
                              <span className="font-mono bg-slate-100 px-1.5 py-0.5 rounded text-[11px] uppercase tracking-tighter">
                                {formatLeaveType(req.leave_type)}
                              </span>
                            )}
                            <p className="text-sm text-slate-500">{req.start_date} to {req.end_date}</p>
                          </div>
                        </div>
                      </div>
                      {req.final_status === 'cancelled' || req.cancellation_status === 'approved' ? (
                        <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-rose-100 text-rose-800 border border-rose-300">
                          Cancelled
                        </span>
                      ) : Number(req.is_cancellation) === 1 && req.cancellation_status === 'pending' ? (
                        <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-purple-100 text-purple-700 border border-purple-200">
                          Cancellation Pending Parent
                        </span>
                      ) : (
                        <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${req.final_status === 'approved' ? 'bg-green-100 text-green-700' : req.final_status === 'rejected' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>
                          {req.final_status}
                        </span>
                      )}
                    </div>
                    
                    {/* Visual Tracker */}
                    <div className="flex items-center justify-between mt-6 relative px-4">
                      {/* Line */}
                      <div className="absolute top-1/2 left-10 right-10 h-0.5 bg-slate-100 -translate-y-1/2 z-0"></div>
                      
                      {/* Logic for steps */}
                      {(req.approval_steps?.length ? req.approval_steps.map(step => ({
                        label: step.display_name,
                        status: step.status,
                        captured_face: step.captured_face,
                        actor_type: step.actor_type
                      })) : isStudentFlow ? [
                        { label: 'Rector', status: req.rector_status },
                        { label: 'HOD', status: req.hod_status },
                        { label: 'Parent', status: req.parent_status, captured_face: req.parent_captured_face }
                      ] : [
                        { label: 'Supervisor', status: req.rector_status || req.status },
                        { label: 'HR / Admin', status: req.hod_status || (req.rector_status === 'approved' ? 'approved' : req.status) }
                      ]).map((step, idx) => {
                        const stepStatus = String(step.status || 'pending').toLowerCase();
                        const isDone = stepStatus === 'approved';
                        const isRejected = stepStatus === 'rejected';
                        return (
                          <div key={idx} className="flex flex-col items-center relative z-10">
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all ${isDone ? 'bg-green-500 border-green-500 text-white' : isRejected ? 'bg-red-500 border-red-500 text-white' : 'bg-white border-slate-200 text-slate-400'}`}>
                              {isDone ? <CheckCircle size={16} /> : isRejected ? <XCircle size={16} /> : <Clock size={16} />}
                            </div>
                            <span className="text-[10px] uppercase font-bold mt-2 tracking-wider text-slate-500">{step.label}</span>
                            <span className={`text-[9px] mt-0.5 ${isDone ? 'text-green-600' : isRejected ? 'text-red-600' : 'text-slate-400'}`}>{stepStatus.toUpperCase()}</span>
                            {step.captured_face && (
                              <div className="mt-2 flex flex-col items-center">
                                <div
                                  className="w-12 h-12 rounded-lg overflow-hidden border-2 border-emerald-500 shadow-2xs cursor-pointer hover:ring-2 hover:ring-emerald-400 hover:scale-105 transition-all shrink-0"
                                  onClick={() => setPreviewImage(step.captured_face.startsWith('data:') ? step.captured_face : `data:image/jpeg;base64,${step.captured_face}`)}
                                  title="Click to view full verified parent photo"
                                >
                                  <img
                                    src={step.captured_face.startsWith('data:') ? step.captured_face : `data:image/jpeg;base64,${step.captured_face}`}
                                    alt="Verified parent"
                                    className="w-full h-full object-cover"
                                  />
                                </div>
                                <span className="text-[9px] font-bold text-emerald-700 bg-emerald-50 px-1 py-0.5 rounded border border-emerald-200 mt-1 whitespace-nowrap">
                                  Parent Photo
                                </span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {/* Cancellation notice banner if cancellation requested or done */}
                    {req.cancellation_reason && (
                      <div className="mt-3 p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
                        <div className="flex items-center gap-1.5 font-bold">
                          <Ban size={14} className="text-rose-600 shrink-0" />
                          <span>Cancellation Reason:</span>
                          <span className="font-normal italic">"{req.cancellation_reason}"</span>
                        </div>
                        {Number(req.is_cancellation) === 1 && req.cancellation_status === 'pending' && (
                          <p className="mt-1 font-semibold text-rose-700 flex items-center gap-1">
                            <Clock size={12} /> Awaiting parent approval via mobile face scan
                          </p>
                        )}
                        {req.final_status === 'cancelled' && (
                          <p className="mt-1 font-semibold text-emerald-700 flex items-center gap-1">
                            <CheckCircle size={12} /> Cancelled & approved by parent · Attendance active as normal
                          </p>
                        )}
                      </div>
                    )}

                    <div className="mt-4 pt-4 border-t border-slate-50 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-sm text-slate-600">
                      <p className="italic">"{req.reason}"</p>
                      <div className="flex items-center gap-2 shrink-0">
                        {/* Check if leave can be edited by student: pending final status and 0 approvals and no active cancellation */}
                        {(() => {
                          const hasApproval = (req.approval_steps || []).some(s => ['approved', 'rejected'].includes(String(s.status || '').toLowerCase()))
                            || ['approved', 'rejected'].includes(String(req.rector_status || '').toLowerCase())
                            || ['approved', 'rejected'].includes(String(req.hod_status || '').toLowerCase())
                            || ['approved', 'rejected'].includes(String(req.parent_status || '').toLowerCase());
                          const isEditable = String(req.final_status || '').toLowerCase() === 'pending' && !hasApproval && !(Number(req.is_cancellation) === 1);
                          if (!isEditable) return null;
                          return (
                            <button
                              type="button"
                              onClick={() => handleOpenEdit(req)}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-700 hover:bg-blue-100 rounded-lg text-xs font-bold border border-blue-200 transition-colors shrink-0 shadow-2xs"
                            >
                              <Edit2 size={13} /> Edit Leave
                            </button>
                          );
                        })()}
                        {/* Student Cancel Leave Button */}
                        {isRegularUser && req.final_status !== 'cancelled' && req.cancellation_status !== 'approved' && req.final_status !== 'rejected' && !(Number(req.is_cancellation) === 1 && req.cancellation_status === 'pending') && (
                          <button
                            type="button"
                            onClick={() => handleOpenCancelModal(req)}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 text-rose-700 hover:bg-rose-100 rounded-lg text-xs font-bold border border-rose-200 transition-colors shrink-0 shadow-2xs"
                            title="Request cancellation for this leave ticket"
                          >
                            <Ban size={13} /> Cancel Leave
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-12 bg-slate-50 rounded-xl border border-dashed border-slate-300">
                  <Clock size={48} className="mx-auto text-slate-300 mb-2" />
                  <p className="text-slate-500">{isRegularUser ? "Your leave request history will appear here." : "No leave history records match your filters."}</p>
                </div>
              )}
            </div>
          ) : activeTab === 'tracking' ? (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead className="bg-slate-50 text-slate-500 text-xs uppercase font-bold tracking-wider">
                  <tr>
                    <th className="p-4 border-b">{terminology.person}</th>
                    <th className="p-4 border-b">Leave Period</th>
                    <th className="p-4 border-b">Status</th>
                    <th className="p-4 border-b">Arrival</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {trackingData.length > 0 ? (
                    trackingData.map(item => (
                      <tr key={item.id} className="hover:bg-slate-50 transition-colors">
                        <td className="p-4">
                          <div className="flex items-center gap-3">
                            <div className="p-2 bg-blue-50 text-blue-600 rounded-full">
                              <User size={16} />
                            </div>
                            <div>
                              <p className="font-bold text-slate-800">{item.student_name || item.name || item.employee_name}</p>
                              <p className="text-[10px] text-slate-400 uppercase font-mono">{item.student_dept || item.department || 'General'}</p>
                            </div>
                          </div>
                        </td>
                        <td className="p-4">
                          <div className="text-sm">
                            <p className="text-slate-700 font-medium">{item.start_date} to {item.end_date}</p>
                            <p className="text-xs text-slate-400 italic">"{item.reason}"</p>
                          </div>
                        </td>
                        <td className="p-4">
                          <span className={`px-2 py-1 rounded text-[10px] font-bold uppercase tracking-tight 
                            ${item.tracking_color === 'red' ? 'bg-red-100 text-red-700' : 
                              item.tracking_color === 'green' ? 'bg-green-100 text-green-700' : 
                              item.tracking_color === 'orange' ? 'bg-orange-100 text-orange-700' : 
                              'bg-blue-100 text-blue-700'}`}
                          >
                            {item.tracking_status}
                          </span>
                        </td>
                        <td className="p-4">
                          {item.arrival_time ? (
                            <div className="text-sm">
                              <p className="text-green-600 font-bold">Arrived</p>
                              <p className="text-[10px] text-slate-400">{new Date(item.arrival_time).toLocaleString()}</p>
                            </div>
                          ) : (
                            <p className="text-slate-400 text-xs italic">Waiting...</p>
                          )}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan="4" className="p-12 text-center text-slate-500 italic">
                        No active or upcoming leaves tracked at this moment.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            /* Parent Validation Tab */
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {filteredParents.length > 0 ? (
                filteredParents.map(parent => (
                  <div key={parent.id} className="bg-white rounded-xl border border-slate-200/90 shadow-2xs hover:shadow-xs p-4 flex flex-col justify-between transition-all">
                    <div className="flex items-start gap-3.5">
                      {/* Compact Professional ID-style photo */}
                      <div 
                        className="w-20 h-24 rounded-lg overflow-hidden bg-slate-100 border border-slate-200 shrink-0 relative group cursor-pointer shadow-2xs"
                        onClick={() => parent.face_image && setPreviewImage(parent.face_image)}
                        title="Click to view full image"
                      >
                        {parent.face_image ? (
                          <img 
                            src={parent.face_image} 
                            alt={parent.username} 
                            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                          />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-slate-300">
                            <User size={32} />
                          </div>
                        )}
                        <span className="absolute bottom-1 right-1 bg-emerald-600 text-white text-[8px] font-bold px-1.5 py-0.5 rounded shadow-2xs">
                          Verified
                        </span>
                      </div>

                      {/* Details */}
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between items-start gap-1">
                          <h3 className="font-bold text-slate-800 text-sm truncate" title={parent.username}>
                            {parent.username}
                          </h3>
                          <span className="text-[10px] text-slate-400 font-mono shrink-0">
                            {parent.created_at?.split('T')[0]}
                          </span>
                        </div>
                        
                        <div className="mt-2 p-2 bg-slate-50/80 rounded-lg border border-slate-100 text-xs">
                          <p className="text-[10px] uppercase font-bold text-slate-400">Linked Student</p>
                          <p className="font-semibold text-slate-800 truncate flex items-center gap-1 mt-0.5">
                            <User size={12} className="text-blue-600 shrink-0" />
                            {parent.student_name || 'Not Linked'}
                          </p>
                          <p className="text-[10px] font-mono text-slate-500">{parent.student_number || '-'}</p>
                        </div>

                        <p className="text-xs text-slate-500 mt-2 flex items-center gap-1.5 truncate">
                          <span className="text-slate-400">Phone:</span>
                          <span className="font-medium text-slate-700">{parent.contact_phone || '-'}</span>
                        </p>
                      </div>
                    </div>

                    {/* Action buttons */}
                    <div className="flex gap-2 mt-3 pt-3 border-t border-slate-100">
                      <button 
                        type="button"
                        onClick={() => {
                          setSearchTerm(parent.student_name || parent.student_number || '');
                          setActiveTab('history');
                        }}
                        className="flex-1 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 rounded-lg border border-slate-200 transition-colors"
                      >
                        View History
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteParent(parent.id, parent.student_name || parent.student_number)}
                        className="py-1.5 px-2.5 text-xs font-medium text-red-600 hover:bg-red-50 rounded-lg border border-red-200 transition-colors flex items-center justify-center gap-1"
                        title="Delete Parent Account & Registered Face"
                      >
                        <Trash2 size={13} />
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
                  onClick={() => { logoutStaff(); setShowPinModal(false); }}
                  className="w-full text-red-600 text-sm font-medium py-2 hover:bg-red-50 rounded-lg transition-colors"
                >
                  Logout Staff Session
                </button>
              )}
            </form>
          </div>
        </div>
      )}

      {/* Edit Leave Request Modal (Only editable before 1st approval) */}
      {editingLeave && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 z-[100] animate-fadeIn">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200">
            <div className="flex justify-between items-center pb-4 border-b border-slate-100">
              <div>
                <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                  <Edit2 size={18} className="text-blue-600" /> Edit Leave Request
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Editable because no hierarchy stage has approved yet.
                </p>
              </div>
              <button
                onClick={() => setEditingLeave(null)}
                className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleUpdateLeave} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-bold text-slate-600 uppercase mb-1.5">Leave Type</label>
                <select
                  value={editFormData.leave_type}
                  onChange={(e) => setEditFormData({ ...editFormData, leave_type: e.target.value })}
                  className="w-full p-2.5 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 text-sm bg-white"
                >
                  {isStudentFlow ? (
                    <>
                      <option value="home">Home Visit</option>
                      <option value="night_out">Night Out</option>
                      <option value="outing">Day Outing</option>
                      <option value="medical">Medical Leave</option>
                      <option value="other">Other / Special Leave</option>
                    </>
                  ) : (
                    <>
                      <option value="casual">Casual Leave (CL)</option>
                      <option value="sick">Sick Leave (SL)</option>
                      <option value="privilege">Privilege Leave (PL)</option>
                      <option value="half_day">Half Day</option>
                      <option value="comp_off">Comp Off</option>
                      <option value="unpaid">Leave Without Pay</option>
                    </>
                  )}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-600 uppercase mb-1.5">Start Date</label>
                  <input
                    type="date"
                    required
                    value={editFormData.start_date}
                    onChange={(e) => setEditFormData({ ...editFormData, start_date: e.target.value })}
                    className="w-full p-2.5 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-600 uppercase mb-1.5">End Date</label>
                  <input
                    type="date"
                    required
                    value={editFormData.end_date}
                    min={editFormData.start_date}
                    onChange={(e) => setEditFormData({ ...editFormData, end_date: e.target.value })}
                    className="w-full p-2.5 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-600 uppercase mb-1.5">Out Time</label>
                  <input
                    type="time"
                    value={editFormData.start_time}
                    onChange={(e) => setEditFormData({ ...editFormData, start_time: e.target.value })}
                    className="w-full p-2.5 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-600 uppercase mb-1.5">Expected Return</label>
                  <input
                    type="time"
                    value={editFormData.end_time}
                    onChange={(e) => setEditFormData({ ...editFormData, end_time: e.target.value })}
                    className="w-full p-2.5 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-600 uppercase mb-1.5">Reason for Leave</label>
                <textarea
                  required
                  rows={3}
                  value={editFormData.reason}
                  onChange={(e) => setEditFormData({ ...editFormData, reason: e.target.value })}
                  placeholder="Specify reason for leave..."
                  className="w-full p-2.5 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setEditingLeave(null)}
                  className="px-4 py-2 border border-slate-200 text-slate-600 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={editSubmitting}
                  className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-50"
                >
                  {editSubmitting ? 'Saving Changes...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Verified Photo Enlarged Preview Modal */}
      {previewImage && (
        <div 
          className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 z-[110] animate-fadeIn"
          onClick={() => setPreviewImage(null)}
        >
          <div 
            className="bg-white rounded-2xl max-w-sm w-full p-4 shadow-2xl border border-slate-200 flex flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-full flex justify-between items-center mb-3 pb-2 border-b border-slate-100">
              <h4 className="font-bold text-slate-800 text-sm flex items-center gap-1.5">
                <ShieldCheck size={16} className="text-emerald-600" /> Verified Photo Capture
              </h4>
              <button 
                onClick={() => setPreviewImage(null)}
                className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100"
              >
                <X size={18} />
              </button>
            </div>
            <div className="w-64 h-64 rounded-xl overflow-hidden bg-slate-100 border border-slate-200 shadow-inner">
              <img 
                src={previewImage} 
                alt="Face Preview" 
                className="w-full h-full object-cover" 
              />
            </div>
            <p className="text-[11px] text-slate-500 mt-2 font-medium">Captured & verified during approval process</p>
          </div>
        </div>
      )}

      {/* Student Cancel Leave Modal */}
      {cancelModalOpen && cancelTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-rose-100 text-rose-600 rounded-xl">
                  <Ban size={20} />
                </div>
                <div>
                  <h3 className="font-bold text-slate-800 text-base">Cancel Leave Request</h3>
                  <p className="text-xs text-slate-500">Ticket #{cancelTarget.id} · {formatLeaveType(cancelTarget.leave_type)}</p>
                </div>
              </div>
              <button
                onClick={() => { setCancelModalOpen(false); setCancelTarget(null); }}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-md"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mt-4 space-y-3.5">
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-950 leading-relaxed">
                <p className="font-bold mb-1 flex items-center gap-1 text-amber-900">
                  <span>&#9888; Parent Approval Required</span>
                </p>
                Submitting this cancellation will notify your linked parent on their mobile app. Your parent must verify their face scan to authorize the cancellation.
                <div className="mt-2 pt-2 border-t border-amber-200/60 text-[11px] text-amber-900 space-y-1">
                  <p>&#10004; Once approved, all assigned staff are automatically notified via email.</p>
                  <p>&#10004; Your regular attendance will continue to be marked as normal.</p>
                  <p>&#10004; You can re-apply for leave on these dates without conflict.</p>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Reason for Cancellation <span className="text-rose-500">*</span>
                </label>
                <textarea
                  value={cancellationReason}
                  onChange={(e) => setCancellationReason(e.target.value)}
                  rows={3}
                  placeholder="e.g. Plans cancelled, event rescheduled, staying back in campus..."
                  className="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-rose-500 focus:border-rose-500 outline-none transition-all placeholder:text-slate-400"
                />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => { setCancelModalOpen(false); setCancelTarget(null); }}
                disabled={submittingCancel}
                className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50"
              >
                Keep Leave
              </button>
              <button
                type="button"
                onClick={handleConfirmCancel}
                disabled={submittingCancel || !cancellationReason.trim()}
                className="inline-flex items-center gap-2 px-5 py-2 text-sm font-bold text-white bg-rose-600 hover:bg-rose-700 active:bg-rose-800 rounded-xl transition-colors disabled:opacity-50 shadow-sm"
              >
                {submittingCancel ? (
                  <>
                    <RotateCcw size={14} className="animate-spin" />
                    Submitting...
                  </>
                ) : (
                  <>
                    <Ban size={14} />
                    Confirm Cancellation
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LeaveManagement;
