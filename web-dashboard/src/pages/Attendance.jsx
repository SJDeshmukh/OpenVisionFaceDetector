import { Fragment, useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import {
  Search,
  Filter,
  Download,
  Calendar,
  MapPin,
  User,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  RefreshCw
} from 'lucide-react';
import { cn } from '../lib/utils';
import { API_URL } from '../config';
import { getBusinessTerminology, usesStudentRecords, isHostelVertical } from '../lib/businessTerminology';

import { useSocket } from '../context/SocketContext';

const Attendance = () => {
  const { socket } = useSocket();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [expandedRow, setExpandedRow] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [paginationWarning, setPaginationWarning] = useState(null);
  const lastRequestIdRef = useRef(0);
  const parseDate = (timestamp) => {
    if (!timestamp) return new Date();
    // Handle various formats: ISO, SQLite, Postgres
    const ts = typeof timestamp === 'string' ? timestamp.replace(' ', 'T') : timestamp;
    const d = new Date(ts);
    return isNaN(d.getTime()) ? new Date() : d;
  };
  const imageSource = (value) => {
    if (!value) return '';
    if (value.startsWith('data:') || value.startsWith('http://') || value.startsWith('https://')) return value;
    return `data:image/jpeg;base64,${value}`;
  };

  const getLocalDateString = (d = new Date()) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const [filterOptions, setFilterOptions] = useState({ names: [], departments: [], designations: [], shifts: [], phones: [], dynamic_filters: {}, visible_standard_filters: {}, shift_schedules: [] });
  const [summarySelection, setSummarySelection] = useState({ key: '', status: 'all' });
  const [filters, setFilters] = useState(() => {
    const today = getLocalDateString();
    return {
      startDate: today,
      endDate: today,
      department: '',
      designation: '',
      shift: '',
      phone: '',
      name: '',
      deviceName: ''
    };
  });
  const [deviceOptions, setDeviceOptions] = useState([]);
  const { user } = useAuth();
  const terminology = getBusinessTerminology(user?.vertical);
  const schoolFlow = usesStudentRecords(user?.vertical);
  const isHostel = isHostelVertical(user?.vertical);
  const isRegularUser = user?.role === 'user' || user?.role === 'student';
  const lateMarkEnabled = user?.features?.includes('late_mark');
  const [personType, setPersonType] = useState('student');
  const filtersRef = useRef(filters);
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);
  const personLabel = schoolFlow ? (personType === 'faculty' ? terminology.staff : terminology.person) : terminology.person;

  useEffect(() => {
    fetchFilters(filtersRef.current);
  }, []);

  useEffect(() => {
    fetchLogs(); // Trigger fetch on mount and filter change
    setCurrentPage(1);
    setExpandedRow(null);
    setSummarySelection({ key: '', status: 'all' });
  }, [filters, personType]);

  useEffect(() => {
    if (!socket || !user?.vendor_id) return;
    const handleAttendanceUpdated = (ev) => {
      // If filters are active, we might need a full refresh to be safe
      // but for "real time" we can just re-fetch the current view.
      if (String(ev.vendor_id) === String(user.vendor_id)) {
        fetchLogs(true, true);
        fetchFilters(filtersRef.current);
      }
    };
    const handlePersonsUpdated = (ev) => {
      if (String(ev.vendor_id) === String(user.vendor_id)) {
        if (ev.action === 'reconcile') return; // Ignore kiosk connection handshake
        fetchLogs(true, true);
        fetchFilters(filtersRef.current);
      }
    };
    socket.on('attendance_updated', handleAttendanceUpdated);
    socket.on('persons_updated', handlePersonsUpdated);

    return () => {
      socket.off('attendance_updated', handleAttendanceUpdated);
      socket.off('persons_updated', handlePersonsUpdated);
    };
  }, [socket, user?.vendor_id]);

  useEffect(() => {
    const t = setTimeout(() => fetchFilters(filtersRef.current), 250);
    return () => clearTimeout(t);
  }, [filters, personType]);

  const fetchFilters = async (activeFilters) => {
    try {
      const params = new URLSearchParams();
      if (schoolFlow) params.append('person_type', personType);
      const f = activeFilters || {};
      Object.entries(filterOptions.dynamic_filters || {}).forEach(([key]) => {
        const v = f[key];
        if (v && String(v).trim() !== '') params.append(key, v);
      });
      const res = await axios.get(`${API_URL}/attendance/filters?${params.toString()}`);
      const nextOptions = res.data || {};
      setFilterOptions(nextOptions);
      const nextFilters = { ...filtersRef.current };
      Object.entries(nextOptions.dynamic_filters || {}).forEach(([key, cfg]) => {
        const allowed = new Set(((cfg && cfg.options) || []).map(String));
        if (nextFilters[key] && !allowed.has(String(nextFilters[key]))) nextFilters[key] = '';
      });
      const current = filtersRef.current;
      const changed = Object.keys(nextFilters).some(k => String(nextFilters[k] ?? '') !== String(current[k] ?? ''));
      if (changed) setFilters(nextFilters);
    } catch (error) {
      console.error("Error fetching filters:", error);
    }
  };

  const fetchLogs = async (isBackground = false, forceRefresh = false) => {
    const requestId = ++lastRequestIdRef.current;
    // Only set refreshing state for manual actions (not auto-refresh)
    if (!isBackground) setIsRefreshing(true);

    try {
      const params = new URLSearchParams();
      if (schoolFlow) params.append('person_type', personType);
      if (filters.startDate) params.append('start_date', filters.startDate);
      if (filters.endDate) params.append('end_date', filters.endDate);
      if (isRegularUser && (user?.person_id || user?.id)) {
        params.append('person_id', user.person_id || user.id);
      }
      Object.entries(filterOptions.dynamic_filters || {}).forEach(([key, cfg]) => {
        const val = filters[key];
        if (val && String(val).trim() !== '') {
          params.append(key, val);
        }
      });

      if (filters.deviceName && String(filters.deviceName).trim() !== '') {
        params.append('device_name', filters.deviceName);
      }
      if (forceRefresh) {
        params.append('nocache', '1');
      }
      const headers = forceRefresh ? { 'Cache-Control': 'no-cache' } : {};
      const batchSize = 500;
      const maximumEvents = 10000;
      const eventsById = new Map();
      let offset = 0;
      let hasMore = true;

      while (hasMore && offset < maximumEvents) {
        params.set('limit', String(batchSize));
        params.set('offset', String(offset));
        const response = await axios.get(`${API_URL}/attendance?${params.toString()}`, { headers });
        if (requestId !== lastRequestIdRef.current) return;

        const batch = response.data?.attendance || [];
        batch.forEach((item) => {
          const key = item.id != null
            ? `id:${item.id}`
            : `${item.person_id || item.name}:${item.timestamp}:${item.status}`;
          eventsById.set(key, item);
        });
        const pageInfo = response.data?.pagination;
        hasMore = pageInfo ? pageInfo.has_more === true : batch.length === batchSize;
        offset += batchSize;
      }

      const list = Array.from(eventsById.values());
      setLogs(list);
      setPaginationWarning(
        hasMore
          ? `More than ${maximumEvents.toLocaleString()} events match these filters. Narrow the date range to view every record.`
          : null
      );
      try {
        const setNames = new Set();
        list.forEach(l => {
          const dn = l.device_name || '';
          if (dn && dn.trim() !== '') setNames.add(dn.trim());
        });
        setDeviceOptions(Array.from(setNames).sort());
      } catch (e) { }
      setError(null);
    } catch (error) {
      if (requestId !== lastRequestIdRef.current) return;
      console.error("Error fetching logs:", error);
      setPaginationWarning(null);
      if (error.response && error.response.status === 403) {
        setError(error.response.data.error || "Access Denied");
      }
    } finally {
      if (requestId === lastRequestIdRef.current) {
        // Always turn off blocking loader (for initial load) and refreshing spinner
        setLoading(false);
        setIsRefreshing(false);
      }
    }
  };

  const handleSearch = () => {
    fetchLogs(false, true);
  };

  const handleExport = () => {
    const params = new URLSearchParams();
    if (schoolFlow) params.append('person_type', personType);
    if (filters.startDate) params.append('start_date', filters.startDate);
    if (filters.endDate) params.append('end_date', filters.endDate);
    Object.entries(filterOptions.dynamic_filters || {}).forEach(([key, cfg]) => {
      const val = filters[key];
      if (val && String(val).trim() !== '') {
        params.append(key, val);
      }
    });

    // Add token for auth
    if (user?.token) params.append('token', user.token);

    window.location.href = `${API_URL}/reports/export?${params.toString()}`;
  };

  const getStatus = (log) => {
    if (isHostel) {
      if (log.status === 'CHECK_OUT') {
        return { label: 'Hostel Exit', color: 'bg-sky-100 text-sky-800' };
      }
      return { label: 'Hostel Entry', color: 'bg-emerald-100 text-emerald-800' };
    }

    if (!lateMarkEnabled) {
      return log.status === 'CHECK_OUT'
        ? { label: 'Check Out', color: 'bg-slate-100 text-slate-700' }
        : { label: 'Check In', color: 'bg-green-100 text-green-700' };
    }

    // Backend provided late flag
    // Handle both integer 1/0 and boolean true/false or string "1"
    if (log.is_late === 1 || log.is_late === true || log.is_late === '1') {
      return { label: 'Late', color: 'bg-amber-100 text-amber-700' };
    }

    // Check Out
    if (log.status === 'CHECK_OUT') {
      return { label: 'Check Out', color: 'bg-slate-100 text-slate-700' };
    }

    // On Time Check In
    if (log.status === 'CHECK_IN') {
      return { label: 'On Time', color: 'bg-green-100 text-green-700' };
    }

    // Fallback based on timestamp if old data (legacy support)
    // Note: This fallback uses hardcoded 9:30 AM which might differ from DB logic
    // but useful for old records without is_late flag.
    const d = parseDate(log.timestamp);
    const hour = d.getHours();
    if (hour < 9) return { label: 'Early', color: 'bg-blue-100 text-blue-700' };
    if (hour === 9 && d.getMinutes() <= 30) return { label: 'On Time', color: 'bg-green-100 text-green-700' };
    return { label: 'Late', color: 'bg-amber-100 text-amber-700' };
  };

  const showShiftColumn = user?.features?.includes('shifts') && !!(filterOptions.dynamic_filters && filterOptions.dynamic_filters.shift);

  const operationalDateKey = (log) => {
    const storedDate = String(log.attendance_date || '').trim().slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(storedDate)) return storedDate;
    return getLocalDateString(parseDate(log.timestamp));
  };

  const formatOperationalDate = (value) => {
    const parts = String(value || '').split('-').map(Number);
    if (parts.length === 3 && parts.every(Number.isFinite)) {
      return new Date(parts[0], parts[1] - 1, parts[2]).toLocaleDateString();
    }
    return value || '';
  };

  const groupedLogs = logs.reduce((acc, log) => {
    // Group by the immutable shift/operational day from the backend. Grouping
    // by the timestamp's calendar date splits overnight IN/OUT pairs.
    const logDate = operationalDateKey(log);
    const shiftName = String(log.shift || 'Work').trim() || 'Work';
    const key = log.person_id
      ? `id:${log.person_id}-${logDate}-${shiftName}`
      : `name:${log.vendor_id || 'unknown'}:${log.name}-${logDate}-${shiftName}`;
      
    if (!acc[key]) {
      acc[key] = {
        key,
        name: log.name,
        person_id: log.person_id || null,
        attendanceDate: logDate,
        shiftName,
        logs: []
      };
    }
    acc[key].logs.push(log);
    return acc;
  }, {});

  // Convert to array and sort by latest timestamp
  const sortedGroups = Object.entries(groupedLogs)
    .map(([_, group]) => ({
      key: group.key,
      name: group.name,
      person_id: group.person_id,
      attendanceDate: group.attendanceDate,
      shiftName: group.shiftName,
      logs: group.logs.sort((a, b) => parseDate(b.timestamp) - parseDate(a.timestamp)),
      latestLog: group.logs.sort((a, b) => parseDate(b.timestamp) - parseDate(a.timestamp))[0]
    }))
    .sort((a, b) => parseDate(b.latestLog.timestamp) - parseDate(a.latestLog.timestamp));

  const shiftSchedules = Array.isArray(filterOptions.shift_schedules) ? filterOptions.shift_schedules : [];
  const scheduleByName = new Map(shiftSchedules.map((shift) => [String(shift.name || '').trim().toLowerCase(), shift]));
  const summaryKeys = new Set(sortedGroups.map((group) => `${group.attendanceDate}::${group.shiftName}`));
  if (filters.startDate && filters.startDate === filters.endDate) {
    shiftSchedules.forEach((shift) => summaryKeys.add(`${filters.startDate}::${shift.name}`));
  }

  const isShiftComplete = (attendanceDate, schedule) => {
    if (!schedule?.end_time) return attendanceDate < getLocalDateString();
    const [year, month, day] = attendanceDate.split('-').map(Number);
    const [hour, minute] = String(schedule.end_time).split(':').map(Number);
    if (![year, month, day, hour, minute].every(Number.isFinite)) return false;
    const end = new Date(Date.UTC(year, month - 1, day, hour, minute));
    if (schedule.is_cross_midnight) end.setUTCDate(end.getUTCDate() + 1);
    try {
      const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: schedule.timezone || 'Asia/Kolkata',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
      }).formatToParts(new Date());
      const value = (type) => Number(parts.find((part) => part.type === type)?.value);
      const zonedNow = Date.UTC(value('year'), value('month') - 1, value('day'), value('hour'), value('minute'));
      return end.getTime() <= zonedNow;
    } catch {
      const localEnd = new Date(year, month - 1, day, hour, minute);
      if (schedule.is_cross_midnight) localEnd.setDate(localEnd.getDate() + 1);
      return localEnd.getTime() <= Date.now();
    }
  };

  const completedShiftSummaries = Array.from(summaryKeys)
    .map((key) => {
      const separator = key.indexOf('::');
      const attendanceDate = key.slice(0, separator);
      const shiftName = key.slice(separator + 2);
      const schedule = scheduleByName.get(shiftName.trim().toLowerCase());
      if (!schedule || !isShiftComplete(attendanceDate, schedule)) return null;
      const groups = sortedGroups.filter((group) => group.attendanceDate === attendanceDate && group.shiftName === shiftName);
      return {
        key,
        attendanceDate,
        shiftName,
        schedule,
        total: groups.length,
        checkedIn: groups.filter((group) => group.logs.some((log) => log.status === 'CHECK_IN')).length,
        checkedOut: groups.filter((group) => group.logs.some((log) => log.status === 'CHECK_OUT')).length,
      };
    })
    .filter(Boolean)
    .sort((a, b) => b.attendanceDate.localeCompare(a.attendanceDate) || a.schedule.start_time.localeCompare(b.schedule.start_time));

  const visibleGroups = sortedGroups.filter((group) => {
    if (!summarySelection.key) return true;
    if (`${group.attendanceDate}::${group.shiftName}` !== summarySelection.key) return false;
    if (summarySelection.status === 'check_in') return group.logs.some((log) => log.status === 'CHECK_IN');
    if (summarySelection.status === 'check_out') return group.logs.some((log) => log.status === 'CHECK_OUT');
    return true;
  });

  const groupsPerPage = 25;
  const totalPages = Math.max(1, Math.ceil(visibleGroups.length / groupsPerPage));
  const visiblePage = Math.min(currentPage, totalPages);
  const pageStart = (visiblePage - 1) * groupsPerPage;
  const paginatedGroups = visibleGroups.slice(pageStart, pageStart + groupsPerPage);

  const changePage = (page) => {
    setCurrentPage(Math.max(1, Math.min(page, totalPages)));
    setExpandedRow(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">
            {isRegularUser ? "My Attendance" : (isHostel ? "Hostel Attendance Logs" : "Attendance Logs")}
          </h1>
          <p className="text-slate-500">
            {isRegularUser ? "View your personal punch logs and attendance history." : (isHostel ? "Track resident entries, exits, and gate movements." : `Track ${personLabel.toLowerCase()} check-ins and movements.`)}
          </p>
        </div>
        <div className="flex space-x-3">
          {schoolFlow && !isRegularUser && (
            <select
              value={personType}
              onChange={(event) => setPersonType(event.target.value)}
              className="px-3 py-2 bg-white border border-slate-200 rounded-lg text-slate-700 font-medium"
              aria-label="Attendance person type"
            >
              <option value="student">{terminology.person} Attendance</option>
              <option value="faculty">{terminology.staff} Attendance</option>
            </select>
          )}
          <div className="relative">
            <button
              onClick={() => {
                const today = getLocalDateString();
                setFilters({
                  ...filters,
                  startDate: today,
                  endDate: today,
                  name: ''
                });
              }}
              className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors"
            >
              <Calendar size={18} />
              <span>Today</span>
            </button>
          </div>
          <button
            onClick={() => fetchLogs(false, true)}
            className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors"
          >
            <RefreshCw size={18} className={isRefreshing ? "animate-spin" : ""} />
            <span>Refresh</span>
          </button>
          {!isRegularUser && (
            <button
              onClick={handleExport}
              className="flex items-center space-x-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium transition-colors"
            >
              <Download size={18} />
              <span>Export</span>
            </button>
          )}
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

      {paginationWarning && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 px-4 py-3 rounded-lg">
          {paginationWarning}
        </div>
      )}

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row gap-4 items-end md:items-center flex-wrap">
        <div className="w-full md:w-auto">
          <input
            type="date"
            value={filters.startDate}
            onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}
            className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        <div className="w-full md:w-auto">
          <input
            type="date"
            value={filters.endDate}
            onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}
            className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        {!isRegularUser && (
          <>
            <div className="w-full md:w-52">
              <select
                value={filters.deviceName || ''}
                onChange={(e) => setFilters({ ...filters, deviceName: e.target.value })}
                className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              >
                <option value="">All Devices</option>
                {deviceOptions.map(opt => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            </div>

            {Object.entries(filterOptions.dynamic_filters || {}).map(([key, cfg]) => (
              <div key={key} className="w-full md:w-44">
                <select
                  value={filters[key] || ''}
                  onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                >
                  <option value="">{`All ${cfg?.label || key}`}</option>
                  {(cfg?.options || []).map(opt => (
                    <option key={opt} value={opt}>{cfg?.option_labels?.[opt] || opt}</option>
                  ))}
                </select>
              </div>
            ))}
          </>
        )}

        <button
          onClick={handleSearch}
          className="p-2 bg-blue-600 text-white hover:bg-blue-700 transition-colors border border-transparent rounded-lg"
        >
          <Filter size={20} />
        </button>
      </div>

      {!isRegularUser && showShiftColumn && completedShiftSummaries.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="completed-shift-heading">
          <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 id="completed-shift-heading" className="font-semibold text-slate-800">Completed shift attendance</h2>
              <p className="text-sm text-slate-500">Ongoing shifts appear here only after their scheduled end time.</p>
            </div>
            {summarySelection.key && (
              <button
                type="button"
                onClick={() => { setSummarySelection({ key: '', status: 'all' }); setCurrentPage(1); }}
                className="self-start text-sm font-medium text-blue-600 hover:text-blue-700"
              >
                Show all attendance
              </button>
            )}
          </div>
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {completedShiftSummaries.map((summary) => {
              const selected = summarySelection.key === summary.key;
              const selectSummary = (status) => {
                setSummarySelection(selected && summarySelection.status === status
                  ? { key: '', status: 'all' }
                  : { key: summary.key, status });
                setCurrentPage(1);
                setExpandedRow(null);
              };
              return (
                <div key={summary.key} className={cn("rounded-lg border p-3", selected ? "border-blue-300 bg-blue-50/40" : "border-slate-200")}>
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-800">{summary.shiftName}</p>
                      <p className="text-xs text-slate-500">
                        {formatOperationalDate(summary.attendanceDate)} · {summary.schedule.start_time}–{summary.schedule.end_time}
                      </p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">Completed</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      ['all', 'People', summary.total, 'text-slate-800'],
                      ['check_in', 'Checked In', summary.checkedIn, 'text-emerald-700'],
                      ['check_out', 'Checked Out', summary.checkedOut, 'text-blue-700'],
                    ].map(([status, label, count, color]) => (
                      <button
                        key={status}
                        type="button"
                        onClick={() => selectSummary(status)}
                        aria-pressed={selected && summarySelection.status === status}
                        className={cn(
                          "rounded-lg border px-2 py-2 text-left transition-colors hover:bg-slate-50",
                          selected && summarySelection.status === status ? "border-blue-400 bg-white ring-2 ring-blue-100" : "border-slate-200 bg-white"
                        )}
                      >
                        <span className={cn("block text-lg font-bold", color)}>{count}</span>
                        <span className="block text-[11px] font-medium text-slate-500">{label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="w-10 px-6 py-4"></th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{personLabel}</th>
                {showShiftColumn && (
                  <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Shift</th>
                )}
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Date</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Time</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isHostel ? 'Movement' : 'Activity'}</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Place</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(loading || (isRefreshing && visibleGroups.length === 0)) ? (
                <tr>
                  <td colSpan="8" className="p-8 text-center text-slate-500">
                    <div className="flex items-center justify-center space-x-2">
                      <RefreshCw className="animate-spin text-blue-500 inline mr-2" size={18} />
                      <span>Loading logs...</span>
                    </div>
                  </td>
                </tr>
              ) : visibleGroups.length === 0 ? (
                <tr><td colSpan="8" className="p-8 text-center text-slate-500">No attendance records found.</td></tr>
              ) : (
                paginatedGroups.map((group) => {
                  const log = group.latestLog; // Show latest log in summary
                  const status = getStatus(log);
                  const isExpanded = expandedRow === group.key;

                  return (
                    <Fragment key={group.key}>
                      <tr
                        className={cn(
                          "hover:bg-slate-50/80 transition-colors cursor-pointer",
                          isExpanded ? "bg-slate-50" : ""
                        )}
                        onClick={() => setExpandedRow(isExpanded ? null : group.key)}
                      >
                        <td className="px-6 py-4">
                          {isExpanded ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center space-x-3">
                            {log.captured_image ? (
                              <img
                                src={imageSource(log.captured_image)}
                                alt="Captured"
                                className="h-10 w-10 rounded-full object-cover border border-slate-200"
                              />
                            ) : (
                              <div className="h-10 w-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400">
                                <User size={20} />
                              </div>
                            )}
                            <div>
                              <span className="font-medium text-slate-900 block">{log.name}</span>
                              {user?.role === 'super_admin' && log.vendor_id && (
                                <span className="text-xs text-slate-400 block">Vendor #{log.vendor_id}</span>
                              )}
                              <span className="text-xs text-slate-500">{group.logs.length} Records</span>
                            </div>
                          </div>
                        </td>
                        {showShiftColumn && (
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                            {log.shift || <span className="text-slate-400 italic">None</span>}
                          </td>
                        )}
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                          {formatOperationalDate(group.attendanceDate)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-slate-700">
                          {parseDate(log.timestamp).toLocaleTimeString()}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100">
                            {log.activity || (isHostel ? 'Hostel Movement' : 'Work')}{log.activity === 'Lecture' && log.subject ? `: ${log.subject}` : ''}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                          {log.device_name ? (
                            <span className="inline-flex items-center gap-1">
                              <MapPin size={14} className="text-slate-400" />
                              <span className="font-medium">{log.device_name}</span>
                            </span>
                          ) : (
                            <span className="text-slate-400 italic">-</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
                            {status.label}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                          <div className="flex items-center space-x-2">
                            <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                              <div className="h-full bg-green-500 rounded-full" style={{ width: '98%' }}></div>
                            </div>
                            <span>98%</span>
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-slate-50/50">
                          <td colSpan="10" className="px-6 py-4 pl-12">
                            <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                              <table className="w-full text-left">
                                <thead className="bg-slate-50 border-b border-slate-100">
                                  <tr>
                                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Image</th>
                                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Time</th>
                                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Date</th>
                                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Place</th>
                                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase">Status</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-50">
                                  {group.logs.map((historyLog, hIdx) => (
                                    <tr key={hIdx} className="hover:bg-slate-50">
                                      <td className="px-4 py-2">
                                        {historyLog.captured_image ? (
                                          <img
                                            src={imageSource(historyLog.captured_image)}
                                            alt="Thumb"
                                            className="h-12 w-12 rounded-md object-cover border border-slate-200"
                                          />
                                        ) : (
                                          <div className="h-12 w-12 rounded-md bg-slate-100 flex items-center justify-center text-slate-400">
                                            <User size={16} />
                                          </div>
                                        )}
                                      </td>
                                      <td className="px-4 py-2 text-sm font-mono text-slate-700">
                                        {parseDate(historyLog.timestamp).toLocaleTimeString()}
                                      </td>
                                      <td className="px-4 py-2 text-sm text-slate-600">
                                        {parseDate(historyLog.timestamp).toLocaleDateString()}
                                      </td>
                                      <td className="px-4 py-2 text-sm text-slate-600">
                                        {historyLog.device_name ? historyLog.device_name : <span className="text-slate-400 italic">-</span>}
                                      </td>
                                      <td className="px-4 py-2">
                                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getStatus(historyLog).color}`}>
                                          {getStatus(historyLog).label}
                                          {historyLog.activity && historyLog.activity !== 'Work' && ` (${historyLog.activity})`}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        {visibleGroups.length > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-slate-200 px-6 py-4">
            <p className="text-sm text-slate-500">
              Showing {pageStart + 1}–{Math.min(pageStart + groupsPerPage, visibleGroups.length)} of {visibleGroups.length} employee-shift records
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => changePage(visiblePage - 1)}
                disabled={visiblePage === 1}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronLeft size={16} /> Previous
              </button>
              <span className="px-2 text-sm font-medium text-slate-600">
                Page {visiblePage} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() => changePage(visiblePage + 1)}
                disabled={visiblePage === totalPages}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Attendance;
