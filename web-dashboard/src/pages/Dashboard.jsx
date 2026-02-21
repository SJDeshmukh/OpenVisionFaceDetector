import { 
  Users, 
  UserCheck, 
  UserX, 
  Clock, 
  CreditCard,
  Calendar,
  Shield,
  AlertTriangle,
  LayoutDashboard
} from 'lucide-react';
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  BarChart,
  Bar
} from 'recharts';
import { useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL } from '../config';
import ActivityDashboard from '../components/ActivityDashboard';
import { useAuth } from '../context/AuthContext';
import { useSocket } from '../context/SocketContext';

const Dashboard = () => {
  const { user, logout } = useAuth();
  const { socket, joinVendor } = useSocket();
  const [activeTab, setActiveTab] = useState('overview');
  const [stats, setStats] = useState({
    total: 0,
    present: 0,
    absent: 0,
    late: 0,
    activeCameras: 1
  });
  const [recentActivity, setRecentActivity] = useState([]);
  const [chartData, setChartData] = useState([]);
  const [deptData, setDeptData] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [analyticsRes, attendanceRes] = await Promise.all([
          axios.get(`${API_URL}/reports/analytics`),
          axios.get(`${API_URL}/attendance`)
        ]);
        
        setError(null);
        const { summary, bar_data, dept_data } = analyticsRes.data;
        const attendance = attendanceRes.data.attendance || [];
        
        setStats({
          total: summary.total_users,
          present: summary.present_today,
          absent: summary.absent_today,
          late: summary.late_today,
          activeCameras: 1
        });

        setChartData(bar_data || []);
        setDeptData(dept_data || []);
        setRecentActivity(attendance.slice(0, 5));

      } catch (error) {
        console.error("Error fetching data:", error);
        if (error.response && error.response.status === 403) {
           const msg = error.response.data?.error || "Access Denied";
           setError(msg);
           const suspended = msg.includes("Subscription Expired") || msg.includes("Account Suspended") || msg.includes("Service Suspended");
           if (suspended) {
             setTimeout(() => logout(), 3000);
           } else {
             // Feature missing or other 403: do not logout
             // UI will be gated by updated features from AuthContext interceptor
           }
        }
      }
    };

    fetchData();
    if (!socket) {
      return;
    }
    const handleAttendanceUpdated = (ev) => {
      if (!user?.vendor_id || String(ev.vendor_id) === String(user.vendor_id)) {
        fetchData();
      }
    };
    socket.on('attendance_updated', handleAttendanceUpdated);
    return () => { 
      socket.off('attendance_updated', handleAttendanceUpdated); 
    };
  }, [logout, user, socket]);

  useEffect(() => {
    if (activeTab === 'plan') {
      axios.get(`${API_URL}/vendor/subscription`)
        .then(res => setSubscription(res.data))
        .catch(err => console.error("Error fetching subscription:", err));
    }
  }, [activeTab]);

  const KpiCard = ({ title, value, subtext, icon: Icon, color }) => (
    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between h-32 relative overflow-hidden group hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start z-10">
        <div>
          <p className="text-sm font-medium text-slate-500 mb-1">{title}</p>
          <h3 className="text-3xl font-bold text-slate-800">{value}</h3>
        </div>
        <div className={`p-3 rounded-lg ${color}`}>
          <Icon size={22} className="text-white" />
        </div>
      </div>
      <div className="flex items-center mt-2 z-10">
        <span className="text-xs text-slate-400">{subtext}</span>
      </div>
      <Icon size={100} className="absolute -right-4 -bottom-4 text-slate-50 opacity-10 group-hover:scale-110 transition-transform" />
    </div>
  );

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Dashboard</h1>
          <p className="text-slate-500">Welcome back, here's your overview.</p>
        </div>
        
        {/* Tabs */}
        <div className="flex bg-slate-100 p-1 rounded-lg">
          <button 
            onClick={() => setActiveTab('overview')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'overview' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
          >
            <div className="flex items-center gap-2">
              <LayoutDashboard size={16} />
              Overview
            </div>
          </button>
          <button 
            onClick={() => setActiveTab('plan')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${activeTab === 'plan' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
          >
             <div className="flex items-center gap-2">
              <CreditCard size={16} />
              My Plan
            </div>
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center gap-2">
            <AlertTriangle size={20} />
            <span className="font-medium">{error} - Logging out...</span>
        </div>
      )}

      {activeTab === 'overview' ? (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <KpiCard 
              title="Total Employees" 
              value={stats.total} 
              subtext="Registered in system" 
              icon={Users} 
              color="bg-blue-600" 
            />
            <KpiCard 
              title="Present Today" 
              value={stats.present} 
              subtext={`${((stats.present / (stats.total || 1)) * 100).toFixed(0)}% attendance rate`} 
              icon={UserCheck} 
              color="bg-green-500" 
            />
            <KpiCard 
              title="Absent Today" 
              value={stats.absent} 
              subtext="Unaccounted for" 
              icon={UserX} 
              color="bg-red-500" 
            />
            <KpiCard 
              title="Late Arrivals" 
              value={stats.late} 
              subtext="Exceeded grace period" 
              icon={Clock} 
              color="bg-amber-500" 
            />
          </div>

          {/* Charts Section */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <h3 className="text-lg font-bold text-slate-800 mb-6">Attendance Trend (Last 7 Days)</h3>
              <div className="w-full">
                <ResponsiveContainer width="100%" height={320}>
                  <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorPresent" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2563eb" stopOpacity={0.1}/>
                        <stop offset="95%" stopColor="#2563eb" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: '#64748b'}} />
                    <YAxis axisLine={false} tickLine={false} tick={{fill: '#64748b'}} />
                    <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#fff', borderRadius: '8px', border: '1px solid #e2e8f0', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} 
                      itemStyle={{ color: '#1e293b' }}
                    />
                    <Area type="monotone" dataKey="present" stroke="#2563eb" strokeWidth={3} fillOpacity={1} fill="url(#colorPresent)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <h3 className="text-lg font-bold text-slate-800 mb-6">Late Arrivals by Dept</h3>
              <div className="w-full">
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={deptData} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                    <XAxis type="number" hide />
                    <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{fill: '#64748b'}} width={80} />
                    <Tooltip cursor={{fill: 'transparent'}} />
                    <Bar dataKey="late" fill="#f59e0b" radius={[0, 4, 4, 0]} barSize={20} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Recent Activity Feed */}
          <ActivityDashboard activities={recentActivity} />
        </>
      ) : (
        /* Plan Tab Content */
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
           {subscription ? (
             <>
               <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm space-y-6">
                 <div className="flex justify-between items-start">
                    <div>
                      <h2 className="text-2xl font-bold text-slate-800 mb-1">Current Subscription</h2>
                      <p className="text-slate-500">Manage your billing and plan details</p>
                    </div>
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${subscription.vendor_status === 'active' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {subscription.vendor_status?.toUpperCase()}
                    </span>
                 </div>
                 
                 <div className="p-4 bg-slate-50 rounded-lg border border-slate-100">
                    <div className="flex justify-between items-center mb-2">
                       <span className="text-sm text-slate-500">Current Plan</span>
                       <span className="font-bold text-slate-800 text-lg capitalize">{subscription.plan_type}</span>
                    </div>
                    <div className="flex justify-between items-center">
                       <span className="text-sm text-slate-500">Cost per Device</span>
                       <span className="font-bold text-slate-800">₹{Number(subscription.cost_per_user || 0)}</span>
                    </div>
                    <div className="flex justify-between items-center mt-1">
                       <span className="text-sm text-slate-500">Cost per Employee</span>
                       <span className="font-bold text-slate-800">₹{Number(subscription.cost_per_employee || 0)}</span>
                    </div>
                 </div>

                 <div className="space-y-4">
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-500">Subscription Period</span>
                        <span className="font-medium text-slate-700">{subscription.days_left} Days Left</span>
                      </div>
                      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div 
                          className={`h-full rounded-full ${subscription.days_left <= 0 ? 'bg-red-500' : 'bg-blue-500'}`} 
                          style={{ width: `${Math.min(100, Math.max(0, (subscription.days_left / 30) * 100))}%` }}
                        ></div>
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-4">
                       <div className="p-3 border border-slate-200 rounded-lg">
                          <div className="flex items-center gap-2 text-slate-500 mb-1">
                             <Calendar size={16} />
                             <span className="text-xs">Start Date</span>
                          </div>
                          <p className="font-medium text-slate-800">{subscription.start_date}</p>
                       </div>
                       <div className="p-3 border border-slate-200 rounded-lg">
                          <div className="flex items-center gap-2 text-slate-500 mb-1">
                             <Calendar size={16} />
                             <span className="text-xs">End Date</span>
                          </div>
                          <p className="font-medium text-slate-800">{subscription.end_date}</p>
                       </div>
                    </div>
                 </div>
               </div>

               <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm space-y-6">
                  <h2 className="text-xl font-bold text-slate-800">Payment & Usage</h2>
                  
                  <div className="space-y-4">
                     <div className="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:border-blue-300 transition-colors">
                        <div className="flex items-center gap-4">
                           <div className="p-3 bg-blue-50 text-blue-600 rounded-lg">
                              <CreditCard size={24} />
                           </div>
                           <div>
                              <p className="font-medium text-slate-800">Next Payment</p>
                              <p className="text-sm text-slate-500">Due on {subscription.end_date}</p>
                           </div>
                        </div>
                        <span className="font-bold text-slate-800 text-lg">
                           ₹{(
                             (Number(subscription.cost_per_user || 0) * Number(subscription.max_users || 0)) +
                             (Number(subscription.cost_per_employee || 0) * Number(subscription.max_employees || 0))
                           ).toLocaleString()}
                        </span>
                     </div>

                     <div className="p-4 border border-slate-200 rounded-lg">
                        <p className="font-medium text-slate-800 mb-3">Subscription Items</p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                           <div className="flex items-center justify-between bg-slate-50 border border-slate-100 rounded-lg px-3 py-2">
                              <span className="text-slate-600">Max Phones (Devices)</span>
                              <span className="font-semibold text-slate-800">{subscription.max_users ?? 0}</span>
                           </div>
                           <div className="flex items-center justify-between bg-slate-50 border border-slate-100 rounded-lg px-3 py-2">
                              <span className="text-slate-600">Max Employees</span>
                              <span className="font-semibold text-slate-800">{subscription.max_employees ?? 0}</span>
                           </div>
                           <div className="flex items-center justify-between bg-slate-50 border border-slate-100 rounded-lg px-3 py-2">
                              <span className="text-slate-600">Max Admin Web Sessions</span>
                              <span className="font-semibold text-slate-800">{Math.max(1, Number(subscription.max_web_sessions ?? 1))}</span>
                           </div>
                           <div className="flex items-center justify-between bg-slate-50 border border-slate-100 rounded-lg px-3 py-2">
                              <span className="text-slate-600">Cost Per Device</span>
                              <span className="font-semibold text-slate-800">₹{Number(subscription.cost_per_user || 0)}</span>
                           </div>
                           <div className="flex items-center justify-between bg-slate-50 border border-slate-100 rounded-lg px-3 py-2">
                              <span className="text-slate-600">Cost Per Employee</span>
                              <span className="font-semibold text-slate-800">₹{Number(subscription.cost_per_employee || 0)}</span>
                           </div>
                        </div>
                     </div>

                     <div className="p-4 border border-slate-200 rounded-lg">
                        <p className="font-medium text-slate-800 mb-3">Included Features</p>
                        <div className="flex flex-wrap gap-2">
                          {Array.from(new Set((Array.isArray(subscription.features) ? subscription.features : [])
                            .filter(Boolean)
                            .map(String)
                            .filter(f => f.toLowerCase() !== 'registration_template')
                          )).map((f) => (
                            <span
                              key={f}
                              className="px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-100"
                              title={f}
                            >
                              {f.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                            </span>
                          ))}
                        </div>
                     </div>
                     
                     <div className={`${subscription.days_left <= 0 ? 'bg-amber-50 text-amber-800' : 'bg-blue-50 text-blue-800'} p-4 rounded-lg text-sm flex gap-3 items-start`}>
                        <Shield size={20} className="shrink-0 mt-0.5" />
                        <p>
                           {subscription.days_left <= 0 
                              ? "Your subscription is expiring or has expired. Contact support to renew your plan."
                              : "Your subscription is active. Filters and reports are enabled based on your plan features."}
                        </p>
                     </div>
                  </div>
               </div>
             </>
           ) : (
             <div className="col-span-2 text-center py-12 text-slate-400">
                <p>Loading subscription details...</p>
             </div>
           )}
        </div>
      )}
    </div>
  );
};

export default Dashboard;
