import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import {
  FileText,
  Download,
  Calendar,
  Filter,
  BarChart2,
  PieChart as PieChartIcon,
  RefreshCw
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

const COLORS = ['#22c55e', '#f59e0b', '#ef4444'];

const Reports = () => {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [analytics, setAnalytics] = useState({
    pie_data: [],
    bar_data: [],
    summary: {
      total_users: 0,
      present_today: 0,
      absent_today: 0,
      late_today: 0
    }
  });

  const [filterOptions, setFilterOptions] = useState({ departments: [], designations: [], shifts: [], phones: [], visible_standard_filters: {} });
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
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  useEffect(() => {
    fetchAnalytics();
    fetchFilters(filtersRef.current);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => fetchFilters(filtersRef.current), 250);
    return () => clearTimeout(t);
  }, [filters]);

  const fetchFilters = async (activeFilters) => {
    try {
      const f = activeFilters || {};
      const params = new URLSearchParams();
      if (f.department) params.append('department', f.department);
      if (f.designation) params.append('designation', f.designation);
      if (f.shift) params.append('shift', f.shift);
      if (f.phone) params.append('phone', f.phone);
      Object.entries(f.dynamic || {}).forEach(([key, value]) => {
        if (value) params.append(`dynamic_${key}`, value);
      });
      const res = await axios.get(`${API_URL}/reports/filters?${params.toString()}`);
      const nextOptions = res.data || {};
      setFilterOptions(nextOptions);
      const nextFilters = { ...filtersRef.current };
      const vis = nextOptions.visible_standard_filters || {};
      const pruneStandard = (key, enabled, list) => {
        if (!enabled) {
          if (nextFilters[key]) nextFilters[key] = '';
          return;
        }
        const allowed = new Set((list || []).map(String));
        if (nextFilters[key] && !allowed.has(String(nextFilters[key]))) nextFilters[key] = '';
      };
      pruneStandard('department', !!vis.department, nextOptions.departments);
      pruneStandard('designation', !!vis.designation, nextOptions.designations);
      pruneStandard('shift', !!vis.shift, nextOptions.shifts);
      pruneStandard('phone', !!vis.phone, nextOptions.phones);
      const nextDynamic = { ...(nextFilters.dynamic || {}) };
      Object.entries(nextDynamic).forEach(([key, val]) => {
        const cfg = (nextOptions.dynamic_filters || {})[key];
        const allowed = new Set(((cfg && cfg.options) || []).map(String));
        if (!cfg || (val && !allowed.has(String(val)))) delete nextDynamic[key];
      });
      nextFilters.dynamic = nextDynamic;
      const current = filtersRef.current;
      const changed = JSON.stringify(nextFilters) !== JSON.stringify(current);
      if (changed) setFilters(nextFilters);
    } catch (error) {
      console.error("Error fetching filters:", error);
    }
  };

  const fetchAnalytics = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_URL}/reports/analytics`);
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
    if (user?.token) {
      url += `&token=${user.token}`;
    }
    window.location.href = url;
  };

  const handleCustomExport = () => {
    const params = new URLSearchParams();
    params.append('start_date', filters.startDate);
    params.append('end_date', filters.endDate);
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

  return (
    <div className="space-y-8">
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
        <div className="flex space-x-3">
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500">Total Users</p>
              <p className="text-2xl font-bold text-slate-800">{analytics.summary.total_users}</p>
            </div>
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500">Present Today</p>
              <p className="text-2xl font-bold text-green-600">{analytics.summary.present_today}</p>
            </div>
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500">Late Today</p>
              <p className="text-2xl font-bold text-amber-500">{analytics.summary.late_today}</p>
            </div>
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
            <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
              <Filter size={20} className="text-blue-600" />
              Advanced Report Generation
            </h3>

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
                  <label className="block text-sm font-medium text-slate-700 mb-1">Department</label>
                  <select
                    value={filters.department}
                    onChange={(e) => setFilters({ ...filters, department: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All Departments</option>
                    {filterOptions.departments.map(dept => (
                      <option key={dept} value={dept}>{dept}</option>
                    ))}
                  </select>
                </div>
              )}

              {(filterOptions.visible_standard_filters?.designation ?? false) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Designation</label>
                  <select
                    value={filters.designation}
                    onChange={(e) => setFilters({ ...filters, designation: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All Designations</option>
                    {filterOptions.designations.map(desig => (
                      <option key={desig} value={desig}>{desig}</option>
                    ))}
                  </select>
                </div>
              )}

              {(filterOptions.visible_standard_filters?.shift ?? false) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Shift</label>
                  <select
                    value={filters.shift}
                    onChange={(e) => setFilters({ ...filters, shift: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All Shifts</option>
                    {(filterOptions.shifts || []).map(s => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
              )}

              {(filterOptions.visible_standard_filters?.phone ?? false) && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Phone</label>
                  <select
                    value={filters.phone}
                    onChange={(e) => setFilters({ ...filters, phone: e.target.value })}
                    className="w-full rounded-lg border-slate-200 text-sm focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">All Phones</option>
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
                    <option value="">All {config.label}s</option>
                    {config.options && config.options.map(opt => (
                      <option key={opt} value={opt}>{opt}</option>
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
