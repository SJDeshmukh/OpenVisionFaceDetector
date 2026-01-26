import { 
  Users, 
  UserCheck, 
  UserX, 
  Clock, 
  Video,
  ArrowUp,
  ArrowDown
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

const Dashboard = () => {
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
           setError(error.response.data.error || "Access Denied");
        }
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const KpiCard = ({ title, value, subtext, icon: Icon, color, trend }) => (
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
      
      {/* Background decoration */}
      <Icon size={100} className="absolute -right-4 -bottom-4 text-slate-50 opacity-10 group-hover:scale-110 transition-transform" />
    </div>
  );

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Dashboard Overview</h1>
        <p className="text-slate-500">Welcome back, here's what's happening today.</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <span className="font-medium">{error}</span>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <KpiCard 
          title="Total Employees" 
          value={stats.total} 
          subtext="Registered in system" 
          icon={Users} 
          color="bg-blue-600" 
          trend={12}
        />
        <KpiCard 
          title="Present Today" 
          value={stats.present} 
          subtext={`${((stats.present / (stats.total || 1)) * 100).toFixed(0)}% attendance rate`} 
          icon={UserCheck} 
          color="bg-green-500" 
          trend={5}
        />
        <KpiCard 
          title="Absent Today" 
          value={stats.absent} 
          subtext="Unaccounted for" 
          icon={UserX} 
          color="bg-red-500" 
          trend={-2}
        />
        <KpiCard 
          title="Late Arrivals" 
          value={stats.late} 
          subtext="Exceeded grace period" 
          icon={Clock} 
          color="bg-amber-500" 
          trend={8}
        />
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <h3 className="text-lg font-bold text-slate-800 mb-6">Attendance Trend (Last 7 Days)</h3>
          <div className="h-80 w-full">
            <ResponsiveContainer width="100%" height="100%">
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
          <div className="h-80 w-full">
            <ResponsiveContainer width="100%" height="100%">
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
    </div>
  );
};

export default Dashboard;