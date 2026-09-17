import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import {
  FileText,
  Download,
  FileSpreadsheet,
  Calendar,
  Filter,
  BarChart2,
  PieChart as PieChartIcon,
  RefreshCw,
  Mail,
  Send,
  X,
  Lock,
  Users,
  CheckCircle2,
  AlertCircle,
  Loader2
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend
} from 'recharts';
import { API_URL } from '../config';
import { getBusinessTerminology, usesStudentRecords } from '../lib/businessTerminology';

const COLORS = ['#22c55e', '#f59e0b', '#ef4444'];

const EMPTY_FILTER_OPTIONS = {
  departments: [],
  designations: [],
  shifts: [],
  phones: [],
  visible_standard_filters: {},
  standard_filter_labels: {},
  dynamic_filters: {},
  matching_employee_count: 0,
};

const normalizeFiltersForOptions = (currentFilters, options) => {
  const normalized = { ...currentFilters };
  const visible = options?.visible_standard_filters || {};
  const optionLists = {
    department: options?.departments || [],
    designation: options?.designations || [],
    shift: options?.shifts || [],
    phone: options?.phones || [],
  };

  Object.entries(optionLists).forEach(([key, values]) => {
    const allowed = new Set(values.map(String));
    if (!visible[key] || (normalized[key] && !allowed.has(String(normalized[key])))) {
      normalized[key] = '';
    }
  });

  const dynamic = { ...(normalized.dynamic || {}) };
  Object.entries(dynamic).forEach(([key, value]) => {
    const config = options?.dynamic_filters?.[key];
    const allowed = new Set((config?.options || []).map(String));
    if (!config || (value && !allowed.has(String(value)))) delete dynamic[key];
  });
  normalized.dynamic = dynamic;
  return normalized;
};

const Reports = () => {
  const { user } = useAuth();
  const terminology = getBusinessTerminology(user?.vertical);
  const schoolFlow = usesStudentRecords(user?.vertical);
  const [personType, setPersonType] = useState('student');
  const personLabelPlural = personType === 'faculty' && schoolFlow ? terminology.staffPlural : terminology.people;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [emailSending, setEmailSending] = useState(false);
  const [emailNotice, setEmailNotice] = useState(null);
  const [employeeReportModalOpen, setEmployeeReportModalOpen] = useState(false);
  const [employeeReportMonth, setEmployeeReportMonth] = useState('');
  const [employeeReportFilters, setEmployeeReportFilters] = useState({
    department: '',
    designation: '',
    shift: '',
    phone: '',
    dynamic: {}
  });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [analytics, setAnalytics] = useState({
    pie_data: [],
    bar_data: [],
    summary: {
      total_users: 0,
      total_students: 0,
      total_faculty: 0,
      present_today: 0,
      absent_today: 0,
      late_today: 0
    }
  });

  const [filterOptions, setFilterOptions] = useState(EMPTY_FILTER_OPTIONS);
  const [employeeFilterOptions, setEmployeeFilterOptions] = useState(EMPTY_FILTER_OPTIONS);
  const [filters, setFilters] = useState({
    startDate: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    endDate: new Date().toISOString().split('T')[0],
    department: '',
    designation: '',
    shift: '',
    phone: '',
    type: 'detailed',
    dynamic: {}
  });
  const filtersRef = useRef(filters);
  const filterRequestRef = useRef(0);
  const employeeFilterRequestRef = useRef(0);
  const recipientPreviewRequestRef = useRef(0);
  const reportStatusTimerRef = useRef(null);
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  useEffect(() => () => {
    if (reportStatusTimerRef.current) clearTimeout(reportStatusTimerRef.current);
  }, []);

  useEffect(() => {
    fetchAnalytics();
    fetchFilters(filtersRef.current);
  }, [personType, user?.vendor_id]);

  useEffect(() => {
    const t = setTimeout(() => fetchFilters(filtersRef.current), 250);
    return () => clearTimeout(t);
  }, [filters, personType]);

  const filterParams = (activeFilters) => {
    const f = activeFilters || {};
    const params = new URLSearchParams();
    if (schoolFlow) params.append('person_type', personType);
    ['department', 'designation', 'shift', 'phone'].forEach((key) => {
      if (f[key]) params.append(key, f[key]);
    });
    Object.entries(f.dynamic || {}).forEach(([key, value]) => {
      if (value) params.append(`dynamic_${key}`, value);
    });
    return params;
  };

  const requestFilterOptions = async (activeFilters) => {
    const params = filterParams(activeFilters);
    const response = await axios.get(`${API_URL}/reports/filters?${params.toString()}`);
    return { ...EMPTY_FILTER_OPTIONS, ...(response.data || {}) };
  };

  const fetchFilters = async (activeFilters) => {
    const requestId = ++filterRequestRef.current;
    try {
      const nextOptions = await requestFilterOptions(activeFilters);
      if (requestId !== filterRequestRef.current) return activeFilters;
      setFilterOptions(nextOptions);
      const current = filtersRef.current;
      const nextFilters = normalizeFiltersForOptions(current, nextOptions);
      if (JSON.stringify(nextFilters) !== JSON.stringify(current)) setFilters(nextFilters);
      return nextFilters;
    } catch (requestError) {
      console.error("Error fetching filters:", requestError);
      return activeFilters;
    }
  };

  const fetchEmployeeFilterOptions = async (activeFilters) => {
    const requestId = ++employeeFilterRequestRef.current;
    try {
      const nextOptions = await requestFilterOptions(activeFilters);
      if (requestId !== employeeFilterRequestRef.current) return null;
      const normalized = normalizeFiltersForOptions(activeFilters, nextOptions);
      setEmployeeFilterOptions(nextOptions);
      setEmployeeReportFilters(normalized);
      return normalized;
    } catch (requestError) {
      console.error('Error fetching employee report filters:', requestError);
      return activeFilters;
    }
  };

  const fetchAnalytics = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_URL}/reports/analytics`, {
        params: schoolFlow ? { person_type: personType } : {},
      });
      setAnalytics(res.data);
      setError(null);
    } catch (error) {
      console.error("Error fetching analytics:", error);
      if (error.response && error.response.status === 403) {
        setError(error.response.data.error || "Access Denied");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = (days = 30) => {
    const endDate = new Date().toISOString().split('T')[0];
    const startDate = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().split('T')[0];

    let url = `${API_URL}/reports/export?start_date=${startDate}&end_date=${endDate}`;
    if (schoolFlow) url += `&person_type=${personType}`;
    if (user?.token) {
      url += `&token=${user.token}`;
    }
    window.location.href = url;
  };

  const handleCustomExport = () => {
    const params = new URLSearchParams();
    params.append('start_date', filters.startDate);
    params.append('end_date', filters.endDate);
    if (schoolFlow) params.append('person_type', personType);
    if (filters.department) params.append('department', filters.department);
    if (filters.designation) params.append('designation', filters.designation);
    if (filters.shift) params.append('shift', filters.shift);
    if (filters.phone) params.append('phone', filters.phone);
    params.append('type', filters.type);
    Object.entries(filters.dynamic || {}).forEach(([key, value]) => {
      if (value) {
        params.append(`dynamic_${key}`, value);
      }
    });

    if (user?.token) {
      params.append('token', user.token);
    }

    const endpoint = filters.type === 'summary'
      ? `${API_URL}/reports/payroll/export-daily`
      : `${API_URL}/reports/export`;

    window.location.href = `${endpoint}?${params.toString()}`;
  };

  const handleExcelExport = () => {
    const params = new URLSearchParams();
    params.append('start_date', filters.startDate);
    params.append('end_date', filters.endDate);
    if (schoolFlow) params.append('person_type', personType);
    if (filters.department) params.append('department', filters.department);
    if (filters.designation) params.append('designation', filters.designation);
    if (filters.shift) params.append('shift', filters.shift);
    if (filters.phone) params.append('phone', filters.phone);
    Object.entries(filters.dynamic || {}).forEach(([key, value]) => {
      if (value) params.append(`dynamic_${key}`, value);
    });
    if (user?.token) params.append('token', user.token);
    window.location.href = `${API_URL}/reports/payroll/export-excel?${params.toString()}`;
  };

  const selectedReportMonth = (filters.endDate || new Date().toISOString().split('T')[0]).slice(0, 7);
  const selectedReportMonthLabel = new Date(`${selectedReportMonth}-01T00:00:00`).toLocaleDateString(undefined, {
    month: 'long', year: 'numeric'
  });
  const hasEmployeeReportsFeature = user?.role === 'super_admin' || Boolean(user?.features?.includes('employee_reports'));
  const hasLateMarkFeature = Boolean(user?.features?.includes('late_mark'));
  const canSendEmployeeReports = ['super_admin', 'vendor_admin', 'admin', 'owner'].includes(user?.role);

  const fetchRecipientPreview = async (targetMonth, activeFilters) => {
    const requestId = ++recipientPreviewRequestRef.current;
    setPreviewLoading(true);
    try {
      const response = await axios.post(`${API_URL}/reports/email-employees/preview`, {
        month: targetMonth || selectedReportMonth,
        person_type: schoolFlow ? personType : undefined,
        filters: activeFilters,
      });
      if (requestId === recipientPreviewRequestRef.current) setPreviewData(response.data);
    } catch (err) {
      console.error('Failed to preview recipient count:', err);
      if (requestId === recipientPreviewRequestRef.current) setPreviewData(null);
    } finally {
      if (requestId === recipientPreviewRequestRef.current) setPreviewLoading(false);
    }
  };

  const updateEmployeeReportFilters = async (updated) => {
    setEmployeeReportFilters(updated);
    const normalized = await fetchEmployeeFilterOptions(updated);
    if (normalized) await fetchRecipientPreview(employeeReportMonth, normalized);
  };

  const handleOpenEmployeeReportsModal = () => {
    setEmailNotice(null);
    const initialMonth = selectedReportMonth;
    const initialFilters = {
      department: filters.department || '',
      designation: filters.designation || '',
      shift: filters.shift || '',
      phone: filters.phone || '',
      dynamic: { ...(filters.dynamic || {}) }
    };
    setEmployeeReportMonth(initialMonth);
    setEmployeeReportFilters(initialFilters);
    setEmployeeFilterOptions(filterOptions);
    setEmployeeReportModalOpen(true);
    // Opening the modal must not wait for the filter/recipient preview request.
    // Keeping this work detached also prevents a slow first request from making
    // the button appear to need a second click.
    void (async () => {
      const normalized = await fetchEmployeeFilterOptions(initialFilters);
      if (normalized) await fetchRecipientPreview(initialMonth, normalized);
    })();
  };

  const sendEmployeeReports = async () => {
    setEmailSending(true);
    setEmailNotice(null);
    try {
      const idempotencyKey = globalThis.crypto?.randomUUID?.()
        || `report-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const response = await axios.post(
        `${API_URL}/reports/email-employees`,
        {
          month: employeeReportMonth || selectedReportMonth,
          person_type: schoolFlow ? personType : undefined,
          filters: employeeReportFilters,
        },
        { headers: { 'Idempotency-Key': idempotencyKey } },
      );
      setEmployeeReportModalOpen(false);
      setEmailNotice({
        type: 'success',
        title: 'Reports Queued',
        message: `${response.data.recipient_count} employee report${response.data.recipient_count === 1 ? '' : 's'} queued for email.`,
      });
      if (response.data.queue_backend === 'lambda_sqs' && response.data.task_id) {
        const pollStatus = async (attempt = 0) => {
          try {
            const statusResponse = await axios.get(
              `${API_URL}/reports/email-employees/status/${encodeURIComponent(response.data.task_id)}`,
            );
            const batch = statusResponse.data;
            if (batch.status === 'sent') {
              setEmailNotice({
                type: 'success',
                title: 'Reports Delivered',
                message: `All ${batch.total} employee reports were delivered successfully.`,
              });
              return;
            }
            if (batch.status === 'failed') {
              setEmailNotice({
                type: attempt >= 40 ? 'error' : 'success',
                title: attempt >= 40 ? 'Report Delivery Failed' : 'Retrying Report Delivery',
                message: attempt >= 40
                  ? `${batch.counts?.failed || 0} employee report deliveries failed. Check System Health for details.`
                  : `${batch.counts?.failed || 0} deliveries encountered an error and are being retried.`,
              });
              if (attempt >= 40) return;
            } else {
              setEmailNotice({
                type: 'success',
                title: 'Sending Reports',
                message: `${batch.counts?.sent || 0} of ${batch.total} employee reports delivered.`,
              });
            }
          } catch (statusError) {
            // A 404 is expected briefly while the DB Lambda creates delivery rows.
            if (statusError.response?.status !== 404) {
              console.error('Failed to read employee report delivery status:', statusError);
            }
          }
          if (attempt < 40) {
            reportStatusTimerRef.current = setTimeout(() => pollStatus(attempt + 1), 3000);
          }
        };
        reportStatusTimerRef.current = setTimeout(() => pollStatus(), 1500);
      }
    } catch (requestError) {
      setEmailNotice({
        type: 'error',
        title: 'Error',
        message: requestError.response?.data?.error || 'Could not queue employee report emails.',
      });
    } finally {
      setEmailSending(false);
    }
  };

  return (
    <div className="space-y-8">
      {/* Notification Alert Toast */}
      {emailNotice && (
        <div className="fixed top-5 right-5 z-50 w-[min(92vw,26rem)] rounded-xl border border-slate-200 bg-white p-4 shadow-2xl" role="status">
          <div className="flex items-start gap-3">
            <div className={`mt-0.5 rounded-full p-2 ${emailNotice?.type === 'error' ? 'bg-red-100 text-red-600' : 'bg-emerald-100 text-emerald-600'}`}>
              {emailNotice?.type === 'error' ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
            </div>
            <div className="min-w-0 flex-1 pr-6">
              <p className="font-bold text-slate-900">{emailNotice?.title || (emailNotice?.type === 'error' ? 'Error' : 'Reports Queued')}</p>
              <p className={`mt-1 text-sm font-medium ${emailNotice?.type === 'error' ? 'text-red-700' : 'text-slate-600'}`}>
                {emailNotice?.message}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setEmailNotice(null)}
              className="absolute right-3 top-3 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              aria-label="Close notification"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Interactive Employee Reports Filter Modal */}
      {employeeReportModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="relative w-full max-w-2xl rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden my-8">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-gradient-to-r from-violet-50 to-indigo-50">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-violet-600 text-white rounded-xl shadow-md">
                  <Mail size={22} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">Report to Each Employee</h3>
                  <p className="text-xs text-slate-500">Send personalized monthly attendance &amp; wage reports via email</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setEmployeeReportModalOpen(false)}
                className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-white rounded-lg transition-colors"
                aria-label="Close modal"
              >
                <X size={20} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 space-y-6 max-h-[75vh] overflow-y-auto">
              {/* Month Selector */}
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-600 mb-1.5">
                  Select Report Month
                </label>
                <input
                  type="month"
                  value={employeeReportMonth}
                  onChange={(e) => {
                    const newMonth = e.target.value;
                    setEmployeeReportMonth(newMonth);
                    fetchRecipientPreview(newMonth, employeeReportFilters);
                  }}
                  className="w-full sm:w-64 rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-800 focus:border-violet-500 focus:ring-2 focus:ring-violet-200"
                />
              </div>

              {/* Filter Section */}
              <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold text-slate-700">
                    <Filter size={16} className="text-violet-600" />
                    <span>Filter Recipients by Registry Fields</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      const cleared = { department: '', designation: '', shift: '', phone: '', dynamic: {} };
                      updateEmployeeReportFilters(cleared);
                    }}
                    className="text-xs text-violet-600 hover:text-violet-800 font-semibold"
                  >
                    Clear Filters (Target All)
                  </button>
                </div>

                <p className="text-xs font-medium text-slate-500">
                  {employeeFilterOptions.matching_employee_count || 0} registered {personLabelPlural.toLowerCase()} match the selected filters.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                  {/* Department */}
                  {employeeFilterOptions.visible_standard_filters?.department && <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      {employeeFilterOptions.standard_filter_labels?.department || 'Department'}
                    </label>
                    <select
                      value={employeeReportFilters.department}
                      onChange={(e) => {
                        const updated = { ...employeeReportFilters, department: e.target.value };
                        updateEmployeeReportFilters(updated);
                      }}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-violet-500 focus:ring-2 focus:ring-violet-200"
                    >
                      <option value="">All Departments</option>
                      {(employeeFilterOptions.departments || []).map((dept) => (
                        <option key={dept} value={dept}>{dept}</option>
                      ))}
                    </select>
                  </div>}

                  {/* Designation */}
                  {employeeFilterOptions.visible_standard_filters?.designation && <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      {employeeFilterOptions.standard_filter_labels?.designation || 'Designation'}
                    </label>
                    <select
                      value={employeeReportFilters.designation}
                      onChange={(e) => {
                        const updated = { ...employeeReportFilters, designation: e.target.value };
                        updateEmployeeReportFilters(updated);
                      }}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-violet-500 focus:ring-2 focus:ring-violet-200"
                    >
                      <option value="">All Designations</option>
                      {(employeeFilterOptions.designations || []).map((desig) => (
                        <option key={desig} value={desig}>{desig}</option>
                      ))}
                    </select>
                  </div>}

                  {/* Shift */}
                  {employeeFilterOptions.visible_standard_filters?.shift && <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      {employeeFilterOptions.standard_filter_labels?.shift || 'Shift'}
                    </label>
                    <select
                      value={employeeReportFilters.shift}
                      onChange={(e) => {
                        const updated = { ...employeeReportFilters, shift: e.target.value };
                        updateEmployeeReportFilters(updated);
                      }}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-violet-500 focus:ring-2 focus:ring-violet-200"
                    >
                      <option value="">All Shifts</option>
                      {(employeeFilterOptions.shifts || []).map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>}

                  {/* Phone */}
                  {employeeFilterOptions.visible_standard_filters?.phone && <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      {employeeFilterOptions.standard_filter_labels?.phone || 'Phone'}
                    </label>
                    <select
                      value={employeeReportFilters.phone}
                      onChange={(e) => {
                        const updated = { ...employeeReportFilters, phone: e.target.value };
                        updateEmployeeReportFilters(updated);
                      }}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-violet-500 focus:ring-2 focus:ring-violet-200"
                    >
                      <option value="">All Phones</option>
                      {(employeeFilterOptions.phones || []).map((phone) => (
                        <option key={phone} value={phone}>{phone}</option>
                      ))}
                    </select>
                  </div>}

                  {/* Dynamic Registry Fields */}
                  {Object.entries(employeeFilterOptions.dynamic_filters || {}).map(([key, config]) => (
                    <div key={key}>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        {config.label || key}
                      </label>
                      <select
                        value={employeeReportFilters.dynamic?.[key] || ''}
                        onChange={(e) => {
                          const updated = {
                            ...employeeReportFilters,
                            dynamic: { ...employeeReportFilters.dynamic, [key]: e.target.value }
                          };
                          updateEmployeeReportFilters(updated);
                        }}
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-violet-500 focus:ring-2 focus:ring-violet-200"
                      >
                        <option value="">All ({config.label || key})</option>
                        {(config.options || []).map((opt) => (
                          <option key={opt} value={opt}>{config.option_labels?.[opt] || opt}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </div>

              {/* Live Recipient Preview Card */}
              <div className="rounded-xl border border-violet-100 bg-violet-50/40 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Users size={18} className="text-violet-600" />
                    <span className="text-sm font-bold text-slate-800">Recipients Preview</span>
                  </div>
                  {previewLoading && (
                    <div className="flex items-center gap-1.5 text-xs text-violet-600">
                      <Loader2 size={14} className="animate-spin" />
                      <span>Updating preview...</span>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-lg bg-white p-3 border border-slate-200/60 shadow-xs">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Matching</span>
                    <p className="text-xl font-bold text-slate-800">{previewData?.total_matching ?? '-'}</p>
                  </div>
                  <div className="rounded-lg bg-white p-3 border border-emerald-200/60 shadow-xs">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-600">Will Receive</span>
                    <p className="text-xl font-bold text-emerald-600">{previewData?.eligible_count ?? '-'}</p>
                  </div>
                  <div className="rounded-lg bg-white p-3 border border-amber-200/60 shadow-xs">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-600">Missing Email</span>
                    <p className="text-xl font-bold text-amber-600">{previewData?.missing_email_count ?? '-'}</p>
                  </div>
                </div>

                {previewData?.missing_email_count > 0 && (
                  <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 p-2.5 rounded-lg border border-amber-200/60">
                    <AlertCircle size={15} className="mt-0.5 shrink-0" />
                    <span>
                      {previewData.missing_email_count} matching employee{previewData.missing_email_count === 1 ? '' : 's'} lack a registered email and will be skipped.
                    </span>
                  </div>
                )}

                {previewData?.sample_recipients?.length > 0 && (
                  <div>
                    <span className="text-xs text-slate-500 font-medium">Sample matching recipients:</span>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {previewData.sample_recipients.slice(0, 8).map((p) => (
                        <span
                          key={p.id}
                          className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md ${
                            p.email ? 'bg-white text-slate-700 border border-slate-200' : 'bg-amber-100 text-amber-800'
                          }`}
                        >
                          {p.name}
                          {!p.email && <span className="text-[9px] text-amber-600">(no email)</span>}
                        </span>
                      ))}
                      {previewData.sample_recipients.length > 8 && (
                        <span className="text-[11px] text-slate-400 self-center">
                          +{previewData.sample_recipients.length - 8} more
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50">
              <button
                type="button"
                onClick={() => setEmployeeReportModalOpen(false)}
                disabled={emailSending}
                className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200/60 rounded-xl transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={sendEmployeeReports}
                disabled={emailSending || !previewData || previewData.eligible_count === 0}
                className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white bg-violet-600 hover:bg-violet-700 rounded-xl shadow-md transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {emailSending ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    <span>Queueing Emails...</span>
                  </>
                ) : (
                  <>
                    <Send size={16} />
                    <span>Send Reports ({previewData?.eligible_count || 0} Emails)</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Branding Header */}
      <div className="flex flex-col sm:flex-row justify-between items-center bg-white p-6 rounded-2xl border border-slate-200 shadow-sm mb-6 bg-gradient-to-r from-white to-blue-50/30">
        <div className="flex items-center space-x-4">
          <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center shadow-blue-200 shadow-lg">
            <FileText className="text-white" size={28} />
          </div>
          <div>
            <h2 className="text-xl font-extrabold text-slate-900 tracking-tight">{filterOptions.vendor_name || "Enterprise"}</h2>
            <div className="flex items-center space-x-2">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
              <p className="text-xs font-medium text-slate-500 uppercase tracking-widest">Active Report Session</p>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-4 mt-6 sm:mt-0 bg-slate-50/50 p-3 rounded-xl border border-slate-100">
          <div className="text-right hidden sm:block border-r border-slate-200 pr-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em] mb-0.5">Powered By</p>
            <p className="text-sm font-black text-blue-600 tracking-tight">OpenVisionX</p>
          </div>
          <div className="w-12 h-12 bg-white rounded-xl flex items-center justify-center p-2 shadow-sm border border-slate-100">
            <img src="/openVisionXLogo.png" alt="OpenVisionX" className="w-full h-full object-contain" />
          </div>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">System Reports</h1>
          <p className="text-slate-500">Real-time attendance analytics and data export.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          {canSendEmployeeReports && (
            hasEmployeeReportsFeature ? (
              <button
                type="button"
                onClick={handleOpenEmployeeReportsModal}
                className="flex items-center space-x-2 px-4 py-2 bg-violet-600 text-white rounded-lg hover:bg-violet-700 font-medium transition-colors shadow-sm"
                title={`Email attendance and wages to employees for ${selectedReportMonthLabel}`}
              >
                <Mail size={18} />
                <span>Report to Each Employee</span>
              </button>
            ) : (
              <button
                type="button"
                disabled
                className="flex items-center space-x-2 px-3.5 py-2 bg-slate-100 text-slate-400 border border-slate-200 rounded-lg cursor-not-allowed font-medium text-sm shadow-none"
                title="Report to Each Employee is an optional add-on feature. Please contact Super Admin to enable."
              >
                <Lock size={15} className="text-slate-400" />
                <span>Report to Each Employee</span>
                <span className="text-[10px] uppercase font-bold bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded ml-1">Add-on</span>
              </button>
            )
          )}
          {schoolFlow && (
            <select
              value={personType}
              onChange={(event) => setPersonType(event.target.value)}
              className="px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-700 font-medium"
              aria-label="Report person type"
            >
              <option value="student">{terminology.person} Reports</option>
              <option value="faculty">{terminology.staff} Reports</option>
            </select>
          )}
          <button
            onClick={() => fetchAnalytics()}
            className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors"
          >
            <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
            <span>Refresh</span>
          </button>
          <button
            onClick={() => handleDownload(30)}
            className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors shadow-sm"
          >
            <Download size={18} />
            <span>Export Report</span>
          </button>
          <button
            onClick={handleExcelExport}
            className="flex items-center space-x-2 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 font-medium transition-colors shadow-sm"
            title="Download the selected report as Excel"
          >
            <FileSpreadsheet size={18} />
            <span>Excel Report</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
          <span className="font-medium">{error}</span>
        </div>
      )}

      {loading ? (
        <div className="text-center py-20">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-slate-500">Loading analytics data...</p>
        </div>
      ) : (
        <>
          {/* Summary Cards */}
          <div className={`grid grid-cols-2 ${hasLateMarkFeature ? 'md:grid-cols-4' : 'md:grid-cols-3'} gap-4`}>
            {/* Total Users */}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500 mb-2">Total Registered</p>
              <p className="text-2xl font-bold text-slate-800">{analytics.summary.total_users}</p>
              <div className="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-semibold">
                <span className="flex items-center gap-1.5 text-blue-600">
                  <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />
                  {analytics.summary.total_users} {personLabelPlural}
                </span>
                {schoolFlow && (
                  <span className="flex items-center gap-1.5 text-indigo-600">
                    <span className="w-2 h-2 rounded-full bg-indigo-500 inline-block" />
                    {personType === 'student'
                      ? `${analytics.summary.total_faculty ?? 0} ${terminology.staffPlural}`
                      : `${analytics.summary.total_students ?? 0} ${terminology.people}`}
                  </span>
                )}
              </div>
            </div>
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500">Present Today</p>
              <p className="text-2xl font-bold text-green-600">{analytics.summary.present_today}</p>
            </div>
            {hasLateMarkFeature && (
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
                <p className="text-sm text-slate-500">Late Today</p>
                <p className="text-2xl font-bold text-amber-500">{analytics.summary.late_today}</p>
              </div>
            )}
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500">Absent Today</p>
              <p className="text-2xl font-bold text-red-500">{analytics.summary.absent_today}</p>
            </div>
          </div>

          {/* Analytics Section */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-bold text-slate-800">Weekly Attendance Trend</h3>
              </div>
              <div className="h-80 w-full">
                <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={200}>
                  <BarChart data={analytics.bar_data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#64748b' }} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fill: '#64748b' }} />
                    <Tooltip
                      cursor={{ fill: 'transparent' }}
                      contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                    />
                    <Legend />
                    <Bar dataKey="present" name="Present" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="absent" name="Absent" fill="#e2e8f0" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <h3 className="text-lg font-bold text-slate-800 mb-6">Today's Punctuality</h3>
              <div className="h-80 w-full">
                <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={200}>
                  <PieChart>
                    <Pie
                      data={analytics.pie_data}
                      cx="50%"
                      cy="50%"
                      innerRadius={80}
                      outerRadius={100}
                      paddingAngle={5}
                      dataKey="value"
                    >
                      {analytics.pie_data.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend verticalAlign="bottom" height={36} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Custom Export Filter */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-lg font-bold text-slate-800">
                <Filter size={20} className="text-blue-600" />
                Advanced Report Generation
              </h3>
              <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
                {filterOptions.matching_employee_count || 0} matching {personLabelPlural.toLowerCase()}
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 items-end">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Start Date</label>
                <input
                  type="date"
                  value={filters.startDate}
                  onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}
                  className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">End Date</label>
                <input
                  type="date"
                  value={filters.endDate}
                  onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}
                  className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                />
              </div>

              {(filterOptions.visible_standard_filters?.department ?? false) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">{filterOptions.standard_filter_labels?.department || 'Department'}</label>
                  <select
                    value={filters.department}
                    onChange={(e) => setFilters({ ...filters, department: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All {filterOptions.standard_filter_labels?.department || 'Departments'}</option>
                    {filterOptions.departments.map(dept => (
                      <option key={dept} value={dept}>{dept}</option>
                    ))}
                  </select>
                </div>
              )}

              {(filterOptions.visible_standard_filters?.designation ?? false) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">{filterOptions.standard_filter_labels?.designation || 'Designation'}</label>
                  <select
                    value={filters.designation}
                    onChange={(e) => setFilters({ ...filters, designation: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All {filterOptions.standard_filter_labels?.designation || 'Designations'}</option>
                    {filterOptions.designations.map(desig => (
                      <option key={desig} value={desig}>{desig}</option>
                    ))}
                  </select>
                </div>
              )}

              {(filterOptions.visible_standard_filters?.shift ?? false) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">{filterOptions.standard_filter_labels?.shift || 'Shift'}</label>
                  <select
                    value={filters.shift}
                    onChange={(e) => setFilters({ ...filters, shift: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All {filterOptions.standard_filter_labels?.shift || 'Shifts'}</option>
                    {(filterOptions.shifts || []).map(s => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
              )}

              {(filterOptions.visible_standard_filters?.phone ?? false) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">{filterOptions.standard_filter_labels?.phone || 'Phone'}</label>
                  <select
                    value={filters.phone}
                    onChange={(e) => setFilters({ ...filters, phone: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All {filterOptions.standard_filter_labels?.phone || 'Phones'}</option>
                    {(filterOptions.phones || []).map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Dynamic Filters */}
              {Object.entries(filterOptions.dynamic_filters || {}).map(([key, config]) => (
                <div key={key}>
                  <label className="block text-sm font-medium text-slate-700 mb-1">{config.label}</label>
                  <select
                    value={filters.dynamic[key] || ''}
                    onChange={(e) => setFilters({
                      ...filters,
                      dynamic: { ...filters.dynamic, [key]: e.target.value }
                    })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All {config.label}</option>
                    {config.options && config.options.map(opt => (
                      <option key={opt} value={opt}>{config.option_labels?.[opt] || opt}</option>
                    ))}
                  </select>
                </div>
              ))}

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Report Type</label>
                <select
                  value={filters.type}
                  onChange={(e) => setFilters({ ...filters, type: e.target.value })}
                  className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                >
                  {(user?.features?.includes('report_detailed') || !user?.features) && (
                    <option value="detailed">Detailed Attendance Log</option>
                  )}
                  {(user?.features?.includes('report_payroll')) && (
                    <option value="summary">Payroll & Hours Summary</option>
                  )}
                </select>
              </div>

              <button
                onClick={handleCustomExport}
                className="w-full flex items-center justify-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors shadow-sm h-[38px]"
              >
                <Download size={16} />
                <span>Export</span>
              </button>
            </div>
          </div>

          {/* Export Options */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="p-6 border-b border-slate-200">
              <h3 className="text-lg font-bold text-slate-800">Export Data</h3>
            </div>
            <div className="divide-y divide-slate-100">
              <div className="p-4 flex items-center justify-between hover:bg-slate-50 transition-colors">
                <div className="flex items-center space-x-4">
                  <div className="w-10 h-10 bg-green-50 text-green-600 rounded-lg flex items-center justify-center">
                    <FileText size={20} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-800">Last 30 Days Report</p>
                    <p className="text-xs text-slate-500">CSV Format • Includes Check-in/out times</p>
                  </div>
                </div>
                <button
                  onClick={() => handleDownload(30)}
                  className="p-2 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                  title="Download CSV"
                >
                  <Download size={20} />
                </button>
              </div>

              <div className="p-4 flex items-center justify-between hover:bg-slate-50 transition-colors">
                <div className="flex items-center space-x-4">
                  <div className="w-10 h-10 bg-blue-50 text-blue-600 rounded-lg flex items-center justify-center">
                    <FileText size={20} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-800">This Week's Report</p>
                    <p className="text-xs text-slate-500">CSV Format • Last 7 days activity</p>
                  </div>
                </div>
                <button
                  onClick={() => handleDownload(7)}
                  className="p-2 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                  title="Download CSV"
                >
                  <Download size={20} />
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default Reports;
