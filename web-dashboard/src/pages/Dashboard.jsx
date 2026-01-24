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

const API_URL = 'http://127.0.0.1:5001/api';

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

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [analyticsRes, attendanceRes] = await Promise.all([
          axios.get(`${API_URL}/reports/analytics`),
          axios.get(`${API_URL}/attendance`)
        ]);
        
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
        {trend && (
          <span className={`text-xs font-semibold flex items-center ${trend > 0 ? 'text-green-600' : 'text-red-600'} mr-2`}>
            {trend > 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
            {Math.abs(trend)}%
          </span>
        )}
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
          subtext="Checked in after 9:30 AM" 
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
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-6 border-b border-slate-200 flex justify-between items-center">
          <h3 className="text-lg font-bold text-slate-800">Live Recognition Feed</h3>
          <span className="flex items-center text-xs text-green-600 font-medium bg-green-50 px-3 py-1 rounded-full border border-green-100">
            <span className="w-2 h-2 bg-green-500 rounded-full mr-2 animate-pulse"></span>
            Live
          </span>
        </div>
        <div className="divide-y divide-slate-100">
          {recentActivity.map((activity, idx) => (
            <div key={idx} className="p-4 hover:bg-slate-50 transition-colors flex items-center justify-between">
              <div className="flex items-center space-x-4">
                <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-500 font-bold">
                  {activity.name.charAt(0)}
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800">{activity.name}</p>
                  <p className="text-xs text-slate-500">Camera 01 • Main Entrance</p>
                </div>
              </div>
              <div className="text-right">
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  activity.status === 'CHECK_IN' 
                    ? 'bg-green-100 text-green-800' 
                    : 'bg-purple-100 text-purple-800'
                }`}>
                  {activity.status === 'CHECK_IN' ? 'Check In' : 'Check Out'}
                </span>
                <p className="text-xs text-slate-400 mt-1">
                  {new Date(activity.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                </p>
              </div>
            </div>
          ))}
          {recentActivity.length === 0 && (
            <div className="p-8 text-center text-slate-400">No activity recorded yet.</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;