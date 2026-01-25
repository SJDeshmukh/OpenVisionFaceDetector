import { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  Calendar, 
  Clock, 
  Plus, 
  Save, 
  UploadCloud, 
  MoreVertical, 
  Trash2, 
  Edit2, 
  Check, 
  X,
  Building2
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { API_URL } from '../config';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const ACTIVITY_TYPES = ['Work', 'Meal', 'Break', 'Custom'];

const Timetable = () => {
  const { user } = useAuth();
  const [companies, setCompanies] = useState([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState(null);
  const [activities, setActivities] = useState([]); // This is the DRAFT state
  const [loading, setLoading] = useState(true);
  const [isDirty, setIsDirty] = useState(false);
  const [showActivityModal, setShowActivityModal] = useState(false);
  const [showCompanyModal, setShowCompanyModal] = useState(false);
  
  // Form States
  const [editingActivity, setEditingActivity] = useState(null);
  const [activityForm, setActivityForm] = useState({
    id: null,
    name: '',
    start_time: '09:00',
    end_time: '17:00',
    type: 'Work',
    days: [...DAYS],
    enabled: true,
    rules: {
      attendance_enabled: true,
      grace_period: 15,
      greeting: 'normal'
    }
  });
  const [newCompanyName, setNewCompanyName] = useState('');

  useEffect(() => {
    fetchCompanies();
  }, []);

  useEffect(() => {
    if (selectedCompanyId) {
      fetchTimetable(selectedCompanyId);
    }
  }, [selectedCompanyId]);

  const fetchCompanies = async () => {
    try {
      const res = await axios.get(`${API_URL}/companies`);
      const validCompanies = (Array.isArray(res.data.companies) ? res.data.companies : [])
        .filter(c => c && typeof c === 'object' && c.id);
      setCompanies(validCompanies);
      
      if (validCompanies.length > 0 && !selectedCompanyId) {
        setSelectedCompanyId(validCompanies[0].id);
      }
      setLoading(false);
    } catch (error) {
      console.error("Error fetching companies:", error);
      setCompanies([]);
      setLoading(false);
    }
  };

  const fetchTimetable = async (companyId) => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/companies/${companyId}`);
      // Parse draft timetable
      let draft = [];
      try {
        draft = JSON.parse(res.data.draft_timetable || '[]');
      } catch (e) {
        console.error("Failed to parse timetable JSON:", e);
      }
      
      // Sanitize activities to prevent render crashes
      const safeDraft = (Array.isArray(draft) ? draft : [])
        .filter(item => item && typeof item === 'object')
        .map(item => ({
          ...item,
          id: item.id || Math.random(), // Ensure ID
          days: Array.isArray(item.days) ? item.days : [], // Ensure days array
          name: item.name || 'Untitled',
          type: item.type || 'Work',
          start_time: item.start_time || '09:00',
          end_time: item.end_time || '17:00',
          enabled: item.enabled !== false,
          rules: item.rules || {}
        }));

      setActivities(safeDraft);
      setIsDirty(false);
    } catch (error) {
      console.error("Error fetching timetable:", error);
      setActivities([]);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateCompany = async () => {
    if (!newCompanyName.trim()) return;
    try {
      const res = await axios.post(`${API_URL}/companies`, { name: newCompanyName });
      setCompanies([...companies, { id: res.data.id, name: res.data.name }]);
      setSelectedCompanyId(res.data.id);
      setShowCompanyModal(false);
      setNewCompanyName('');
    } catch (error) {
      alert(error.response?.data?.error || "Failed to create company");
    }
  };

  const handleSaveDraft = async (dataToSave = null) => {
    try {
      const payload = dataToSave || activities;
      await axios.put(`${API_URL}/companies/${selectedCompanyId}/draft`, {
        draft_timetable: payload,
        modified_by: user.username
      });
      setIsDirty(false);
      // alert("Draft saved successfully!"); // Removed alert for smoother auto-save UX
      console.log("Draft auto-saved");
    } catch (error) {
      console.error("Failed to save draft", error);
      alert("Failed to save draft to backend");
    }
  };

  const handlePublish = async () => {
    if (!confirm("Are you sure you want to publish these changes? This will affect live operations.")) return;
    try {
      // First save draft to ensure consistency
      await axios.put(`${API_URL}/companies/${selectedCompanyId}/draft`, {
        draft_timetable: activities,
        modified_by: user.username
      });
      
      // Then publish
      await axios.post(`${API_URL}/companies/${selectedCompanyId}/publish`, {
        published_by: user.username
      });
      
      setIsDirty(false);
      alert("Timetable published successfully!");
    } catch (error) {
      alert("Failed to publish");
    }
  };

  const handleSaveActivity = () => {
    const newActivity = {
      ...activityForm,
      id: activityForm.id || Date.now() // Simple ID generation
    };

    let updatedActivities;
    if (editingActivity) {
      updatedActivities = activities.map(a => a.id === newActivity.id ? newActivity : a);
    } else {
      updatedActivities = [...activities, newActivity];
    }

    // Sort by start time
    updatedActivities.sort((a, b) => a.start_time.localeCompare(b.start_time));

    setActivities(updatedActivities);
    setIsDirty(true);
    setShowActivityModal(false);
    resetActivityForm();
  };

  const handleDeleteActivity = async (id) => {
    if (!confirm("Delete this activity?")) return;
    const updated = activities.filter(a => a.id !== id);
    setActivities(updated);
    setIsDirty(false);
    // Auto-save
    await handleSaveDraft(updated);
  };

  const openAddModal = () => {
    resetActivityForm();
    setShowActivityModal(true);
  };

  const openEditModal = (activity) => {
    setEditingActivity(activity);
    setActivityForm(activity);
    setShowActivityModal(true);
  };

  const resetActivityForm = () => {
    setEditingActivity(null);
    setActivityForm({
      id: null,
      name: '',
      start_time: '09:00',
      end_time: '17:00',
      type: 'Work',
      days: [...DAYS],
      enabled: true,
      rules: {
        attendance_enabled: true,
        grace_period: 15,
        greeting: 'normal'
      }
    });
  };

  const toggleDay = (day) => {
    if (activityForm.days.includes(day)) {
      setActivityForm({ ...activityForm, days: activityForm.days.filter(d => d !== day) });
    } else {
      setActivityForm({ ...activityForm, days: [...activityForm.days, day] });
    }
  };

  return (
    <div className="pt-8 px-0 pb-8 min-h-screen text-slate-900">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <header className="mb-8 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-purple-600">
              Company Timetable
            </h1>
            <p className="text-slate-600 mt-2">Manage daily schedules and activities</p>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <div className="relative">
              <select 
                value={selectedCompanyId || ''} 
                onChange={(e) => setSelectedCompanyId(Number(e.target.value))}
                className="appearance-none bg-white border border-slate-200 rounded-lg pl-4 pr-10 py-2.5 text-slate-800 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 w-64 shadow-sm"
              >
                {companies.map(c => (
                  <option key={c.id} value={c.id} className="bg-white text-slate-900">{c.name}</option>
                ))}
              </select>
              <Building2 className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" size={18} />
            </div>
            
            <button 
              onClick={() => setShowCompanyModal(true)}
              className="p-2.5 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors text-slate-600 hover:text-slate-800 shadow-sm"
              title="Add Company"
            >
              <Plus size={20} />
            </button>

            <div className="h-8 w-px bg-slate-200 mx-2 hidden md:block"></div>

            <button 
              onClick={handleSaveDraft}
              disabled={!isDirty}
              className={`flex items-center space-x-2 px-4 py-2.5 rounded-lg font-medium transition-all shadow-sm ${
                isDirty 
                  ? 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100' 
                  : 'bg-slate-50 text-slate-500 border border-slate-200 cursor-not-allowed'
              }`}
            >
              <Save size={18} />
              <span>Save Draft</span>
            </button>

            <button 
              onClick={handlePublish}
              className="flex items-center space-x-2 px-4 py-2.5 bg-green-50 text-green-600 border border-green-200 rounded-lg hover:bg-green-100 font-medium transition-all shadow-sm"
            >
              <UploadCloud size={18} />
              <span>Publish Live</span>
            </button>
          </div>
        </header>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Timeline View */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-semibold flex items-center space-x-2 text-slate-800">
                  <Clock className="text-blue-500" size={24} />
                  <span>Daily Schedule</span>
                </h2>
                <button 
                  onClick={openAddModal}
                  className="flex items-center space-x-1 px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 text-sm font-medium transition-colors border border-blue-100"
                >
                  <Plus size={16} />
                  <span>Add Activity</span>
                </button>
              </div>

              {loading ? (
                <div className="text-center py-12 text-slate-600">Loading...</div>
              ) : activities.length === 0 ? (
                <div className="text-center py-12 border-2 border-dashed border-slate-200 rounded-xl">
                  <Calendar className="mx-auto text-slate-500 mb-3" size={48} />
                  <p className="text-slate-600">No activities defined yet.</p>
                  <button onClick={openAddModal} className="mt-4 text-blue-600 hover:text-blue-700 text-sm font-medium">
                    Create your first activity
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  {activities.map((activity) => (
                    <div 
                      key={activity.id} 
                      className={`group relative flex items-center p-4 rounded-xl border transition-all ${
                        activity.enabled 
                          ? 'bg-white border-slate-200 hover:border-blue-300 hover:shadow-md' 
                          : 'bg-slate-50 border-slate-100 opacity-60'
                      }`}
                    >
                      {/* Time Column */}
                      <div className="w-32 flex-shrink-0 border-r border-slate-100 pr-4 mr-4">
                        <div className="text-lg font-mono font-medium text-slate-900">
                          {activity.start_time}
                        </div>
                        <div className="text-sm text-slate-600 font-mono">
                          to {activity.end_time}
                        </div>
                      </div>

                      {/* Content Column */}
                      <div className="flex-grow min-w-0">
                        <div className="flex items-center space-x-3 mb-1">
                          <h3 className="font-semibold text-lg truncate text-slate-900">{activity.name}</h3>
                          <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wide ${
                            activity.type === 'Work' ? 'bg-blue-50 text-blue-700 border border-blue-200' :
                            activity.type === 'Meal' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
                            activity.type === 'Break' ? 'bg-purple-50 text-purple-700 border border-purple-200' :
                            'bg-slate-100 text-slate-600 border border-slate-200'
                          }`}>
                            {activity.type}
                          </span>
                        </div>
                        
                        <div className="flex flex-wrap gap-2 text-xs text-slate-600">
                          <div className="flex space-x-1">
                            {DAYS.map(day => (
                              <span key={day} className={activity.days.includes(day) ? 'text-slate-900 font-bold' : 'text-slate-400'}>
                                {day.charAt(0)}
                              </span>
                            ))}
                          </div>
                          <span className="text-slate-400">•</span>
                          <span>{activity.rules.attendance_enabled ? 'Attendance On' : 'No Attendance'}</span>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center space-x-2 opacity-0 group-hover:opacity-100 transition-opacity ml-4">
                        <button 
                          onClick={() => openEditModal(activity)}
                          className="p-2 hover:bg-slate-100 rounded-lg text-slate-400 hover:text-blue-600 transition-colors"
                        >
                          <Edit2 size={18} />
                        </button>
                        <button 
                          onClick={() => handleDeleteActivity(activity.id)}
                          className="p-2 hover:bg-red-50 rounded-lg text-slate-400 hover:text-red-600 transition-colors"
                        >
                          <Trash2 size={18} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Info / Preview Panel (Could be Analytics or Summary) */}
          <div className="space-y-4">
            <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
              <h3 className="text-lg font-semibold mb-4 text-slate-900">Summary</h3>
              <div className="space-y-4">
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-slate-600">Total Activities</span>
                  <span className="font-mono font-bold text-slate-900">{activities.length}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-slate-600">Work Blocks</span>
                  <span className="font-mono font-bold text-blue-600">
                    {activities.filter(a => a.type === 'Work').length}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-slate-600">Breaks/Meals</span>
                  <span className="font-mono font-bold text-amber-500">
                    {activities.filter(a => ['Meal', 'Break'].includes(a.type)).length}
                  </span>
                </div>
              </div>
            </div>
            
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-6">
              <h4 className="text-blue-700 font-semibold mb-2">Draft Mode</h4>
              <p className="text-sm text-blue-700 leading-relaxed">
                Changes are saved locally as a draft. Click "Publish Live" to apply these changes to the actual attendance system.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Activity Modal */}
      {showActivityModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
          <div className="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50">
              <h3 className="font-bold text-lg text-slate-800">
                {editingActivity ? 'Edit Activity' : 'New Activity'}
              </h3>
              <button onClick={() => setShowActivityModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={20} />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto space-y-6 custom-scrollbar">
              {/* Basic Info */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-slate-800 mb-1.5">Activity Name</label>
                  <input 
                    type="text" 
                    value={activityForm.name}
                    onChange={(e) => setActivityForm({...activityForm, name: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                    placeholder="e.g., Morning Shift"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-800 mb-1.5">Start Time</label>
                  <input 
                    type="time" 
                    value={activityForm.start_time}
                    onChange={(e) => setActivityForm({...activityForm, start_time: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-800 mb-1.5">End Time</label>
                  <input 
                    type="time" 
                    value={activityForm.end_time}
                    onChange={(e) => setActivityForm({...activityForm, end_time: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-800 mb-1.5">Type</label>
                  <select 
                    value={activityForm.type}
                    onChange={(e) => setActivityForm({...activityForm, type: e.target.value})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  >
                    {ACTIVITY_TYPES.map(t => (
                      <option key={t} value={t} className="bg-white">{t}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-800 mb-1.5">Greeting</label>
                  <select 
                    value={activityForm.rules.greeting}
                    onChange={(e) => setActivityForm({...activityForm, rules: {...activityForm.rules, greeting: e.target.value}})}
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  >
                    <option value="normal" className="bg-white">Normal</option>
                    <option value="silent" className="bg-white">Silent</option>
                    <option value="custom" className="bg-white">Custom</option>
                  </select>
                </div>
              </div>

              {/* Days Selector */}
              <div>
                <label className="block text-sm font-medium text-slate-800 mb-3">Applicable Days</label>
                <div className="flex flex-wrap gap-2">
                  {DAYS.map(day => (
                    <button
                      key={day}
                      onClick={() => toggleDay(day)}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                        activityForm.days.includes(day)
                          ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/25'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      {day}
                    </button>
                  ))}
                </div>
              </div>

              {/* Rules Section */}
              <div className="bg-slate-50 rounded-xl p-4 space-y-4 border border-slate-200">
                <h4 className="text-sm font-bold text-slate-500 uppercase tracking-wider">Rules Configuration</h4>
                
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-800">Enable Attendance</p>
                    <p className="text-xs text-slate-600">Track entries/exits during this block</p>
                  </div>
                  <div className="relative inline-block w-12 mr-2 align-middle select-none transition duration-200 ease-in">
                    <input 
                      type="checkbox" 
                      checked={activityForm.rules.attendance_enabled}
                      onChange={(e) => setActivityForm({...activityForm, rules: {...activityForm.rules, attendance_enabled: e.target.checked}})}
                      className="toggle-checkbox absolute block w-6 h-6 rounded-full bg-white border-4 border-slate-300 appearance-none cursor-pointer checked:right-0 checked:border-blue-500"
                    />
                    <div className={`block overflow-hidden h-6 rounded-full cursor-pointer ${activityForm.rules.attendance_enabled ? 'bg-blue-500' : 'bg-slate-400'}`}></div>
                  </div>
                </div>

                <div className="pt-4 border-t border-slate-200">
                  <div className="flex justify-between items-center mb-2">
                    <label className="text-sm font-medium text-slate-600">Grace Period (Minutes)</label>
                    <span className="text-sm font-mono text-blue-600 font-bold">{activityForm.rules.grace_period} min</span>
                  </div>
                  <input 
                    type="range" 
                    min="0" 
                    max="60" 
                    step="5" 
                    value={activityForm.rules.grace_period}
                    onChange={(e) => setActivityForm({...activityForm, rules: {...activityForm.rules, grace_period: parseInt(e.target.value)}})}
                    className="w-full h-2 bg-slate-300 rounded-lg appearance-none cursor-pointer accent-blue-600"
                  />
                </div>
              </div>
            </div>

            <div className="px-6 py-4 bg-slate-50 border-t border-slate-200 flex justify-end space-x-3">
              <button 
                onClick={() => setShowActivityModal(false)}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-200 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button 
                onClick={handleSaveActivity}
                disabled={!activityForm.name}
                className="px-6 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-lg shadow-blue-600/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {editingActivity ? 'Update Activity' : 'Add Activity'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Company Modal */}
      {showCompanyModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[60]">
          <div className="bg-white border border-slate-200 rounded-xl shadow-xl w-full max-w-sm p-6">
            <h3 className="text-lg font-bold text-slate-900 mb-4">Add New Company</h3>
            <input 
              type="text" 
              value={newCompanyName}
              onChange={(e) => setNewCompanyName(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5 text-slate-900 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 mb-6"
              placeholder="Company Name"
              autoFocus
            />
            <div className="flex justify-end space-x-3">
              <button 
                onClick={() => setShowCompanyModal(false)}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800"
              >
                Cancel
              </button>
              <button 
                onClick={handleCreateCompany}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Timetable;
