import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../config';

const Wages = () => {
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

  useEffect(() => {
    fetchWorkingHours();
  }, []);

  const fetchWorkingHours = async () => {
      try {
          const res = await fetch(`${API_BASE_URL}/companies/1`);
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
          const res = await fetch(`${API_BASE_URL}/companies/1`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ working_hours: parseFloat(workingHours) })
          });
          if (res.status === 403) {
             const data = await res.json();
             setError(data.error || "Access Denied");
             return;
          }
          if (res.ok) {
              setWorkingHoursChanged(false);
              fetchPayroll(); // Refresh calculation
          }
      } catch (e) {
          console.error("Error saving working hours", e);
      }
  };


  const fetchPayroll = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/reports/payroll?start_date=${startDate}&end_date=${endDate}`);
      if (res.status === 403) {
          const data = await res.json();
          setError(data.error || "Access Denied");
          return;
      }
      const data = await res.json();
      if (data.payroll) {
        setPayrollData(data.payroll);
      }
    } catch (error) {
      console.error("Error fetching payroll:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (startDate && endDate) {
      fetchPayroll();
    }
  }, [startDate, endDate]);

  const handleWageChange = (index, value) => {
    const newData = [...payrollData];
    newData[index].daily_wage = parseFloat(value) || 0;
    
    // Recalculate cost immediately
    // Assumption: Daily Wage is for 'workingHours'. Hourly Rate = Daily / workingHours.
    const hourlyRate = newData[index].daily_wage / workingHours; 
    newData[index].total_cost = (newData[index].total_hours * hourlyRate).toFixed(2);
    
    setPayrollData(newData);
    setHasChanges(true);
  };

  const saveWages = async () => {
    setSaveLoading(true);
    try {
      const updates = payrollData.map(p => ({
        name: p.name,
        daily_wage: p.daily_wage
      }));

      const res = await fetch(`${API_BASE_URL}/persons/wages`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
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

        {/* Working Hours Setting */}
        <div className="bg-slate-50 border-b border-slate-200 p-4 rounded-t-lg flex flex-col sm:flex-row sm:items-center gap-4 mb-4">
            <div className="flex items-center gap-2">
                <label className="text-sm font-semibold text-slate-700 whitespace-nowrap">Standard Daily Working Hours:</label>
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
                    className="w-20 px-2 py-1 border border-slate-300 rounded text-sm focus:ring-2 focus:ring-blue-500"
                />
                <span className="text-xs text-slate-500 whitespace-nowrap">hours/day</span>
            </div>
            {workingHoursChanged && (
                <button 
                    onClick={saveWorkingHours}
                    className="text-xs bg-blue-600 text-white px-3 py-2 sm:py-1 rounded hover:bg-blue-700 transition-colors w-full sm:w-auto"
                >
                    Update Calculation
                </button>
            )}
        </div>

        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Employee</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Role</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Contact</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Days Present</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">Total Hours</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">Daily Wage</th>
                <th className="py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">Estimated Cost</th>
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
                              {person.name.substring(0,2).toUpperCase()}
                            </div>
                          )}
                        </div>
                        <div>
                          <p className="font-medium text-slate-900 text-sm">{person.name}</p>
                          <p className="text-xs text-slate-500">{person.department || 'No Dept'}</p>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-sm text-slate-600">{person.designation || '-'}</td>
                    <td className="py-3 px-4 text-sm text-slate-600">{person.phone || '-'}</td>
                    <td className="py-3 px-4 text-sm text-slate-600 text-center font-medium">{person.days_present}</td>
                    <td className="py-3 px-4 text-sm text-slate-600 text-center">
                        <span className="bg-blue-50 text-blue-700 px-2 py-1 rounded text-xs font-semibold">
                            {person.total_hours} hrs
                        </span>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <div className="flex items-center justify-end gap-2 relative group">
                        <span className="text-slate-400 text-sm">RS</span>
                        <input 
                          type="number" 
                          min="0"
                          step="0.01"
                          value={person.daily_wage}
                          onChange={(e) => handleWageChange(index, e.target.value)}
                          className="w-24 px-2 py-1 border border-slate-200 rounded text-right text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-medium text-slate-700 bg-slate-50 focus:bg-white transition-all"
                          placeholder="0.00"
                        />
                      </div>
                    </td>
                    <td className="py-3 px-4 text-right">
                        <div className="text-sm font-bold text-slate-900 block">
                            RS {parseFloat(person.total_cost || 0).toFixed(2)}
                        </div>
                        {parseFloat(person.total_hours || 0) > 0 && parseFloat(person.daily_wage || 0) > 0 && (
                            <span className="text-[10px] text-slate-400 block mt-1">
                                {person.total_hours}h × RS {(parseFloat(person.daily_wage)/workingHours).toFixed(2)}/hr
                            </span>
                        )}
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
                            ₹{payrollData.reduce((acc, curr) => acc + parseFloat(curr.total_cost || 0), 0).toFixed(2)}
                        </td>
                    </tr>
                </tfoot>
            )}
          </table>
        </div>
      </div>
    </div>
  );
};

export default Wages;
