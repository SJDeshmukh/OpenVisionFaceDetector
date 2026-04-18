import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../config';
import { useAuth } from '../context/AuthContext';
import { useSocket } from '../context/SocketContext';

const Wages = () => {
  const { user } = useAuth();
  const { socket } = useSocket();

  // Helper to format date as YYYY-MM-DD in local time
  const formatDate = (date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  // Calculate default dates (First and Last day of current month)
  const now = new Date();
  const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
  const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);

  const [payrollData, setPayrollData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [startDate, setStartDate] = useState(formatDate(firstDay));
  const [endDate, setEndDate] = useState(formatDate(lastDay));
  const [hasChanges, setHasChanges] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [workingHours, setWorkingHours] = useState(8.0);
  const [workingHoursChanged, setWorkingHoursChanged] = useState(false);
  const [globalSettings, setGlobalSettings] = useState({ allowance: 7, deduction: 0 });
  const [globalSettingsChanged, setGlobalSettingsChanged] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsPerson, setDetailsPerson] = useState(null);
  const [advanceModalOpen, setAdvanceModalOpen] = useState(false);
  const [advancePerson, setAdvancePerson] = useState(null);
  const [advanceAmount, setAdvanceAmount] = useState('');
  const [pfPercentage, setPfPercentage] = useState(12.0);
  const [esiPercentage, setEsiPercentage] = useState(0.75);
  const [gratuityPercentage, setGratuityPercentage] = useState(4.81);
  const [gratuityYears, setGratuityYears] = useState(5);
  const [advanceCash, setAdvanceCash] = useState('');
  const [advanceOnline, setAdvanceOnline] = useState('');
  const [deductionMonth, setDeductionMonth] = useState(formatDate(new Date()).substring(0, 7));
  const [advanceHistory, setAdvanceHistory] = useState([]);
  const [editingAdvance, setEditingAdvance] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [joiningDateModalOpen, setJoiningDateModalOpen] = useState(false);
  const [joiningDatePerson, setJoiningDatePerson] = useState(null);
  const [tempJoiningDate, setTempJoiningDate] = useState('');
  const [ownerConfigModalOpen, setOwnerConfigModalOpen] = useState(false);
  const [owners, setOwners] = useState([]);
  const [ownersLoading, setOwnersLoading] = useState(false);

  useEffect(() => {
    if (user) {
      fetchWorkingHours();
    }
  }, [user]);

  const fetchWorkingHours = async () => {
    try {
      const companyId = user?.company_id || 1;
      const res = await fetch(`${API_BASE_URL}/companies/${companyId}`, {
        headers: {
          'Authorization': `Bearer ${user?.token}`
        }
      });
      const data = await res.json();
      if (data.working_hours) {
        setWorkingHours(parseFloat(data.working_hours));
      }
    } catch (e) {
      console.error("Error fetching working hours", e);
    }
  };

  const saveWorkingHours = async () => {
    try {
      const companyId = user?.company_id || 1;
      const res = await fetch(`${API_BASE_URL}/companies/${companyId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({ working_hours: parseFloat(workingHours) })
      });
      if (res.status === 403) {
        const data = await res.json();
        setError(data.error || "Access Denied");
        return;
      }
      if (res.ok) {
        setWorkingHoursChanged(false);
        // Do NOT fetchPayroll() immediately if it causes a UI jump, 
        // but we need to recalculate costs locally or refresh.
        // fetchPayroll(); 

        // Better: Update local payroll data with new hourly rate immediately
        const newData = payrollData.map(p => {
          const newRate = p.daily_wage / parseFloat(workingHours);
          return {
            ...p,
            company_working_hours: parseFloat(workingHours),
            total_cost: (p.total_hours * newRate).toFixed(2)
          };
        });
        setPayrollData(newData);
        alert("Working hours updated successfully!");
      }
    } catch (e) {
      console.error("Error saving working hours", e);
    }
  };


  const fetchPayroll = async (isBackground = false) => {
    if (!isBackground) setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/reports/payroll?start_date=${startDate}&end_date=${endDate}&pf_percentage=${pfPercentage}&esi_percentage=${esiPercentage}&gratuity_percentage=${gratuityPercentage}`, {
        headers: {
          'Authorization': `Bearer ${user?.token}`
        }
      });
      if (res.status === 403) {
        const data = await res.json();
        setError(data.error || "Access Denied");
        return;
      }
      const data = await res.json();
      if (data.payroll) {
        setPayrollData(data.payroll);
      }
      if (data.global_settings) {
        setGlobalSettings({
          allowance: parseInt(data.global_settings.allowance),
          deduction: parseFloat(data.global_settings.deduction),
        });
        if (data.global_settings.pf_percentage) setPfPercentage(data.global_settings.pf_percentage);
        if (data.global_settings.esi_percentage) setEsiPercentage(data.global_settings.esi_percentage);
        if (data.global_settings.gratuity_percentage) setGratuityPercentage(data.global_settings.gratuity_percentage);
        if (data.global_settings.gratuity_threshold_years) setGratuityYears(data.global_settings.gratuity_threshold_years);
      }
    } catch (error) {
      console.error("Error fetching payroll:", error);
    } finally {
      if (!isBackground) setLoading(false);
    }
  };

  useEffect(() => {
    if (startDate && endDate) {
      // Only fetch if NOT already editing (to prevent overwrite)
      if (!hasChanges) {
        fetchPayroll();
      }

      // Poll for updates (Disable polling if editing)
      const interval = setInterval(() => {
        if (!hasChanges && !workingHoursChanged) fetchPayroll(true);
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [startDate, endDate, hasChanges, workingHoursChanged]);

  useEffect(() => {
    if (!socket || !user) return;
    const onPersonsUpdated = (data) => {
      try {
        if (!data || String(data.vendor_id) !== String(user.vendor_id)) return;
        if (!hasChanges && !workingHoursChanged) fetchPayroll(true);
      } catch { }
    };
    const onAttendanceUpdated = (data) => {
      try {
        if (!data || String(data.vendor_id) !== String(user.vendor_id)) return;
        if (!hasChanges && !workingHoursChanged) fetchPayroll(true);
      } catch { }
    };
    socket.on('persons_updated', onPersonsUpdated);
    socket.on('attendance_updated', onAttendanceUpdated);
    return () => {
      socket.off('persons_updated', onPersonsUpdated);
      socket.off('attendance_updated', onAttendanceUpdated);
    };
  }, [socket, user, hasChanges, workingHoursChanged, startDate, endDate]);

  const handleWageChange = (index, field, value) => {
    const newData = [...payrollData];

    if (field === 'daily_wage') {
      newData[index].daily_wage = parseFloat(value) || 0;
    } else if (field === 'late_allowance_days') {
      newData[index].late_allowance_days = value === '' ? null : parseInt(value);
    } else if (field === 'late_deduction_amount') {
      newData[index].late_deduction_amount = value === '' ? null : parseFloat(value);
    } else if (['pf_enabled', 'esi_enabled', 'gratuity_enabled'].includes(field)) {
      if (field === 'gratuity_enabled' && value && !newData[index].joining_date) {
        setJoiningDatePerson({ ...newData[index], index });
        setTempJoiningDate(formatDate(new Date()));
        setJoiningDateModalOpen(true);
        // Don't set the value yet, wait for modal
        return;
      }
      newData[index][field] = value ? 1 : 0;
    } else {
      newData[index][field] = value === '' ? 0 : parseFloat(value);
    }

    // Recalculate
    const hourlyRate = (newData[index].daily_wage || 0) / workingHours;
    const baseCost = (newData[index].total_hours || 0) * hourlyRate;

    // Late Deduction
    const allowance = newData[index].late_allowance_days ?? globalSettings.allowance;
    const deduction = newData[index].late_deduction_amount ?? globalSettings.deduction;
    const lateMarks = newData[index].late_marks_count || 0;

    const deductableLates = Math.max(0, lateMarks - allowance);
    const totalDeduction = deductableLates * deduction;

    const finalPayout = baseCost - totalDeduction;

    newData[index].base_cost = baseCost.toFixed(2);
    newData[index].late_deduction = totalDeduction.toFixed(2);
    newData[index].final_payout = finalPayout.toFixed(2);
    newData[index].total_cost = finalPayout.toFixed(2);

    setPayrollData(newData);
    setHasChanges(true);
  };

  const saveJoiningDate = () => {
    if (!joiningDatePerson || !tempJoiningDate) return;
    
    const newData = [...payrollData];
    const idx = joiningDatePerson.index;
    newData[idx].joining_date = tempJoiningDate;
    newData[idx].gratuity_enabled = 1;
    
    setPayrollData(newData);
    setHasChanges(true);
    setJoiningDateModalOpen(false);
    setJoiningDatePerson(null);
  };

  const saveGlobalSettings = async () => {
    try {
      const payload = {
        ...globalSettings,
        pf_percentage: pfPercentage,
        esi_percentage: esiPercentage,
        gratuity_percentage: gratuityPercentage,
        gratuity_threshold_years: gratuityYears
      };
      const res = await fetch(`${API_BASE_URL}/settings/late-config`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        alert("Global settings updated!");
        setGlobalSettingsChanged(false);
        fetchPayroll();
      } else {
        alert("Failed to update settings");
      }
    } catch (e) {
      console.error(e);
      alert("Error updating settings");
    }
  };

  const saveWages = async () => {
    setSaveLoading(true);
    try {
      const updates = payrollData.map(p => {
        const u = {};
        if (p.person_id) u.person_id = p.person_id; else u.name = p.name;
        if (typeof p.daily_wage === 'number') u.daily_wage = p.daily_wage;
        if (p.late_allowance_days !== null && p.late_allowance_days !== '' && p.late_allowance_days !== undefined) {
          u.late_allowance_days = p.late_allowance_days;
        }
        if (p.late_deduction_amount !== null && p.late_deduction_amount !== '' && p.late_deduction_amount !== undefined) {
          u.late_deduction_amount = p.late_deduction_amount;
        }
        // New Payroll Fields
        ['basic_salary', 'hra', 'conveyance', 'special_allowance', 'pf_enabled', 'esi_enabled', 'gratuity_enabled', 'professional_tax', 'joining_date'].forEach(f => {
          if (p[f] !== undefined && p[f] !== null) u[f] = p[f];
        });
        return u;
      });

      const res = await fetch(`${API_BASE_URL}/persons/wages`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({ updates })
      });

      if (res.status === 403) {
        const data = await res.json();
        setError(data.error || "Access Denied");
        alert(data.error || "Access Denied");
        return;
      }

      if (res.ok) {
        setHasChanges(false);
        alert("Wages saved successfully!");
        fetchPayroll();
      } else {
        alert("Failed to save wages");
      }
    } catch (error) {
      console.error("Error saving wages:", error);
      alert("Error saving wages");
    } finally {
      setSaveLoading(false);
    }
  };
  const fetchAdvanceHistory = async (personId) => {
    setHistoryLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/persons/advances/${personId}`, {
        headers: { 'Authorization': `Bearer ${user?.token}` }
      });
      const data = await res.json();
      if (data.success) {
        setAdvanceHistory(data.advances);
      }
    } catch (e) {
      console.error("Error fetching advance history", e);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleOpenAdvanceModal = (person) => {
    setAdvancePerson(person);
    setAdvanceAmount('');
    setAdvanceCash('');
    setAdvanceOnline('');
    setEditingAdvance(null);
    setAdvanceModalOpen(true);
    fetchAdvanceHistory(person.person_id);
  };

  const recordAdvance = async () => {
    if (!advancePerson) return;
    const cash = parseFloat(advanceCash || 0);
    const online = parseFloat(advanceOnline || 0);
    const total = cash + online;
    
    if (total <= 0) {
      alert("Please enter a valid amount");
      return;
    }

    const url = editingAdvance 
      ? `${API_BASE_URL}/persons/advances/record/${editingAdvance.id}`
      : `${API_BASE_URL}/persons/advances`;
    const method = editingAdvance ? 'PUT' : 'POST';

    try {
      const res = await fetch(url, {
        method: method,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({
          person_id: advancePerson.person_id,
          amount: total,
          amount_cash: cash,
          amount_online: online,
          deduction_month: deductionMonth
        })
      });

      if (res.ok) {
        alert(editingAdvance ? "Advance updated!" : "Advance recorded!");
        setAdvanceCash('');
        setAdvanceOnline('');
        setAdvanceAmount('');
        setEditingAdvance(null);
        fetchAdvanceHistory(advancePerson.person_id);
        fetchPayroll(true); // Background update main view
      }
    } catch (e) {
      console.error(e);
      alert("Error saving advance");
    }
  };

  const deleteAdvance = async (advanceId) => {
    if (!window.confirm("Are you sure you want to delete this advance record?")) return;
    try {
      const res = await fetch(`${API_BASE_URL}/persons/advances/record/${advanceId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${user?.token}` }
      });
      if (res.ok) {
        fetchAdvanceHistory(advancePerson.person_id);
        fetchPayroll(true);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchOwners = async () => {
    setOwnersLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/vendor/owners`, {
        headers: { 'Authorization': `Bearer ${user?.token}` }
      });
      const data = await res.json();
      if (data.owners) {
        setOwners(data.owners);
      }
    } catch (e) {
      console.error("Error fetching owners", e);
    } finally {
      setOwnersLoading(false);
    }
  };

  const saveOwners = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/vendor/owners`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({ owners })
      });
      if (res.ok) {
        alert("Owner accounts updated successfully!");
        setOwnerConfigModalOpen(false);
      } else {
        const data = await res.json();
        alert("Error: " + (data.error || "Failed to update owners"));
      }
    } catch (e) {
      console.error(e);
      alert("Error saving owners");
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Wages & Payroll</h1>
          <p className="text-sm text-slate-500 mt-1">Manage employee daily wages and calculate estimated costs.</p>
        </div>

        {hasChanges && (
          <button
            onClick={saveWages}
            disabled={saveLoading}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2 shadow-sm transition-all"
          >
            {saveLoading ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Saving...
              </>
            ) : (
              <>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
                Save Changes
              </>
            )}
          </button>
        )}

        {!hasChanges && (
          <button
            onClick={() => { fetchOwners(); setOwnerConfigModalOpen(true); }}
            className="px-4 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-900 flex items-center gap-2 shadow-sm transition-all ml-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
            Manage Owners
          </button>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center gap-2 mb-6">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
          <span className="font-medium">{error}</span>
        </div>
      )}

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
        <div className="flex flex-col sm:flex-row sm:items-end gap-4 mb-6">
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full sm:w-auto px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full sm:w-auto px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
            />
          </div>
          <button
            onClick={fetchPayroll}
            className="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200 hover:text-slate-900 transition-colors text-sm font-medium"
          >
            Refresh Data
          </button>

          <div className="sm:ml-auto flex items-center gap-2 text-xs text-amber-600 bg-amber-50 px-3 py-2 rounded-lg border border-amber-100">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
            Cost is calculated based on exact payable hours (Total Payable Hours × Hourly Rate).
          </div>
        </div>

        {/* Settings Block: Working Hours, Late Config & Statutory Rates */}
        <div className="bg-slate-50 border-b border-slate-200 p-4 rounded-t-lg flex flex-col gap-6 mb-4">
          
          {/* Row 1: Working Hours & Late Config */}
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex items-center gap-2">
              <label className="text-sm font-semibold text-slate-700 whitespace-nowrap">Daily Hours:</label>
              <input
                type="number"
                step="0.5"
                min="1"
                max="24"
                value={workingHours}
                onChange={(e) => {
                  setWorkingHours(e.target.value);
                  setWorkingHoursChanged(true);
                }}
                className="w-16 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
              />
            </div>
            {workingHoursChanged && (
              <button onClick={saveWorkingHours} className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700">Update</button>
            )}

            <div className="flex items-center gap-2 border-l border-slate-200 pl-4">
              <label className="text-sm font-semibold text-slate-700 whitespace-nowrap">Late Allowance:</label>
              <input
                type="number"
                min="0"
                value={globalSettings.allowance}
                onChange={(e) => {
                  setGlobalSettings({ ...globalSettings, allowance: parseInt(e.target.value) || 0 });
                  setGlobalSettingsChanged(true);
                }}
                className="w-12 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
              />
              <span className="text-xs text-slate-500">days</span>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-sm font-semibold text-slate-700 whitespace-nowrap">Deduction:</label>
              <div className="relative">
                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400 text-xs text-[10px]">₹</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={globalSettings.deduction}
                  onChange={(e) => {
                    setGlobalSettings({ ...globalSettings, deduction: parseFloat(e.target.value) || 0 });
                    setGlobalSettingsChanged(true);
                  }}
                  className="w-20 pl-4 pr-1 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div className="flex items-center gap-2 border-l border-slate-200 pl-4">
              <label className="text-sm font-semibold text-slate-700 whitespace-nowrap">TZ Offset:</label>
              <input
                type="number"
                step="0.5"
                value={globalSettings.timezone_offset || 0}
                onChange={(e) => {
                  setGlobalSettings({ ...globalSettings, timezone_offset: parseFloat(e.target.value) || 0 });
                  setGlobalSettingsChanged(true);
                }}
                className="w-16 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Row 2: Statutory Rates (PF, ESI, Gratuity) */}
          <div className="flex flex-wrap items-center gap-6 pt-4 border-t border-slate-200">
            <div className="flex items-center gap-2">
              <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">PF Rate:</label>
              <div className="flex items-center">
                <input
                  type="number"
                  step="0.1"
                  value={pfPercentage}
                  onChange={(e) => {
                    setPfPercentage(parseFloat(e.target.value) || 0);
                    setGlobalSettingsChanged(true);
                  }}
                  className="w-20 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500 font-bold text-slate-700"
                />
                <span className="ml-1 text-slate-400 text-xs">%</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">ESI Rate:</label>
              <div className="flex items-center">
                <input
                  type="number"
                  step="0.01"
                  value={esiPercentage}
                  onChange={(e) => {
                    setEsiPercentage(parseFloat(e.target.value) || 0);
                    setGlobalSettingsChanged(true);
                  }}
                  className="w-20 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500 font-bold text-slate-700"
                />
                <span className="ml-1 text-slate-400 text-xs">%</span>
              </div>
            </div>

            <div className="flex items-center gap-2 border-l border-slate-200 pl-4">
              <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">Gratuity:</label>
              <div className="flex items-center">
                <input
                  type="number"
                  step="0.01"
                  value={gratuityPercentage}
                  onChange={(e) => {
                    setGratuityPercentage(parseFloat(e.target.value) || 0);
                    setGlobalSettingsChanged(true);
                  }}
                  className="w-20 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500 font-bold text-slate-700"
                />
                <span className="ml-1 text-slate-400 text-xs">%</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">Threshold:</label>
              <div className="flex items-center">
                <input
                  type="number"
                  min="0"
                  value={gratuityYears}
                  onChange={(e) => {
                    setGratuityYears(parseInt(e.target.value) || 0);
                    setGlobalSettingsChanged(true);
                  }}
                  className="w-16 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500 font-bold text-slate-700"
                />
                <span className="ml-1 text-slate-400 text-[10px] uppercase font-bold">Years</span>
              </div>
            </div>

            <div className="ml-auto flex items-center gap-2">
              <button onClick={() => fetchPayroll(true)} className="text-xs bg-slate-200 text-slate-700 px-3 py-1.5 rounded hover:bg-slate-300 font-bold">Preview Rates</button>
              {globalSettingsChanged && (
                <button
                  onClick={saveGlobalSettings}
                  className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 transition-colors font-bold shadow-sm"
                >
                  Save Global Settings
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Employee</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Days Present</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Daily Wage</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Statutory (PF/ESI)</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Allowance / Deduction</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">Net Payout</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan="7" className="py-12 text-center text-slate-500">
                    <div className="flex flex-col items-center justify-center">
                      <svg className="animate-spin h-8 w-8 text-slate-400 mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      <p>Loading payroll data...</p>
                    </div>
                  </td>
                </tr>
              ) : payrollData.length === 0 ? (
                <tr>
                  <td colSpan="7" className="py-12 text-center text-slate-500">
                    <p className="text-lg font-medium text-slate-900">No records found</p>
                    <p>Try selecting a different date range.</p>
                  </td>
                </tr>
              ) : (
                payrollData.map((person, index) => (
                  <tr key={person.name} className="hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-slate-200 overflow-hidden flex-shrink-0 border border-slate-300">
                          {person.face_image ? (
                            <img
                              src={person.face_image.startsWith('data:') ? person.face_image : `data:image/jpeg;base64,${person.face_image}`}
                              alt={person.name}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center text-slate-400 font-bold text-xs">
                              {person.name.substring(0, 2).toUpperCase()}
                            </div>
                          )}
                        </div>
                        <div onClick={() => { setDetailsPerson(person); setDetailsOpen(true); }} className="cursor-pointer">
                          <p className="font-medium text-slate-900 text-sm">{person.name}</p>
                          <p className="text-xs text-slate-500 font-mono">ID: #{person.display_id || person.person_id}</p>
                          <p className="text-[10px] text-slate-400">
                            {person.custom_data?.student_number ||
                              person.custom_data?.roll_number ||
                              person.custom_data?.admission_number || ""}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <div className="flex flex-col items-center">
                        <span className="text-sm font-medium text-slate-600">{person.days_present} days</span>
                        <span className="text-[10px] text-slate-400">{person.total_hours_str || `${person.total_hours} hrs`}</span>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <div className="flex items-center justify-center gap-2">
                        <span className="text-slate-400 text-sm">₹</span>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={person.daily_wage}
                          onChange={(e) => handleWageChange(index, 'daily_wage', e.target.value)}
                          className="w-20 px-2 py-1 border border-slate-200 rounded text-right text-sm focus:ring-2 focus:ring-blue-500 font-medium text-slate-700 bg-slate-50 focus:bg-white"
                          placeholder="0.00"
                        />
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col gap-1 items-center">
                        <div className="flex items-center gap-2">
                          <label className="flex items-center gap-1 text-[10px] font-bold text-slate-500 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={person.pf_enabled}
                              onChange={(e) => handleWageChange(index, 'pf_enabled', e.target.checked)}
                              className="w-3 h-3 rounded text-blue-600"
                            />
                            PF
                          </label>
                          {person.pf_enabled && (
                            <span className="text-[10px] font-bold text-blue-600">₹{person.breakdown?.deductions?.pf || 0}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <label className="flex items-center gap-1 text-[10px] font-bold text-slate-500 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={person.esi_enabled}
                              onChange={(e) => handleWageChange(index, 'esi_enabled', e.target.checked)}
                              className="w-3 h-3 rounded text-green-600"
                            />
                            ESI
                          </label>
                          {person.esi_enabled && (
                            <span className="text-[10px] font-bold text-green-600">₹{person.breakdown?.deductions?.esi || 0}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <label className="flex items-center gap-1 text-[10px] font-bold text-slate-500 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={person.gratuity_enabled}
                              onChange={(e) => handleWageChange(index, 'gratuity_enabled', e.target.checked)}
                              className="w-3 h-3 rounded text-amber-600"
                            />
                            GRA
                          </label>
                          {person.gratuity_enabled && (
                            <span className="text-[10px] font-bold text-amber-600" title="Provision">₹{person.breakdown?.provisions?.gratuity || 0}</span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col gap-1 items-center">
                        <div className="flex items-center gap-1 text-xs">
                          <span className="text-slate-500">Allow:</span>
                          <input
                            type="number"
                            min="0"
                            placeholder={globalSettings.allowance}
                            value={person.late_allowance_days ?? ''}
                            onChange={(e) => handleWageChange(index, 'late_allowance_days', e.target.value)}
                            className="w-12 px-1 py-0.5 border border-slate-200 rounded text-center text-xs"
                          />
                        </div>
                        <div className="flex items-center gap-1 text-xs">
                          <span className="text-slate-500">Deduct:</span>
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            placeholder={globalSettings.deduction}
                            value={person.late_deduction_amount ?? ''}
                            onChange={(e) => handleWageChange(index, 'late_deduction_amount', e.target.value)}
                            className="w-12 px-1 py-0.5 border border-slate-200 rounded text-center text-xs"
                          />
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <div className="text-sm font-bold text-slate-900 block cursor-help" title={`Basic: ₹${person.breakdown?.components?.basic || 0}\nHRA: ₹${person.breakdown?.components?.hra || 0}\nDed: ₹${person.breakdown?.deductions?.total_statutory || 0}`}>
                        ₹ {parseFloat(person.final_payout || person.total_cost || 0).toFixed(2)}
                      </div>
                      {(parseFloat(person.late_deduction || 0) > 0 || parseFloat(person.advance_deduction || 0) > 0) && (
                        <div className="flex flex-col items-end">
                          {parseFloat(person.late_deduction || 0) > 0 && (
                            <span className="text-[10px] text-red-500 block">
                              - ₹{person.late_deduction} (Late)
                            </span>
                          )}
                          {parseFloat(person.advance_deduction || 0) > 0 && (
                            <span className="text-[10px] text-amber-600 block">
                              - ₹{person.advance_deduction} (Advance)
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-4 text-center">
                      <button
                        onClick={() => handleOpenAdvanceModal(person)}
                        className="p-1.5 text-blue-600 hover:bg-blue-50 rounded transition-colors"
                        title="Manage Advances"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14"/></svg>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
            {payrollData.length > 0 && (
              <tfoot className="bg-slate-50 font-semibold text-slate-900 border-t border-slate-300">
                <tr>
                  <td colSpan="6" className="py-3 px-4 text-right text-sm uppercase tracking-wider">Total Estimated Cost</td>
                  <td className="py-3 px-4 text-right text-base text-blue-700">
                    ₹{payrollData.reduce((acc, curr) => acc + parseFloat(curr.final_payout || curr.total_cost || 0), 0).toFixed(2)}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>
      {advanceModalOpen && advancePerson && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden transform transition-all flex flex-col max-h-[90vh]">
            <div className="bg-blue-600 p-6 text-white flex justify-between items-center">
              <div>
                <h2 className="text-xl font-bold">{editingAdvance ? 'Edit' : 'Manage'} Advance Payments</h2>
                <p className="text-blue-100 text-sm mt-1">For {advancePerson.name}</p>
              </div>
              <button onClick={() => setAdvanceModalOpen(false)} className="text-white/80 hover:text-white">&times;</button>
            </div>
            
            <div className="p-6 space-y-6 overflow-y-auto">
              {/* Form Section */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200">
                <h3 className="text-sm font-bold text-slate-800 mb-4">{editingAdvance ? 'Editing Record' : 'Add New Advance'}</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500 uppercase mb-1">Cash Amount (₹)</label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-emerald-600 font-bold">C</span>
                      <input
                        type="number"
                        value={advanceCash}
                        onChange={(e) => setAdvanceCash(e.target.value)}
                        className="w-full pl-8 pr-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition-all font-bold text-emerald-700"
                        placeholder="0.00"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500 uppercase mb-1">Online Amount (₹)</label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-blue-600 font-bold">O</span>
                      <input
                        type="number"
                        value={advanceOnline}
                        onChange={(e) => setAdvanceOnline(e.target.value)}
                        className="w-full pl-8 pr-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-bold text-blue-700"
                        placeholder="0.00"
                      />
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 mt-4">
                  <div className="bg-slate-100 px-3 py-2 rounded-lg flex justify-between items-center border border-slate-200">
                    <span className="text-[10px] font-bold text-slate-500 uppercase">Total</span>
                    <span className="font-bold text-slate-800">₹ {(parseFloat(advanceCash || 0) + parseFloat(advanceOnline || 0)).toFixed(2)}</span>
                  </div>
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500 uppercase mb-1">Deduction Month</label>
                    <input
                      type="month"
                      value={deductionMonth}
                      onChange={(e) => setDeductionMonth(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
                    />
                  </div>
                </div>

                <div className="flex gap-2 mt-4">
                  <button
                    onClick={recordAdvance}
                    disabled={(parseFloat(advanceCash || 0) + parseFloat(advanceOnline || 0)) <= 0}
                    className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-semibold shadow-sm transition-all text-sm"
                  >
                    {editingAdvance ? 'Update Record' : 'Record Payment'}
                  </button>
                  {editingAdvance && (
                    <button
                      onClick={() => { setEditingAdvance(null); setAdvanceCash(''); setAdvanceOnline(''); setAdvanceAmount(''); }}
                      className="px-4 py-2 bg-slate-200 text-slate-700 rounded-lg hover:bg-slate-300 font-semibold text-sm"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>

              {/* History Section */}
              <div>
                <h3 className="text-sm font-bold text-slate-800 mb-3 flex justify-between">
                  <span>Advance History</span>
                  {historyLoading && <span className="animate-pulse text-blue-500">Loading...</span>}
                </h3>
                <div className="border border-slate-200 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-100 text-slate-600 font-bold uppercase tracking-wider">
                      <tr>
                        <th className="py-2 px-3">Date</th>
                        <th className="py-2 px-3">Amount</th>
                        <th className="py-2 px-3">Month</th>
                        <th className="py-2 px-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {advanceHistory.length === 0 ? (
                        <tr><td colSpan="4" className="py-8 text-center text-slate-400">No previous records found</td></tr>
                      ) : (
                        advanceHistory.map(h => (
                          <tr key={h.id} className={editingAdvance?.id === h.id ? 'bg-blue-50' : ''}>
                            <td className="py-2 px-3">{new Date(h.date).toLocaleDateString()}</td>
                            <td className="py-2 px-3">
                              <div className="font-bold text-slate-700">₹{h.amount}</div>
                              <div className="flex gap-2 mt-0.5">
                                {parseFloat(h.amount_cash || 0) > 0 && <span className="text-[9px] bg-emerald-100 text-emerald-700 px-1 rounded font-bold">C: ₹{h.amount_cash}</span>}
                                {parseFloat(h.amount_online || 0) > 0 && <span className="text-[9px] bg-blue-100 text-blue-700 px-1 rounded font-bold">O: ₹{h.amount_online}</span>}
                              </div>
                            </td>
                            <td className="py-2 px-3 text-slate-500">{h.deduction_month}</td>
                            <td className="py-2 px-3 text-right space-x-2">
                              <button 
                                onClick={() => {
                                  setEditingAdvance(h);
                                  setAdvanceCash(h.amount_cash || 0);
                                  setAdvanceOnline(h.amount_online || 0);
                                  setAdvanceAmount(h.amount);
                                  setDeductionMonth(h.deduction_month);
                                }}
                                className="text-blue-600 hover:text-blue-800 font-bold"
                              >
                                Edit
                              </button>
                              <button 
                                onClick={() => deleteAdvance(h.id)}
                                className="text-red-500 hover:text-red-700 font-bold"
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
            
            <div className="p-4 bg-slate-50 border-t border-slate-200 text-right">
              <button
                onClick={() => setAdvanceModalOpen(false)}
                className="px-6 py-2 bg-white border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-100 font-semibold transition-all text-sm"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {joiningDateModalOpen && joiningDatePerson && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden transform transition-all flex flex-col">
            <div className="bg-amber-600 p-6 text-white text-center">
              <h2 className="text-xl font-bold">Set Joining Date</h2>
              <p className="text-amber-100 text-sm mt-1">Required for Gratuity threshold for {joiningDatePerson.name}</p>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-[11px] font-bold text-slate-500 uppercase mb-1">Joining Date</label>
                <input
                  type="date"
                  value={tempJoiningDate}
                  onChange={(e) => setTempJoiningDate(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-amber-500/20 focus:border-amber-500 transition-all text-sm font-bold"
                />
              </div>
              <p className="text-[10px] text-slate-400 italic">
                This date is used to calculate tenure. If the employee was working before this system, please select their original start date.
              </p>
              <div className="flex gap-2 pt-2">
                <button
                  onClick={saveJoiningDate}
                  className="flex-1 px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 font-semibold shadow-sm text-sm"
                >
                  Set Date & Enable GRA
                </button>
                <button
                  onClick={() => { setJoiningDateModalOpen(false); setJoiningDatePerson(null); }}
                  className="px-4 py-2 bg-slate-200 text-slate-700 rounded-lg hover:bg-slate-300 font-semibold text-sm"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      
      {ownerConfigModalOpen && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[70] p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl overflow-hidden transform transition-all flex flex-col max-h-[90vh]">
            <div className="bg-slate-800 p-6 text-white flex justify-between items-center">
              <div>
                <h2 className="text-xl font-bold">Manage Owner Mobile Access</h2>
                <p className="text-slate-400 text-sm mt-1">Configure multiple owner accounts for mobile approval</p>
              </div>
              <button onClick={() => setOwnerConfigModalOpen(false)} className="text-slate-400 hover:text-white transition-colors">
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto space-y-4 flex-1">
              {ownersLoading ? (
                <div className="flex flex-col items-center py-12 text-slate-400">
                  <svg className="animate-spin h-8 w-8 mb-4 text-slate-300" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <span>Loading owner accounts...</span>
                </div>
              ) : (
                <>
                  <div className="space-y-3">
                    {owners.map((owner, idx) => (
                      <div key={idx} className="flex gap-2 items-center bg-slate-50 p-4 rounded-xl border border-slate-200">
                        <div className="flex-1 space-y-2">
                          <label className="text-[10px] font-black text-slate-400 uppercase tracking-wider">Owner Email / Username</label>
                          <input 
                            type="text"
                            value={owner.username}
                            onChange={(e) => {
                              const newOwners = [...owners];
                              newOwners[idx] = { ...newOwners[idx], username: e.target.value };
                              setOwners(newOwners);
                            }}
                            placeholder="owner@company.com"
                            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-500/20 focus:border-slate-800 transition-all text-sm font-bold"
                          />
                        </div>
                        <div className="flex-1 space-y-2">
                          <label className="text-[10px] font-black text-slate-400 uppercase tracking-wider">Password (Update)</label>
                          <input 
                            type="text"
                            value={owner.password || ''}
                            onChange={(e) => {
                              const newOwners = [...owners];
                              newOwners[idx] = { ...newOwners[idx], password: e.target.value };
                              setOwners(newOwners);
                            }}
                            placeholder="New password"
                            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-500/20 focus:border-slate-800 transition-all text-sm font-bold"
                          />
                        </div>
                        <button 
                          onClick={() => {
                            const newOwners = owners.filter((_, i) => i !== idx);
                            setOwners(newOwners);
                          }}
                          className="mt-6 p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                        </button>
                      </div>
                    ))}
                  </div>
                  
                  <button 
                    onClick={() => setOwners([...owners, { username: '', password: '' }])}
                    className="w-full py-3 border-2 border-dashed border-slate-200 rounded-xl text-slate-400 hover:text-slate-600 hover:border-slate-300 hover:bg-slate-50 transition-all flex items-center justify-center gap-2 text-sm font-bold"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                    Add Another Owner Account
                  </button>
                </>
              )}
            </div>
            
            <div className="p-6 bg-slate-50 border-t border-slate-200 flex gap-3">
              <button
                onClick={() => setOwnerConfigModalOpen(false)}
                className="flex-1 py-3 bg-white border border-slate-200 text-slate-600 rounded-xl hover:bg-slate-100 font-bold transition-all text-sm"
              >
                Cancel
              </button>
              <button
                onClick={saveOwners}
                className="flex-[2] py-3 bg-slate-800 text-white rounded-xl hover:bg-slate-900 font-bold shadow-lg shadow-slate-200 transition-all text-sm"
              >
                Save Owner Access
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Wages;
