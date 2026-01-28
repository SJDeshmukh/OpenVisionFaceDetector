import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { FRONTEND_BUNDLES } from '../config';
import logo from '../assets/logo_openvision.png';
import { 
  LayoutDashboard, 
  Users, 
  ClipboardList, 
  Video, 
  FileText, 
  Settings, 
  Shield, 
  Bell, 
  Search,
  LogOut,
  CalendarClock,
  DollarSign,
  Activity,
  Menu,
  X
} from 'lucide-react';

const adminNavItems = [
  { name: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
  { name: 'People', path: '/people', icon: Users },
  { name: 'Timetable', path: '/timetable', icon: CalendarClock },
  { name: 'Wages', path: '/wages', icon: DollarSign },
  { name: 'Attendance', path: '/attendance', icon: ClipboardList },
  { name: 'Live Attendance', path: '/live-attendance', icon: Activity },
  { name: 'Cameras', path: '/cameras', icon: Video },
  { name: 'Reports', path: '/reports', icon: FileText },
  { name: 'Settings', path: '/settings', icon: Settings },
  { name: 'Audit Logs', path: '/audit-logs', icon: Shield },
];

const userNavItems = [
  { name: 'Attendance', path: '/attendance', icon: ClipboardList },
];

export const Sidebar = ({ isOpen, onClose }) => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  let navItems = (user?.role === 'admin' || user?.role === 'vendor_admin') ? adminNavItems : userNavItems;

  // Dynamic Frontend Loading Logic
  const bundleId = user?.frontend_bundle_id || 'default_attendance';
  const allowedItems = FRONTEND_BUNDLES[bundleId] || FRONTEND_BUNDLES['default_attendance'];

  if (allowedItems !== 'ALL') {
      navItems = navItems.filter(item => allowedItems.includes(item.name));
  }

  return (
    <>
      {/* Mobile Overlay */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-30 lg:hidden"
          onClick={onClose}
        />
      )}
      
      <aside className={`fixed left-0 top-0 h-full w-64 bg-slate-900 text-white z-40 flex flex-col shadow-xl transition-transform duration-300 ease-in-out ${
        isOpen ? 'translate-x-0' : '-translate-x-full'
      } lg:translate-x-0`}>
        <div className="h-16 flex items-center justify-between px-6 border-b border-slate-800">
          <div className="flex items-center">
            <div className="w-8 h-8 flex items-center justify-center mr-3">
              <img src={logo} alt="VisionX" className="w-full h-full object-contain" />
            </div>
            <span className="text-lg font-bold tracking-tight">VisionX</span>
          </div>
          <button onClick={onClose} className="lg:hidden text-slate-400 hover:text-white">
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto py-6 px-3 space-y-1 custom-scrollbar">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={() => onClose?.()} // Close sidebar on mobile when link clicked
              className={({ isActive }) =>
                `flex items-center px-3 py-2.5 rounded-lg transition-all duration-200 group ${
                  isActive 
                    ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20' 
                    : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                }`
              }
            >
              <item.icon size={20} className="mr-3" />
              <span className="text-sm font-medium">{item.name}</span>
            </NavLink>
          ))}
        </div>

        <div className="p-4 border-t border-slate-800">
          <button 
            onClick={handleLogout}
            className="flex items-center w-full px-3 py-2.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-red-400 transition-colors"
          >
            <LogOut size={20} className="mr-3" />
            <span className="text-sm font-medium">Sign Out</span>
          </button>
        </div>
      </aside>
    </>
  );
};

export const Topbar = ({ onToggleSidebar }) => {
  const { user } = useAuth();

  return (
    <header className="fixed top-0 left-0 lg:left-64 right-0 h-16 bg-white border-b border-slate-200 z-30 flex items-center justify-between px-4 lg:px-8 shadow-sm transition-all duration-300">
      <div className="flex items-center w-full max-w-xl">
        <button 
          onClick={onToggleSidebar}
          className="mr-4 p-2 text-slate-500 hover:bg-slate-100 rounded-lg lg:hidden"
        >
          <Menu size={24} />
        </button>

        <div className="relative w-full max-w-md hidden sm:block">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <input 
            type="text" 
            placeholder="Search..." 
            className="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
          />
        </div>
      </div>

      <div className="flex items-center space-x-6">
        <button className="relative p-2 text-slate-500 hover:bg-slate-50 rounded-lg transition-colors">
          <Bell size={20} />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full border-2 border-white"></span>
        </button>
        
        <div className="flex items-center space-x-3 pl-6 border-l border-slate-200">
          <div className="text-right hidden sm:block">
            <p className="text-sm font-bold text-slate-800 capitalize">{user?.username || 'Guest'}</p>
            <p className="text-xs text-slate-500 capitalize">{user?.role === 'admin' ? 'Administrator' : 'Kiosk User'}</p>
          </div>
          <div className="w-10 h-10 rounded-full bg-slate-200 flex items-center justify-center text-slate-600 font-bold border-2 border-white shadow-sm">
            {user?.username?.charAt(0).toUpperCase() || 'U'}
          </div>
        </div>
      </div>
    </header>
  );
};