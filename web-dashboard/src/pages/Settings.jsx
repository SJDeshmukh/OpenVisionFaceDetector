import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import {
  Save,
  Bell,
  Lock,
  Database,
  Users as UsersIcon,
  Trash2,
  Edit2,
  Plus,
  X,
  CreditCard,
  FileText,
  RefreshCw,
  MessageSquare,
  QrCode,
  Smartphone,
  Send,
  CalendarClock,
  Clock,
  ArrowRight
} from 'lucide-react';
import { API_URL } from '../config';
import { useSocket } from '../context/SocketContext';

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

const Settings = () => {
  const { user } = useAuth();
  const { socket } = useSocket();

  // System Settings State
  const [workStartTime, setWorkStartTime] = useState("09:00");
  const [lateThreshold, setLateThreshold] = useState("09:30");
  const [voiceGreeting, setVoiceGreeting] = useState(true);
  const [saving, setSaving] = useState(false);
  const [companyShifts, setCompanyShifts] = useState([]);

  const calculateLateTime = (startTime, graceMins = 15) => {
    if (!startTime || typeof startTime !== 'string' || !startTime.includes(':')) return '—';
    const [h, m] = startTime.split(':').map(Number);
    if (isNaN(h) || isNaN(m)) return '—';
    const totalMins = h * 60 + m + Math.max(0, Number(graceMins) || 0);
    const lateH = Math.floor(totalMins / 60) % 24;
    const lateM = totalMins % 60;
    return `${String(lateH).padStart(2, '0')}:${String(lateM).padStart(2, '0')}`;
  };

  // User Management State
  const [systemUsers, setSystemUsers] = useState([]);
  const [showUserModal, setShowUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [userForm, setUserForm] = useState({ username: '', password: '', role: 'user' });

  // Subscription State
  const [subscription, setSubscription] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [refreshingBilling, setRefreshingBilling] = useState(false);

  // WhatsApp Integration State
  const [whatsappSettings, setWhatsappSettings] = useState({
    status: 'disconnected',
    phone_number: '',
    auto_punch_alerts: 1,
    auto_leave_alerts: 1,
    auto_advance_alerts: 1,
    auto_late_alerts: 0
  });
  const [whatsappLoading, setWhatsappLoading] = useState(false);
  const [showQrModal, setShowQrModal] = useState(false);
  const [qrCodeData, setQrCodeData] = useState(null);
  const [qrPolling, setQrPolling] = useState(false);
  const [testPhone, setTestPhone] = useState('');
  const [sendingTest, setSendingTest] = useState(false);
  const [savingWhatsapp, setSavingWhatsapp] = useState(false);

  const getAuthHeaders = () => (user?.token ? { Authorization: `Bearer ${user.token}` } : {});
  const hasWhatsappFeature = (Array.isArray(user?.features) && user.features.includes('whatsapp_alerts')) || user?.role === 'super_admin';
  const hasLateMarkFeature = Array.isArray(user?.features) && user.features.includes('late_mark');

  useEffect(() => {
    fetchSettings();
    if (['vendor_admin', 'admin', 'owner'].includes(user?.role)) {
      fetchSystemUsers();
      fetchSubscription();
      if (hasWhatsappFeature) {
        fetchWhatsappSettings();
      }
    }
  }, [user, hasWhatsappFeature]);

  const fetchWhatsappSettings = async () => {
    try {
      const res = await axios.get(`${API_URL}/whatsapp/settings`, {
        headers: getAuthHeaders()
      });
      if (res.data?.settings) {
        setWhatsappSettings(res.data.settings);
        if (res.data.settings.phone_number) {
          setTestPhone(res.data.settings.phone_number);
        }
      }
    } catch (e) {
      console.error("Error fetching whatsapp settings:", e);
    }
  };

  const handleOpenQrModal = async () => {
    setWhatsappLoading(true);
    setShowQrModal(true);
    setQrCodeData(null);
    try {
      const res = await axios.get(`${API_URL}/whatsapp/qr`, {
        headers: getAuthHeaders()
      });
      if (res.data?.qr_code) {
        setQrCodeData(res.data.qr_code);
        setQrPolling(true);
      } else {
        alert(res.data?.error || "Failed to generate WhatsApp QR code. Make sure WhatsApp service is running.");
      }
    } catch (err) {
      alert("Error contacting WhatsApp service: " + (err.response?.data?.error || err.message));
    } finally {
      setWhatsappLoading(false);
    }
  };

  useEffect(() => {
    let interval = null;
    if (showQrModal && qrPolling) {
      interval = setInterval(async () => {
        try {
          const res = await axios.post(`${API_URL}/whatsapp/sync`, {}, {
            headers: getAuthHeaders()
          });
          if (res.data?.settings?.status === 'connected') {
            setWhatsappSettings(res.data.settings);
            if (res.data.settings.phone_number) {
              setTestPhone(res.data.settings.phone_number);
            }
            setQrPolling(false);
            setShowQrModal(false);
            alert(`WhatsApp successfully connected with +${res.data.settings.phone_number || ''}!`);
          }
        } catch (e) {
          console.error("Polling whatsapp sync error:", e);
        }
      }, 3000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [showQrModal, qrPolling, user?.token]);

  const handleDisconnectWhatsapp = async () => {
    if (!window.confirm("Are you sure you want to disconnect WhatsApp? Automated alerts will stop.")) return;
    try {
      const res = await axios.post(`${API_URL}/whatsapp/disconnect`, {}, {
        headers: getAuthHeaders()
      });
      if (res.data?.settings) {
        setWhatsappSettings(res.data.settings);
      }
      alert("WhatsApp instance disconnected.");
    } catch (err) {
      alert("Error disconnecting: " + (err.response?.data?.error || err.message));
    }
  };

  const handleSaveWhatsappToggles = async (updatedFields) => {
    setSavingWhatsapp(true);
    try {
      const payload = { ...whatsappSettings, ...updatedFields };
      const res = await axios.post(`${API_URL}/whatsapp/settings`, payload, {
        headers: getAuthHeaders()
      });
      if (res.data?.settings) {
        setWhatsappSettings(res.data.settings);
      }
    } catch (err) {
      alert("Failed to save WhatsApp preferences: " + (err.response?.data?.error || err.message));
    } finally {
      setSavingWhatsapp(false);
    }
  };

  const handleSendTestMessage = async () => {
    if (!testPhone) {
      alert("Please enter a phone number to test.");
      return;
    }
    setSendingTest(true);
    try {
      const res = await axios.post(`${API_URL}/whatsapp/send-test`, { phone: testPhone }, {
        headers: getAuthHeaders()
      });
      if (res.data?.success) {
        alert("Test message sent successfully to " + testPhone + "!");
      } else {
        alert("Failed to send: " + (res.data?.error || "Unknown error"));
      }
    } catch (err) {
      alert("Error sending test message: " + (err.response?.data?.error || err.message));
    } finally {
      setSendingTest(false);
    }
  };

  const fetchSubscription = async () => {
    setRefreshingBilling(true);
    try {
      const requestConfig = {
        headers: getAuthHeaders(),
        params: { _ts: Date.now() }
      };
      const [res, invoiceRes] = await Promise.all([
        axios.get(`${API_URL}/vendor/subscription`, requestConfig),
        axios.get(`${API_URL}/vendor/invoices`, requestConfig).catch(() => null)
      ]);
      if (res.data) {
        const { invoices: embeddedInvoices, ...sub } = res.data;
        setSubscription(sub);
        setInvoices(invoiceRes?.data?.invoices || embeddedInvoices || []);
      }
    } catch (error) {
      console.error("Error fetching subscription:", error);
    } finally {
      setRefreshingBilling(false);
    }
  };

  useEffect(() => {
    if (!socket || !['vendor_admin', 'admin', 'owner'].includes(user?.role)) return undefined;
    const handleInvoiceUpdated = (data) => {
      if (String(data?.vendor_id) === String(user?.vendor_id)) fetchSubscription();
    };
    socket.on('invoice_updated', handleInvoiceUpdated);
    return () => socket.off('invoice_updated', handleInvoiceUpdated);
  }, [socket, user?.role, user?.vendor_id]);

  const fetchSettings = async () => {
    try {
      const res = await axios.get(`${API_URL}/settings`, user?.token ? { headers: { Authorization: `Bearer ${user?.token}` } } : undefined);
      const s = res.data;
      if (s) {
        if (s.work_start_time !== undefined) setWorkStartTime(s.work_start_time);
        if (s.late_threshold !== undefined) {
          let lt = s.late_threshold;
          // Auto-sanitize inverted threshold (e.g. 05:59 with 06:00 start)
          if (s.work_start_time && lt < s.work_start_time) {
            try {
              const [h, m] = s.work_start_time.split(':').map(Number);
              const total = h * 60 + m + 15;
              lt = `${String(Math.floor(total / 60) % 24).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
            } catch (e) {}
          }
          setLateThreshold(lt);
        }
        if (s.voice_greeting !== undefined) setVoiceGreeting(String(s.voice_greeting).toLowerCase() === 'true');
      }

      // Fetch active company shifts for Timetable integration preview
      try {
        const compRes = await axios.get(`${API_URL}/companies`, { headers: getAuthHeaders() });
        const compList = compRes.data?.companies || [];
        if (compList.length > 0) {
          const detailRes = await axios.get(`${API_URL}/companies/${compList[0].id}`, { headers: getAuthHeaders() });
          const rawShifts = detailRes.data?.shifts || [];
          setCompanyShifts(Array.isArray(rawShifts) ? rawShifts : []);
        }
      } catch (e) {
        // Silently continue if company shifts not configured
      }
    } catch (error) {
      console.error("Error fetching settings:", error);
    }
  };

  const handleSaveSettings = async () => {
    if (hasLateMarkFeature && workStartTime && lateThreshold && lateThreshold < workStartTime) {
      alert("Late After time cannot be earlier than Work Start Time. Please adjust the timings.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        work_start_time: workStartTime,
        voice_greeting: voiceGreeting,
      };
      if (hasLateMarkFeature) payload.late_threshold = lateThreshold;
      await axios.post(`${API_URL}/settings`, payload, {
        headers: getAuthHeaders()
      });
      alert("Settings saved successfully!");
    } catch (error) {
      console.error("Error saving settings:", error);
      alert(error.response?.data?.error || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const fetchSystemUsers = async () => {
    try {
      const res = await axios.get(`${API_URL}/users`, { headers: getAuthHeaders() });
      setSystemUsers(res.data.users);
    } catch (error) {
      console.error("Error fetching system users:", error);
    }
  };

  const handleSaveUser = async () => {
    try {
      if (editingUser) {
        // Update existing user
        const payload = { username: userForm.username.trim().toLowerCase() };
        if (userForm.password) payload.password = userForm.password;
        payload.role = userForm.role;

        await axios.put(`${API_URL}/users/${encodeURIComponent(editingUser.username)}`, payload, {
          headers: getAuthHeaders()
        });
      } else {
        // Create new user
        await axios.post(`${API_URL}/users`, userForm, {
          headers: getAuthHeaders()
        });
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
      await axios.delete(`${API_URL}/users/${username}`, {
        headers: getAuthHeaders()
      });
      fetchSystemUsers();
    } catch (error) {
      alert(error.response?.data?.error || "Delete failed");
    }
  };

  const openEditModal = (u) => {
    setEditingUser(u);
    setUserForm({ username: u.login_email || '', password: '', role: u.role }); // Password blank for no change
    setShowUserModal(true);
  };

  const openAddModal = () => {
    setEditingUser(null);
    setUserForm({ username: '', password: '', role: 'user' });
    setShowUserModal(true);
  };


  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">System Configuration</h1>
          <p className="text-slate-500">Manage attendance settings for this business.</p>
        </div>
        {['vendor_admin', 'admin', 'owner'].includes(user?.role) && <button
          onClick={handleSaveSettings}
          disabled={saving}
          className="flex items-center space-x-2 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors shadow-sm"
        >
          <Save size={18} />
          <span>{saving ? 'Saving...' : 'Save Changes'}</span>
        </button>}
      </div>

      {['vendor_admin', 'admin', 'owner'].includes(user?.role) && subscription && (
        <Section title="Subscription & Billing" icon={CreditCard}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-blue-50 p-4 rounded-lg border border-blue-100">
              <h4 className="font-semibold text-blue-900 mb-2">Current Plan</h4>
              <div className="space-y-2 text-sm text-blue-800">
                <div className="flex justify-between">
                  <span>Start Date:</span>
                  <span className="font-medium">{subscription.start_date}</span>
                </div>
                <div className="flex justify-between">
                  <span>End Date:</span>
                  <span className="font-medium">{subscription.end_date}</span>
                </div>
                <div className="flex justify-between">
                  <span>Max Users:</span>
                  <span className="font-medium">{subscription.max_users}</span>
                </div>
                <div className="flex justify-between">
                  <span>Cost Per User:</span>
                  <span className="font-medium">₹{subscription.cost_per_user}/mo</span>
                </div>
              </div>
            </div>

            <div>
              <h4 className="font-semibold text-slate-800 mb-3 flex items-center gap-2">
                <FileText size={16} className="text-slate-500" /> Invoices
                <button
                  type="button"
                  onClick={fetchSubscription}
                  disabled={refreshingBilling}
                  className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 disabled:opacity-50"
                  title="Refresh invoices"
                >
                  <RefreshCw size={13} className={refreshingBilling ? 'animate-spin' : ''} />
                  Refresh
                </button>
              </h4>
              <div className="max-h-40 overflow-y-auto">
                <table className="w-full text-sm text-left">
                  <thead className="bg-slate-50 text-slate-500 sticky top-0">
                    <tr>
                      <th className="p-2 font-medium">Date</th>
                      <th className="p-2 font-medium">Amount</th>
                      <th className="p-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {invoices.length === 0 ? (
                      <tr><td colSpan="3" className="p-2 text-center text-slate-400">No invoices found</td></tr>
                    ) : (
                      invoices.map(inv => (
                        <tr key={inv.id}>
                          <td className="p-2 text-slate-700">{inv.invoice_date}</td>
                          <td className="p-2 text-slate-700">
                            <div className="font-medium">₹{inv.amount}</div>
                            {inv.details && (
                              <div className="text-[10px] text-slate-500 leading-tight">
                                {(() => {
                                  try {
                                    const d = JSON.parse(inv.details);
                                    const deviceCount = d.active_users ?? d.max_devices ?? 0;
                                    return (
                                      <>
                                        {deviceCount > 0 && <div>{deviceCount} devices</div>}
                                        {Number(d.max_employees || 0) > 0 && <div>{d.max_employees} employees</div>}
                                        {d.setup_fee > 0 && <div>+ Setup</div>}
                                      </>
                                    );
                                  } catch (e) { return null; }
                                })()}
                              </div>
                            )}
                          </td>
                          <td className="p-2">
                            <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${inv.status === 'paid' ? 'bg-green-100 text-green-700' :
                                inv.status === 'overdue' ? 'bg-red-100 text-red-700' :
                                  'bg-yellow-100 text-yellow-700'
                              }`}>
                              {inv.status.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </Section>
      )}

      {['vendor_admin', 'admin', 'owner'].includes(user?.role) && hasWhatsappFeature && (
        <Section title="WhatsApp Gateway" icon={MessageSquare}>
          <div className="space-y-6">
            {/* Status & Connection Banner */}
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center p-4 rounded-xl border border-slate-200 bg-slate-50 gap-4">
              <div className="flex items-center gap-3">
                <div className={`p-3 rounded-xl ${whatsappSettings.status === 'connected' ? 'bg-emerald-100 text-emerald-600' : 'bg-slate-200 text-slate-600'}`}>
                  <Smartphone size={24} />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h4 className="font-bold text-slate-800">
                      {whatsappSettings.status === 'connected'
                        ? `Connected: +${whatsappSettings.phone_number || 'Business Account'}`
                        : 'WhatsApp Not Connected'}
                    </h4>
                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                      whatsappSettings.status === 'connected'
                        ? 'bg-emerald-100 text-emerald-700'
                        : whatsappSettings.status === 'connecting'
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-slate-200 text-slate-600'
                    }`}>
                      {whatsappSettings.status === 'connected' ? '● Active' : whatsappSettings.status === 'connecting' ? '○ Pairing...' : '○ Disconnected'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {whatsappSettings.status === 'connected'
                      ? 'Automated alerts for biometric punches, leaves, and advances are actively running.'
                      : 'Scan QR code with your business phone to enable automated WhatsApp notifications.'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 self-end sm:self-auto">
                {whatsappSettings.status === 'connected' ? (
                  <>
                    <button
                      type="button"
                      onClick={fetchWhatsappSettings}
                      className="p-2 border border-slate-200 hover:bg-slate-100 rounded-lg text-slate-600 transition-colors"
                      title="Refresh Status"
                    >
                      <RefreshCw size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={handleDisconnectWhatsapp}
                      className="px-4 py-2 border border-red-200 text-red-600 hover:bg-red-50 rounded-lg text-xs font-bold transition-colors"
                    >
                      Disconnect
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={handleOpenQrModal}
                    disabled={whatsappLoading}
                    className="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold shadow-sm transition-all"
                  >
                    <QrCode size={16} />
                    <span>{whatsappLoading ? 'Generating QR...' : 'Link WhatsApp via QR'}</span>
                  </button>
                )}
              </div>
            </div>

            {/* Notification Toggles */}
            <div className="space-y-3">
              <h5 className="text-sm font-semibold text-slate-700">Automated Notification Rules</h5>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <label className="flex items-start gap-3 p-3 rounded-xl border border-slate-200 hover:bg-slate-50 cursor-pointer transition-colors">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={Boolean(whatsappSettings.auto_punch_alerts)}
                    onChange={(e) => {
                      const val = e.target.checked ? 1 : 0;
                      setWhatsappSettings(prev => ({ ...prev, auto_punch_alerts: val }));
                      handleSaveWhatsappToggles({ auto_punch_alerts: val });
                    }}
                  />
                  <div>
                    <span className="text-sm font-medium text-slate-800">Real-Time Attendance Punch Alerts</span>
                    <p className="text-xs text-slate-500">Sends instant WhatsApp confirmation to employee (and parent in campus mode) on kiosk punch.</p>
                  </div>
                </label>

                <label className="flex items-start gap-3 p-3 rounded-xl border border-slate-200 hover:bg-slate-50 cursor-pointer transition-colors">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={Boolean(whatsappSettings.auto_leave_alerts)}
                    onChange={(e) => {
                      const val = e.target.checked ? 1 : 0;
                      setWhatsappSettings(prev => ({ ...prev, auto_leave_alerts: val }));
                      handleSaveWhatsappToggles({ auto_leave_alerts: val });
                    }}
                  />
                  <div>
                    <span className="text-sm font-medium text-slate-800">Leave & Gate-Pass Alerts</span>
                    <p className="text-xs text-slate-500">Notifies employees or students when leaves or gate-passes are approved or rejected.</p>
                  </div>
                </label>

                <label className="flex items-start gap-3 p-3 rounded-xl border border-slate-200 hover:bg-slate-50 cursor-pointer transition-colors">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={Boolean(whatsappSettings.auto_advance_alerts)}
                    onChange={(e) => {
                      const val = e.target.checked ? 1 : 0;
                      setWhatsappSettings(prev => ({ ...prev, auto_advance_alerts: val }));
                      handleSaveWhatsappToggles({ auto_advance_alerts: val });
                    }}
                  />
                  <div>
                    <span className="text-sm font-medium text-slate-800">Owner Advance Approvals</span>
                    <p className="text-xs text-slate-500">Sends instant WhatsApp notification when salary advances are requested and approved.</p>
                  </div>
                </label>

                {hasLateMarkFeature && <label className="flex items-start gap-3 p-3 rounded-xl border border-slate-200 hover:bg-slate-50 cursor-pointer transition-colors">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={Boolean(whatsappSettings.auto_late_alerts)}
                    onChange={(e) => {
                      const val = e.target.checked ? 1 : 0;
                      setWhatsappSettings(prev => ({ ...prev, auto_late_alerts: val }));
                      handleSaveWhatsappToggles({ auto_late_alerts: val });
                    }}
                  />
                  <div>
                    <span className="text-sm font-medium text-slate-800">Late Arrival Warning</span>
                    <p className="text-xs text-slate-500">Alerts employee when they clock in past the configured grace period.</p>
                  </div>
                </label>}
              </div>
            </div>

            {/* Test Message Panel (when connected) */}
            {whatsappSettings.status === 'connected' && (
              <div className="p-4 rounded-xl border border-slate-200 bg-slate-50 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div className="flex-1">
                  <label className="block text-xs font-semibold text-slate-700 mb-1">Verify Delivery (Test WhatsApp)</label>
                  <div className="flex items-center gap-2 max-w-sm">
                    <input
                      type="tel"
                      placeholder="e.g. +919876543210"
                      value={testPhone}
                      onChange={(e) => {
                        const raw = e.target.value;
                        const formatted = raw.startsWith('+')
                          ? '+' + raw.slice(1).replace(/\D/g, '')
                          : raw.replace(/[^\d+]/g, '');
                        setTestPhone(formatted);
                      }}
                      className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs outline-none focus:ring-2 focus:ring-blue-500 bg-white font-mono"
                    />
                    <button
                      type="button"
                      onClick={handleSendTestMessage}
                      disabled={sendingTest}
                      className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-medium shrink-0 flex items-center gap-1 shadow-sm"
                    >
                      <Send size={12} />
                      <span>{sendingTest ? 'Sending...' : 'Send Test'}</span>
                    </button>
                  </div>
                </div>
                <span className="text-[11px] text-slate-400">TapInX Automated Alerts</span>
              </div>
            )}
          </div>
        </Section>
      )}

      {['vendor_admin', 'admin'].includes(user?.role) && (
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
                  <th className="pb-3 font-semibold text-slate-600 text-sm">Login Email</th>
                  <th className="pb-3 font-semibold text-slate-600 text-sm">Role</th>
                  <th className="pb-3 font-semibold text-slate-600 text-sm text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="text-slate-700">
                {systemUsers.map((u) => (
                  <tr key={u.username} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="py-3 text-sm">
                      <div className="font-medium text-slate-700">
                        {u.login_email || 'Email required'}
                      </div>
                      {u.person_name && <div className="text-xs text-slate-400">{u.person_name}</div>}
                      {u.requires_email_update && (
                        <div className="text-xs font-medium text-amber-600">Update required before login</div>
                      )}
                    </td>
                    <td className="py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${u.role === 'admin' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'
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

      <Section 
        title="Attendance & Shift Rules" 
        icon={CalendarClock}
        action={
          <Link 
            to="/timetable" 
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg text-sm font-semibold transition-colors border border-blue-100 shadow-sm"
          >
            <CalendarClock size={16} />
            <span>Manage in Timetable</span>
          </Link>
        }
      >
        {companyShifts && companyShifts.length > 0 ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-800">Active Timetable Shifts</p>
                <p className="text-xs text-slate-500">Attendance is governed by the shifts configured in your Timetable.</p>
              </div>
              <span className="text-xs font-semibold px-2.5 py-1 bg-green-50 text-green-700 border border-green-200 rounded-full">
                {companyShifts.filter(s => s.active !== false).length} Active Shifts
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {companyShifts.map((shift, idx) => (
                <div key={shift.id || idx} className="p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-2">
                  <div className="flex justify-between items-start">
                    <span className="font-semibold text-slate-800 text-sm">{shift.name}</span>
                    <span className={`text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded ${shift.active !== false ? 'bg-green-100 text-green-800' : 'bg-slate-200 text-slate-600'}`}>
                      {shift.active !== false ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <div className="flex items-center text-xs text-slate-600 space-x-1.5">
                    <Clock size={13} className="text-slate-400" />
                    <span>{shift.start_time} - {shift.end_time}</span>
                  </div>
                  {hasLateMarkFeature && (
                    <div className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 px-2 py-1 rounded font-medium">
                      Late after: <span className="font-bold">{calculateLateTime(shift.start_time, shift.grace_period_mins ?? 15)}</span> ({shift.grace_period_mins ?? 15}m grace)
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="pt-3 border-t border-slate-100">
              <details className="group">
                <summary className="text-xs font-medium text-slate-500 hover:text-slate-700 cursor-pointer select-none">
                  Advanced: Fallback Rule (For staff without an assigned shift)
                </summary>
                <div className={`grid grid-cols-1 ${hasLateMarkFeature ? 'sm:grid-cols-2' : ''} gap-5 mt-3 pt-2`}>
                  <div>
                    <label htmlFor="work-start-time" className="block text-xs font-semibold text-slate-700 mb-1.5">Fallback Work Start</label>
                    <input
                      id="work-start-time"
                      type="time"
                      value={workStartTime}
                      onChange={(e) => setWorkStartTime(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
                    />
                  </div>
                  {hasLateMarkFeature && <div>
                    <label htmlFor="late-threshold" className="block text-xs font-semibold text-slate-700 mb-1.5">Fallback Late After</label>
                    <input
                      id="late-threshold"
                      type="time"
                      value={lateThreshold}
                      onChange={(e) => setLateThreshold(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
                    />
                  </div>}
                </div>
              </details>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="p-4 bg-blue-50/70 border border-blue-100 rounded-xl flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-blue-900">Want to use multi-shift schedules?</p>
                <p className="text-xs text-blue-700 mt-0.5">Create shifts and assign staff in the Timetable tab for automatic attendance rules.</p>
              </div>
              <Link 
                to="/timetable" 
                className="px-3.5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors flex items-center space-x-1"
              >
                <span>Set Up Shifts</span>
                <ArrowRight size={14} />
              </Link>
            </div>

            <div className={`grid grid-cols-1 ${hasLateMarkFeature ? 'sm:grid-cols-2' : ''} gap-5`}>
              <div>
                <label htmlFor="work-start-time" className="block text-sm font-semibold text-slate-700 mb-2">Work Start Time</label>
                <input
                  id="work-start-time"
                  type="time"
                  value={workStartTime}
                  onChange={(e) => setWorkStartTime(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg"
                />
              </div>
              {hasLateMarkFeature && <div>
                <label htmlFor="late-threshold" className="block text-sm font-semibold text-slate-700 mb-2">Late After</label>
                <input
                  id="late-threshold"
                  type="time"
                  value={lateThreshold}
                  onChange={(e) => setLateThreshold(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg"
                />
              </div>}
            </div>
            {hasLateMarkFeature && <p className="text-xs text-slate-500">A check-in after the configured late time is marked late for this business.</p>}
          </div>
        )}
      </Section>



      <Section title="Notifications & Interface" icon={Bell}>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-slate-800">Voice Greeting</p>
              <p className="text-xs text-slate-500">Play text-to-speech greeting upon successful recognition</p>
            </div>
            <div className="relative inline-block w-12 mr-2 align-middle select-none transition duration-200 ease-in">
              <input
                type="checkbox"
                name="toggle"
                id="toggle"
                checked={voiceGreeting}
                onChange={(e) => setVoiceGreeting(e.target.checked)}
                className="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 appearance-none cursor-pointer checked:right-0 checked:border-green-400"
              />
              <label htmlFor="toggle" className="toggle-label block overflow-hidden h-6 rounded-full bg-gray-300 cursor-pointer checked:bg-green-400"></label>
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
                <label className="block text-sm font-medium text-slate-700 mb-1">Login Email</label>
                <input
                  type="email"
                  required
                  value={userForm.username}
                  onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="Enter email address"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  {editingUser ? 'New Password (leave blank to keep)' : 'Password'}
                </label>
                <input
                  type="password"
                  minLength={8}
                  value={userForm.password}
                  onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="Enter password"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Role</label>
                <select
                  value={userForm.role}
                  onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
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

      {/* WhatsApp QR Modal */}
      {showQrModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl p-6 max-w-md w-full text-center space-y-4 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex justify-between items-center border-b border-slate-100 pb-3">
              <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                <MessageSquare className="text-emerald-600" />
                Link Company WhatsApp
              </h3>
              <button
                onClick={() => { setShowQrModal(false); setQrPolling(false); }}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X size={20} />
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed text-left">
              1. Open WhatsApp on your business phone.<br />
              2. Tap <strong>Settings</strong> &gt; <strong>Linked Devices</strong> &gt; <strong>Link a Device</strong>.<br />
              3. Point your camera at the QR code below:
            </p>

            <div className="flex justify-center p-4 bg-slate-50 rounded-2xl border border-slate-100 min-h-[250px] items-center">
              {whatsappLoading ? (
                <div className="flex flex-col items-center gap-2 text-slate-400">
                  <RefreshCw className="animate-spin text-emerald-600" size={32} />
                  <span className="text-xs font-medium">Generating WhatsApp QR Code...</span>
                </div>
              ) : qrCodeData ? (
                <div className="flex flex-col items-center gap-2">
                  <img
                    src={qrCodeData.startsWith('data:') ? qrCodeData : `data:image/png;base64,${qrCodeData}`}
                    alt="WhatsApp QR Code"
                    className="w-56 h-56 rounded-lg shadow-sm"
                  />
                  <span className="text-[11px] text-slate-500 font-mono flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
                    Waiting for scan... (Auto-refreshing)
                  </span>
                </div>
              ) : (
                <div className="text-xs text-red-500">
                  Unable to generate QR Code. Please check server gateway connection.
                </div>
              )}
            </div>

            <button
              onClick={() => { setShowQrModal(false); setQrPolling(false); fetchWhatsappSettings(); }}
              className="w-full py-2.5 bg-slate-800 hover:bg-slate-900 text-white rounded-xl text-sm font-semibold transition-all shadow-md"
            >
              Done Scanning
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default Settings;
