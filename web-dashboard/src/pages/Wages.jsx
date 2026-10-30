import React, { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../config';
import { useAuth } from '../context/AuthContext';
import { useSocket } from '../context/SocketContext';

const Wages = () => {
  const { user } = useAuth();
  const { socket } = useSocket();
  const imageSource = (value) => {
    if (!value) return '';
    if (value.startsWith('/') || value.startsWith('data:') || value.startsWith('http://') || value.startsWith('https://')) return value;
    return `data:image/jpeg;base64,${value}`;
  };

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
  const [dirtyPersonIds, setDirtyPersonIds] = useState(new Set());
  const [saveLoading, setSaveLoading] = useState(false);
  const [salarySaveOpen, setSalarySaveOpen] = useState(false);
  const [salaryPassword, setSalaryPassword] = useState('');
  const [salaryEffectiveDate, setSalaryEffectiveDate] = useState(formatDate(new Date()));
  const [salaryChangeReason, setSalaryChangeReason] = useState('');
  const [salarySaveError, setSalarySaveError] = useState('');
  const [salaryHistoryOpen, setSalaryHistoryOpen] = useState(false);
  const [salaryHistoryPerson, setSalaryHistoryPerson] = useState(null);
  const [salaryHistory, setSalaryHistory] = useState([]);
  const [salaryHistoryLoading, setSalaryHistoryLoading] = useState(false);
  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [finalizePassword, setFinalizePassword] = useState('');
  const [finalizeError, setFinalizeError] = useState('');
  const [finalizeLoading, setFinalizeLoading] = useState(false);
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
  const [ownersSaving, setOwnersSaving] = useState(false);
  const [disableStatutoryOpen, setDisableStatutoryOpen] = useState(false);
  const [disableStatutoryPassword, setDisableStatutoryPassword] = useState('');
  const [disableStatutoryError, setDisableStatutoryError] = useState('');
  const lateMarkEnabled = Boolean(user?.features?.includes('late_mark'));
  const payrollRequestRef = useRef(null);

  const markSalaryDirty = (personId) => {
    if (!personId) return;
    setDirtyPersonIds(current => {
      const next = new Set(current);
      next.add(Number(personId));
      return next;
    });
  };

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
    const background = isBackground === true;
    if (background && payrollRequestRef.current) return;
    if (payrollRequestRef.current) payrollRequestRef.current.abort();
    const controller = new AbortController();
    payrollRequestRef.current = controller;
    if (!background) setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        pf_percentage: String(pfPercentage),
        esi_percentage: String(esiPercentage),
        gratuity_percentage: String(gratuityPercentage),
        include_images: 'false',
      });
      const res = await fetch(`${API_BASE_URL}/reports/payroll?${params.toString()}`, {
        signal: controller.signal,
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
      if (error.name !== 'AbortError') console.error("Error fetching payroll:", error);
    } finally {
      if (payrollRequestRef.current === controller) {
        payrollRequestRef.current = null;
        if (!background) setLoading(false);
      }
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
      }, 30000);
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

  useEffect(() => () => {
    if (payrollRequestRef.current) payrollRequestRef.current.abort();
  }, []);

  const recalculatePayrollPerson = (person) => {
    const hourlyRate = (person.daily_wage || 0) / Math.max(parseFloat(workingHours) || 0, 0.01);
    const baseCost = (person.total_hours || 0) * hourlyRate;
    const allowance = lateMarkEnabled ? (person.late_allowance_days ?? globalSettings.allowance) : 0;
    const deduction = lateMarkEnabled ? (person.late_deduction_amount ?? globalSettings.deduction) : 0;
    const lateMarks = lateMarkEnabled ? (person.late_marks_count || 0) : 0;
    const lateDeduction = Math.max(0, lateMarks - allowance) * deduction;

    const configuredBasic = parseFloat(person.basic_salary || 0);
    const configuredHra = parseFloat(person.hra || 0);
    const configuredConveyance = parseFloat(person.conveyance || 0);
    const configuredSpecial = parseFloat(person.special_allowance || 0);
    const basic = configuredBasic || baseCost * 0.5;
    const hra = configuredHra || baseCost * 0.2;
    const conveyance = configuredConveyance || 0;
    const specialAllowance = configuredSpecial || Math.max(0, baseCost - basic - hra - conveyance);
    const gross = basic + hra + conveyance + specialAllowance;
    const pf = person.pf_enabled ? Math.min(basic, 15000) * (parseFloat(pfPercentage) / 100) : 0;
    const esi = person.esi_enabled && gross <= 21000 ? gross * (parseFloat(esiPercentage) / 100) : 0;
    const professionalTax = parseFloat(person.professional_tax || 0);
    const statutoryDeduction = pf + esi + professionalTax;
    const advanceDeduction = parseFloat(person.advance_deduction || 0);
    const finalPayout = gross - statutoryDeduction - lateDeduction - advanceDeduction;

    return {
      ...person,
      base_cost: baseCost.toFixed(2),
      late_deduction: lateDeduction.toFixed(2),
      breakdown: {
        ...(person.breakdown || {}),
        components: { basic, hra, conveyance, special_allowance: specialAllowance },
        deductions: { pf, esi, pt: professionalTax, total_statutory: statutoryDeduction },
        gross,
        net_before_advances: gross - statutoryDeduction,
      },
      final_payout: finalPayout.toFixed(2),
      total_cost: finalPayout.toFixed(2),
    };
  };

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

    newData[index] = recalculatePayrollPerson(newData[index]);

    setPayrollData(newData);
    setHasChanges(true);
    markSalaryDirty(newData[index].person_id);
  };

  const enablePfAndEsiForAll = () => {
    if (!payrollData.length) return;
    const updated = payrollData.map(person => recalculatePayrollPerson({
      ...person,
      pf_enabled: 1,
      esi_enabled: 1,
    }));
    setPayrollData(updated);
    setHasChanges(true);
    setDirtyPersonIds(new Set(updated.map(person => Number(person.person_id)).filter(Boolean)));
  };

  const disablePfAndEsiForAll = () => {
    if (!disableStatutoryPassword) return;
    setDisableStatutoryError('');
    const updated = payrollData.map(person => recalculatePayrollPerson({
      ...person,
      pf_enabled: 0,
      esi_enabled: 0,
    }));
    setPayrollData(updated);
    setDirtyPersonIds(new Set(updated.map(person => Number(person.person_id)).filter(Boolean)));
    setHasChanges(true);
    setDisableStatutoryOpen(false);
    setSalaryPassword(disableStatutoryPassword);
    setDisableStatutoryPassword('');
    setSalaryEffectiveDate(formatDate(new Date()));
    setSalaryChangeReason('Disable PF and ESI for all employees');
    setSalarySaveError('');
    setSalarySaveOpen(true);
  };

  const saveJoiningDate = () => {
    if (!joiningDatePerson || !tempJoiningDate) return;
    
    const newData = [...payrollData];
    const idx = joiningDatePerson.index;
    newData[idx].joining_date = tempJoiningDate;
    newData[idx].gratuity_enabled = 1;
    
    setPayrollData(newData);
    setHasChanges(true);
    markSalaryDirty(newData[idx].person_id);
    setJoiningDateModalOpen(false);
    setJoiningDatePerson(null);
  };

  const saveGlobalSettings = async () => {
    try {
      const payload = {
        pf_percentage: pfPercentage,
        esi_percentage: esiPercentage,
        gratuity_percentage: gratuityPercentage,
        gratuity_threshold_years: gratuityYears
      };
      if (lateMarkEnabled) {
        payload.allowance = globalSettings.allowance;
        payload.deduction = globalSettings.deduction;
      }
      if (globalSettings.timezone_offset !== undefined) payload.timezone_offset = globalSettings.timezone_offset;
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
    if (!salaryPassword) {
      setSalarySaveError('Enter your current login password.');
      return;
    }
    if (!salaryEffectiveDate || salaryEffectiveDate > formatDate(new Date())) {
      setSalarySaveError('Choose today or an earlier effective date.');
      return;
    }
    if (salaryChangeReason.trim().length < 3) {
      setSalarySaveError('Enter a short reason for this salary change.');
      return;
    }
    setSaveLoading(true);
    setSalarySaveError('');
    try {
      const updates = payrollData.filter(p => dirtyPersonIds.has(Number(p.person_id))).map(p => {
        const u = { person_id: p.person_id };
        if (p.salary_version !== undefined && p.salary_version !== null) {
          u.expected_salary_version = p.salary_version;
        }
        if (typeof p.daily_wage === 'number') u.daily_wage = p.daily_wage;
        if (lateMarkEnabled && p.late_allowance_days !== '' && p.late_allowance_days !== undefined) {
          u.late_allowance_days = p.late_allowance_days;
        }
        if (lateMarkEnabled && p.late_deduction_amount !== '' && p.late_deduction_amount !== undefined) {
          u.late_deduction_amount = p.late_deduction_amount;
        }
        ['basic_salary', 'hra', 'conveyance', 'special_allowance', 'pf_enabled', 'esi_enabled', 'gratuity_enabled', 'professional_tax', 'joining_date'].forEach(f => {
          if (p[f] !== undefined && p[f] !== null) u[f] = p[f];
        });
        return u;
      });

      if (!updates.length) {
        setSalarySaveError('No employee salary changes were selected.');
        return;
      }

      const confirmationResponse = await fetch(`${API_BASE_URL}/persons/wages/reauth`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({ password: salaryPassword, purpose: 'salary_change' })
      });
      const confirmation = await confirmationResponse.json().catch(() => ({}));
      if (!confirmationResponse.ok || !confirmation.reauth_token) {
        setSalarySaveError(confirmation.error || 'The password could not be confirmed.');
        return;
      }

      const res = await fetch(`${API_BASE_URL}/persons/wages`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({
          updates,
          reauth_token: confirmation.reauth_token,
          effective_from: salaryEffectiveDate,
          change_reason: salaryChangeReason.trim(),
        })
      });

      const result = await res.json().catch(() => ({}));

      if (res.ok) {
        setHasChanges(false);
        setDirtyPersonIds(new Set());
        setSalarySaveOpen(false);
        setSalaryPassword('');
        setSalaryChangeReason('');
        alert(`Salary history updated for ${result.changed?.length ?? updates.length} employee(s).`);
        fetchPayroll();
      } else {
        const errMsg = result.error || "Failed to save salary changes";
        console.error("Save wages error:", errMsg);
        setSalarySaveError(errMsg);
      }
    } catch (error) {
      console.error("Error saving wages:", error);
      setSalarySaveError("Could not reach the server. Please try again.");
    } finally {
      setSaveLoading(false);
    }
  };

  const openSalarySave = () => {
    setSalaryPassword('');
    setSalaryEffectiveDate(formatDate(new Date()));
    setSalaryChangeReason('');
    setSalarySaveError('');
    setSalarySaveOpen(true);
  };

  const openSalaryHistory = async (person) => {
    setSalaryHistoryPerson(person);
    setSalaryHistory([]);
    setSalaryHistoryOpen(true);
    setSalaryHistoryLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/persons/${person.person_id}/salary-versions`, {
        headers: { 'Authorization': `Bearer ${user?.token}` }
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Could not load salary history');
      setSalaryHistory(data.versions || []);
    } catch (historyError) {
      setSalaryHistory([{ error: historyError.message }]);
    } finally {
      setSalaryHistoryLoading(false);
    }
  };

  const finalizePayroll = async () => {
    if (!finalizePassword || finalizeLoading) {
      if (!finalizePassword) setFinalizeError('Enter your current login password.');
      return;
    }
    setFinalizeLoading(true);
    setFinalizeError('');
    try {
      const confirmationResponse = await fetch(`${API_BASE_URL}/persons/wages/reauth`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({ password: finalizePassword, purpose: 'payroll_finalize' })
      });
      const confirmation = await confirmationResponse.json().catch(() => ({}));
      if (!confirmationResponse.ok || !confirmation.reauth_token) {
        setFinalizeError(confirmation.error || 'The password could not be confirmed.');
        return;
      }

      const params = new URLSearchParams({
        pf_percentage: String(pfPercentage),
        esi_percentage: String(esiPercentage),
        gratuity_percentage: String(gratuityPercentage),
        include_images: 'false',
      });
      const response = await fetch(`${API_BASE_URL}/reports/payroll/finalize?${params.toString()}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${user?.token}`
        },
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          reauth_token: confirmation.reauth_token,
        })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        setFinalizeError(result.error || 'Could not finalize this payroll period.');
        return;
      }
      setFinalizeOpen(false);
      setFinalizePassword('');
      alert(`Payroll finalized. Run #${result.run_id} contains ${result.employee_count} employee(s).`);
    } catch (_) {
      setFinalizeError('Could not reach the server. Please try again.');
    } finally {
      setFinalizeLoading(false);
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
    setOwnersSaving(true);
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
        const data = await res.json().catch(() => ({}));
        alert("Error: " + (data.error || "Failed to update owners"));
      }
    } catch (e) {
      console.error(e);
      alert("Error: Could not reach the server. Please try again.");
    } finally {
      setOwnersSaving(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Wages & Payroll</h1>
          <p className="text-sm text-slate-500 mt-1">Manage employee daily wages and calculate estimated costs.</p>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={enablePfAndEsiForAll}
            disabled={!payrollData.length || loading}
            className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-2 shadow-sm transition-all"
            title="Enable PF and ESI for every employee shown below; gratuity remains unchanged"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/><path d="M16 6h4v4"/></svg>
            Enable PF &amp; ESI for All
          </button>
          <button
            type="button"
            onClick={() => {
              setDisableStatutoryPassword('');
              setDisableStatutoryError('');
              setDisableStatutoryOpen(true);
            }}
            disabled={!payrollData.length || loading}
            className="px-4 py-2 bg-white text-red-700 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50 flex items-center gap-2 shadow-sm transition-all"
            title="Password-confirm and disable PF and ESI for every employee in this business"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
            Disable PF &amp; ESI for All
          </button>

        {hasChanges && (
          <button
            onClick={openSalarySave}
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

        <button
          type="button"
          onClick={() => {
            setFinalizePassword('');
            setFinalizeError('');
            setFinalizeOpen(true);
          }}
          disabled={!payrollData.length || loading || hasChanges}
          className="px-4 py-2 bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2 shadow-sm transition-all"
          title={hasChanges ? 'Save salary changes before finalizing payroll' : 'Create an immutable payroll record for this date range'}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/></svg>
          Finalize Payroll
        </button>

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

            {lateMarkEnabled && <div className="flex items-center gap-2 border-l border-slate-200 pl-4">
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
            </div>}

            {lateMarkEnabled && <div className="flex items-center gap-2">
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
            </div>}

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
                {lateMarkEnabled && <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Late Allowance / Deduction</th>}
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">Net Payout</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={lateMarkEnabled ? 7 : 6} className="py-12 text-center text-slate-500">
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
                  <td colSpan={lateMarkEnabled ? 7 : 6} className="py-12 text-center text-slate-500">
                    <p className="text-lg font-medium text-slate-900">No records found</p>
                    <p>Try selecting a different date range.</p>
                  </td>
                </tr>
              ) : (
                payrollData.map((person, index) => (
                  <tr key={person.name} className="hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-3">
                        <div className="relative w-10 h-10 rounded-full bg-slate-200 overflow-hidden flex-shrink-0 border border-slate-300">
                          <div className="absolute inset-0 flex items-center justify-center text-slate-400 font-bold text-xs">
                            {person.name.substring(0, 2).toUpperCase()}
                          </div>
                          {person.face_image || person.image_url ? (
                            <img
                              src={imageSource(person.image_url || person.face_image)}
                              alt={person.name}
                              className="relative z-10 w-full h-full object-cover"
                              onError={(event) => { event.currentTarget.style.display = 'none'; }}
                            />
                          ) : null}
                        </div>
                        <div onClick={() => { setDetailsPerson(person); setDetailsOpen(true); }} className="cursor-pointer">
                          <p className="font-medium text-slate-900 text-sm">{person.name}</p>
                          <p className="text-xs text-slate-500 font-mono">ID: #{person.display_id || person.person_id}</p>
                          <p className="text-[10px] text-slate-400">
                            {person.custom_data?.student_id || ""}
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
                    {lateMarkEnabled && <td className="py-3 px-4">
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
                    </td>}
                    <td className="py-3 px-4 text-right">
                      <div className="text-sm font-bold text-slate-900 block cursor-help" title={`Basic: ₹${person.breakdown?.components?.basic || 0}\nHRA: ₹${person.breakdown?.components?.hra || 0}\nDed: ₹${person.breakdown?.deductions?.total_statutory || 0}`}>
                        ₹ {parseFloat(person.final_payout || person.total_cost || 0).toFixed(2)}
                      </div>
                      {(parseFloat(person.late_deduction || 0) > 0 || parseFloat(person.advance_deduction || 0) > 0) && (
                        <div className="flex flex-col items-end">
                          {lateMarkEnabled && parseFloat(person.late_deduction || 0) > 0 && (
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
                        onClick={() => openSalaryHistory(person)}
                        className="p-1.5 text-slate-600 hover:bg-slate-100 rounded transition-colors"
                        title="View Salary History"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>
                      </button>
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
      {finalizeOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="border-b border-slate-200 px-6 py-5">
              <h3 className="text-lg font-bold text-slate-900">Finalize Payroll</h3>
              <p className="mt-1 text-sm text-slate-500">{startDate} to {endDate}</p>
            </div>
            <div className="space-y-4 px-6 py-5">
              <div className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-sm text-violet-800">
                This creates a permanent snapshot of hours, salary versions, deductions, and net payouts. It cannot be edited later.
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Current Login Password</label>
                <input type="password" value={finalizePassword} onChange={(event) => setFinalizePassword(event.target.value)} autoComplete="current-password" className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-violet-500 focus:ring-2 focus:ring-violet-100" onKeyDown={(event) => { if (event.key === 'Enter' && !finalizeLoading) finalizePayroll(); }} />
              </div>
              {finalizeError && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{finalizeError}</div>}
            </div>
            <div className="flex justify-end gap-3 border-t border-slate-200 bg-slate-50 px-6 py-4">
              <button type="button" disabled={finalizeLoading} onClick={() => setFinalizeOpen(false)} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50">Cancel</button>
              <button type="button" disabled={finalizeLoading} onClick={finalizePayroll} className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-700 disabled:cursor-wait disabled:opacity-60">{finalizeLoading ? 'Finalizing…' : 'Confirm & Finalize'}</button>
            </div>
          </div>
        </div>
      )}

      {salarySaveOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="border-b border-slate-200 px-6 py-5">
              <h3 className="text-lg font-bold text-slate-900">Confirm Salary Change</h3>
              <p className="mt-1 text-sm text-slate-500">
                {dirtyPersonIds.size} employee record{dirtyPersonIds.size === 1 ? '' : 's'} will receive a new salary version.
              </p>
            </div>
            <div className="space-y-4 px-6 py-5">
              <div>
                <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Effective From</label>
                <input type="date" max={formatDate(new Date())} value={salaryEffectiveDate} onChange={(event) => setSalaryEffectiveDate(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                <p className="mt-1 text-xs text-slate-500">Attendance before this date keeps the previous salary.</p>
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Reason</label>
                <textarea value={salaryChangeReason} onChange={(event) => setSalaryChangeReason(event.target.value)} maxLength={500} rows={3} placeholder="Example: Annual salary revision" className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold uppercase tracking-wide text-slate-500">Current Login Password</label>
                <input type="password" value={salaryPassword} onChange={(event) => setSalaryPassword(event.target.value)} autoComplete="current-password" placeholder="Confirm this change with your password" className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-100" onKeyDown={(event) => { if (event.key === 'Enter' && !saveLoading) saveWages(); }} />
              </div>
              {salarySaveError && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{salarySaveError}</div>}
            </div>
            <div className="flex justify-end gap-3 border-t border-slate-200 bg-slate-50 px-6 py-4">
              <button type="button" disabled={saveLoading} onClick={() => setSalarySaveOpen(false)} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50">Cancel</button>
              <button type="button" disabled={saveLoading} onClick={saveWages} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60">{saveLoading ? 'Saving…' : 'Confirm & Save'}</button>
            </div>
          </div>
        </div>
      )}

      {salaryHistoryOpen && salaryHistoryPerson && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
          <div className="flex max-h-[80vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
              <div>
                <h3 className="text-lg font-bold text-slate-900">Salary History</h3>
                <p className="mt-1 text-sm text-slate-500">{salaryHistoryPerson.name} · ID #{salaryHistoryPerson.display_id || salaryHistoryPerson.person_id}</p>
              </div>
              <button onClick={() => setSalaryHistoryOpen(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
            </div>
            <div className="overflow-auto px-6 py-5">
              {salaryHistoryLoading ? (
                <div className="py-12 text-center text-sm text-slate-500">Loading salary history…</div>
              ) : salaryHistory[0]?.error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{salaryHistory[0].error}</div>
              ) : salaryHistory.length === 0 ? (
                <div className="py-12 text-center text-sm text-slate-500">No salary history is available yet.</div>
              ) : (
                <table className="w-full border-collapse text-left text-sm">
                  <thead><tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500"><th className="px-3 py-3">Version</th><th className="px-3 py-3">Effective Period</th><th className="px-3 py-3 text-right">Daily Wage</th><th className="px-3 py-3">Changed By</th><th className="px-3 py-3">Reason</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {salaryHistory.map(version => (
                      <tr key={version.id} className="align-top">
                        <td className="px-3 py-3 font-semibold text-slate-800">v{version.version_number}</td>
                        <td className="px-3 py-3 text-slate-600">{version.effective_from} to {version.effective_to || 'Current'}</td>
                        <td className="px-3 py-3 text-right font-semibold text-slate-900">₹{Number(version.daily_wage || 0).toFixed(2)}</td>
                        <td className="px-3 py-3 text-slate-600">{version.changed_by}</td>
                        <td className="max-w-xs px-3 py-3 text-slate-600">{version.change_reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="flex justify-end border-t border-slate-200 bg-slate-50 px-6 py-4"><button onClick={() => setSalaryHistoryOpen(false)} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100">Close</button></div>
          </div>
        </div>
      )}

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
                              {h.edit_history?.length > 0 && (
                                <details className="mt-2 text-[10px] text-slate-500">
                                  <summary className="cursor-pointer font-semibold text-amber-700">
                                    Edited {h.edit_history.length} time{h.edit_history.length === 1 ? '' : 's'}
                                  </summary>
                                  <div className="mt-1 space-y-1 border-l-2 border-amber-200 pl-2">
                                    {h.edit_history.map((edit) => (
                                      <div key={edit.id}>
                                        <div className="font-medium text-slate-600">
                                          ₹{Number(edit.old_amount || 0).toFixed(2)} → ₹{Number(edit.new_amount || 0).toFixed(2)}
                                        </div>
                                        <div>
                                          Cash ₹{Number(edit.old_amount_cash || 0).toFixed(2)} → ₹{Number(edit.new_amount_cash || 0).toFixed(2)} · Online ₹{Number(edit.old_amount_online || 0).toFixed(2)} → ₹{Number(edit.new_amount_online || 0).toFixed(2)}
                                        </div>
                                        {(edit.old_deduction_month !== edit.new_deduction_month) && <div>Month {edit.old_deduction_month || '—'} → {edit.new_deduction_month || '—'}</div>}
                                        <div>{edit.edited_by || 'Unknown user'} · {new Date(edit.edited_at).toLocaleString()}</div>
                                      </div>
                                    ))}
                                  </div>
                                </details>
                              )}
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

      {disableStatutoryOpen && (
        <div className="fixed inset-0 bg-black/45 backdrop-blur-sm flex items-center justify-center z-[80] p-4">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              disablePfAndEsiForAll();
            }}
            className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden"
          >
            <div className="bg-red-600 px-6 py-5 text-white">
              <h2 className="text-xl font-bold">Disable PF &amp; ESI for All?</h2>
              <p className="text-red-100 text-sm mt-1">This applies to every employee in this business and saves immediately.</p>
            </div>
            <div className="p-6 space-y-4">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                Gratuity settings will not be changed. Enter your current web-login password to continue.
              </div>
              <div>
                <label htmlFor="disable-statutory-password" className="block text-sm font-semibold text-slate-700 mb-1.5">Current password</label>
                <input
                  id="disable-statutory-password"
                  type="password"
                  autoFocus
                  autoComplete="current-password"
                  value={disableStatutoryPassword}
                  onChange={(event) => {
                    setDisableStatutoryPassword(event.target.value);
                    setDisableStatutoryError('');
                  }}
                  className="w-full px-3 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-red-500/20 focus:border-red-500"
                  placeholder="Enter your login password"
                />
              </div>
              {disableStatutoryError && (
                <p className="text-sm font-medium text-red-600" role="alert">{disableStatutoryError}</p>
              )}
            </div>
            <div className="px-6 py-4 bg-slate-50 border-t border-slate-200 flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setDisableStatutoryOpen(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-100 disabled:opacity-50 font-semibold"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!disableStatutoryPassword}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 font-semibold"
              >
                Disable for All Employees
              </button>
            </div>
          </form>
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
                          <label className="text-[10px] font-black text-slate-400 uppercase tracking-wider">Owner Login Email</label>
                          <input 
                            type="email"
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
                            type="password"
                            value={owner.password || ''}
                            onChange={(e) => {
                              const newOwners = [...owners];
                              newOwners[idx] = { ...newOwners[idx], password: e.target.value };
                              setOwners(newOwners);
                            }}
                            placeholder="New password"
                            minLength={8}
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
                disabled={ownersSaving}
                className="flex-[2] py-3 bg-slate-800 text-white rounded-xl hover:bg-slate-900 font-bold shadow-lg shadow-slate-200 transition-all text-sm disabled:cursor-wait disabled:opacity-60"
              >
                {ownersSaving ? 'Saving…' : 'Save Owner Access'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Wages;
