import { NavLink, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { FRONTEND_BUNDLES, FEATURE_TO_SIDEBAR_MAP, ALWAYS_VISIBLE_ITEMS } from '../config';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, Users, ClipboardList, Video, FileText, Settings,
  Shield, Bell, Search, LogOut, CalendarClock, DollarSign, Activity,
  Menu, X, FileCheck, Zap, ChevronRight, Moon, Sun
} from 'lucide-react';
import { Image as ImageIcon } from 'lucide-react';

const adminNavItems = [
  { name: 'Dashboard',            path: '/dashboard',            icon: LayoutDashboard },
  { name: 'People',               path: '/people',               icon: Users },
  { name: 'Faces',                path: '/faces',                icon: ImageIcon },
  { name: 'Classes',              path: '/classes',              icon: Users },
  { name: 'Timetable',            path: '/timetable',            icon: CalendarClock },
  { name: 'Wages',                path: '/wages',                icon: DollarSign },
  { name: 'Attendance',           path: '/attendance',           icon: ClipboardList },
  { name: 'Bulk Image Attendance',path: '/bulk-image-attendance',icon: ClipboardList },
  { name: 'Live Attendance',      path: '/live-attendance',      icon: Activity },
  { name: 'Cameras',              path: '/cameras',              icon: Video },
  { name: 'Reports',              path: '/reports',              icon: FileText },
  { name: 'Settings',             path: '/settings',             icon: Settings },
  { name: 'Audit Logs',           path: '/audit-logs',           icon: Shield },
  { name: 'Leave Management',     path: '/leave-management',     icon: FileCheck },
  { name: 'Face Reset Requests',  path: '/face-reset-requests',  icon: Shield },
];

const superAdminNavItems = [
  { name: 'Vendors',       path: '/admin/vendors',       icon: Users },
  { name: 'Live Feed',     path: '/admin/live-feed',     icon: Video },
  { name: 'Audit Logs',    path: '/admin/audit-logs',    icon: Shield },
  { name: 'System Health', path: '/admin/system-health', icon: Activity },
  { name: 'Background Jobs',path: '/admin/jobs',         icon: Activity },
];

const userNavItems = [
  { name: 'Attendance',      path: '/attendance',      icon: ClipboardList },
  { name: 'Leave Management',path: '/leave-management',icon: FileCheck },
];

const facultyNavItems = [
  { name: 'Classes',          path: '/classes',              icon: Users },
  { name: 'People',           path: '/people',               icon: Users },
  { name: 'Bulk Attendance',  path: '/bulk-image-attendance',icon: ClipboardList },
  { name: 'Attendance',       path: '/attendance',           icon: ClipboardList },
  { name: 'Reports',          path: '/reports',              icon: FileText },
];

/* ── Variants ── */
const navItemVariants = {
  hidden:  { opacity: 0, x: -14 },
  visible: (i) => ({
    opacity: 1, x: 0,
    transition: { delay: i * 0.045, duration: 0.32, ease: [0.22, 1, 0.36, 1] }
  }),
};

const overlayVariants = {
  hidden:  { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.2 } },
  exit:    { opacity: 0, transition: { duration: 0.18 } },
};

/* ── Sidebar ── */
export const Sidebar = ({ isOpen, onClose }) => {
  const { user, staffSession, logout } = useAuth();
  const navigate = useNavigate();
  const [liveFeedUnlocked, setLiveFeedUnlocked] = useState(false);
  const [seqIndex, setSeqIndex] = useState(0);
  const secret = ['j', 'o', 'n', 'a', 's'];

  useEffect(() => {
    const handler = (e) => {
      if (!user || user.role !== 'super_admin') return;
      const k = String(e.key || '').toLowerCase();
      if (k === secret[seqIndex]) {
        const ni = seqIndex + 1;
        if (ni >= secret.length) { setLiveFeedUnlocked(true); setSeqIndex(0); }
        else setSeqIndex(ni);
      } else {
        setSeqIndex(k === secret[0] ? 1 : 0);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [user, seqIndex]);

  const handleLogout = () => { logout(); navigate('/login'); };

  let navItems;
  if (user?.role === 'super_admin') {
    navItems = superAdminNavItems.filter(item => item.path !== '/admin/live-feed' || liveFeedUnlocked);
  } else if (user?.role === 'faculty') {
    navItems = facultyNavItems;
  } else if (user?.role === 'admin' || user?.role === 'vendor_admin') {
    if (staffSession) {
      navItems = staffSession.role === 'hod'
        ? adminNavItems.filter(i => i.name === 'Leave Management' || i.name === 'Dashboard')
        : adminNavItems;
    } else {
      navItems = adminNavItems;
    }
  } else {
    navItems = userNavItems;
  }

  if (user?.role !== 'super_admin' && user?.role !== 'faculty') {
    const bundleId = user?.frontend_bundle_id || 'default_attendance';
    if (user?.features && Array.isArray(user.features)) {
      const allowedNames = new Set(ALWAYS_VISIBLE_ITEMS);
      user.features.forEach(fk => { const sn = FEATURE_TO_SIDEBAR_MAP[fk]; if (sn) allowedNames.add(sn); });
      if (bundleId === 'class_attendance_ui' || user.features.includes('classes')) allowedNames.add('Faces');
      navItems = navItems.filter(item => allowedNames.has(item.name));
    } else {
      const allowed = FRONTEND_BUNDLES[bundleId] || FRONTEND_BUNDLES['default_attendance'];
      if (allowed !== 'ALL') navItems = navItems.filter(item => allowed.includes(item.name));
    }
  }

  return (
    <>
      {/* Mobile dark overlay */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            key="overlay"
            variants={overlayVariants}
            initial="hidden" animate="visible" exit="exit"
            className="fixed inset-0 z-30 lg:hidden"
            style={{ background: 'var(--overlay-bg)', backdropFilter: 'blur(5px)' }}
            onClick={onClose}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside
        className={`fixed left-0 top-0 h-full w-64 z-40 flex flex-col transition-transform duration-300 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        } lg:translate-x-0`}
        style={{
          background: 'var(--bg-sidebar)',
          borderRight: '1px solid var(--border-sidebar)',
          boxShadow: 'var(--shadow-sidebar)',
        }}
      >
        {/* Logo */}
        <div
          className="h-16 flex items-center justify-between px-5 flex-shrink-0"
          style={{ borderBottom: '1px solid rgba(124,58,255,0.1)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center overflow-hidden flex-shrink-0"
              style={{
                background: 'linear-gradient(135deg, #7C3AFF 0%, #06D6FF 100%)',
                boxShadow: '0 0 18px rgba(124,58,255,0.65), 0 0 36px rgba(124,58,255,0.2)',
              }}
            >
              <img src="/tapinx-logo.svg" alt="TapInX" className="w-7 h-7 object-contain" style={{ filter: 'brightness(10)' }} />
            </div>
            <div>
              <p className="text-[15px] font-bold text-white leading-tight tracking-tight">TapInX</p>
              <p className="text-[9px] font-semibold tracking-[0.2em] uppercase" style={{ color: 'rgba(124,58,255,0.7)' }}>
                AttendX
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="lg:hidden p-1.5 rounded-lg transition-colors"
            style={{ color: '#8080B0' }}
            onMouseEnter={e => e.currentTarget.style.color = '#fff'}
            onMouseLeave={e => e.currentTarget.style.color = '#8080B0'}
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-0.5 custom-scrollbar">
          {navItems.map((item, i) => (
            <motion.div key={item.path} custom={i} variants={navItemVariants} initial="hidden" animate="visible">
              <NavLink
                to={item.path}
                onClick={() => onClose?.()}
                className="block"
              >
                {({ isActive }) => (
                  <div
                    className="relative flex items-center gap-3 px-3 py-2.5 rounded-xl overflow-hidden transition-all duration-200 group cursor-pointer"
                    style={{
                      background: isActive
                        ? 'linear-gradient(90deg, rgba(124,58,255,0.22) 0%, rgba(124,58,255,0.06) 100%)'
                        : 'transparent',
                      color: isActive ? '#fff' : '#8080B0',
                    }}
                    onMouseEnter={e => { if (!isActive) { e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; e.currentTarget.style.color = '#C4C4E0'; } }}
                    onMouseLeave={e => { if (!isActive) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#8080B0'; } }}
                  >
                    {/* Active left accent */}
                    {isActive && <span className="nav-glow-line" />}

                    <item.icon
                      size={17}
                      className="relative z-10 flex-shrink-0 transition-all duration-200"
                      style={{
                        color: isActive ? '#9B6AFF' : 'inherit',
                        filter: isActive ? 'drop-shadow(0 0 6px rgba(124,58,255,0.9))' : 'none',
                      }}
                    />
                    <span className="relative z-10 text-[13px] font-medium leading-none truncate flex-1">
                      {item.name}
                    </span>
                    {isActive && (
                      <ChevronRight size={13} className="relative z-10 flex-shrink-0" style={{ color: 'rgba(124,58,255,0.6)' }} />
                    )}
                  </div>
                )}
              </NavLink>
            </motion.div>
          ))}
        </nav>

        {/* User + Logout */}
        <div className="flex-shrink-0 p-3" style={{ borderTop: '1px solid rgba(124,58,255,0.1)' }}>
          {user && (
            <div
              className="flex items-center gap-3 px-3 py-2.5 rounded-xl mb-1"
              style={{ background: 'rgba(124,58,255,0.06)' }}
            >
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #7C3AFF, #06D6FF)', color: '#fff' }}
              >
                {(staffSession?.name || user?.username || 'U').charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-semibold text-white truncate leading-tight">
                  {staffSession ? staffSession.name : (user?.username || 'Guest')}
                </p>
                <p className="text-[10px] truncate capitalize" style={{ color: '#5050A0' }}>
                  {staffSession
                    ? `${staffSession.role.toUpperCase()}${staffSession.department ? ` · ${staffSession.department}` : ''}`
                    : (user?.role === 'admin' ? 'Administrator' : 'TapInX User')}
                </p>
              </div>
            </div>
          )}
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-xl transition-all duration-200 group"
            style={{ color: '#8080B0' }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,59,59,0.08)'; e.currentTarget.style.color = '#FF6B6B'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#8080B0'; }}
          >
            <LogOut size={16} className="flex-shrink-0" />
            <span className="text-[13px] font-medium">Sign Out</span>
          </button>
        </div>
      </aside>
    </>
  );
};

/* ── Topbar ── */
export const Topbar = ({ onToggleSidebar }) => {
  const { user, staffSession } = useAuth();
  const [searchFocused, setSearchFocused] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'dark');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  };

  return (
    <header
      className="fixed top-0 left-0 lg:left-64 right-0 h-16 z-30 flex items-center justify-between px-4 lg:px-8 transition-all duration-300"
      style={{
        background: 'var(--bg-topbar)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderBottom: '1px solid var(--border-top)',
        boxShadow: 'var(--shadow-topbar)',
      }}
    >
      <div className="flex items-center gap-4 flex-1 max-w-xl">
        <button
          onClick={onToggleSidebar}
          className="lg:hidden p-2 rounded-xl transition-all duration-200"
          style={{ color: '#8080B0', background: 'rgba(124,58,255,0.06)' }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(124,58,255,0.14)'; e.currentTarget.style.color = '#fff'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(124,58,255,0.06)'; e.currentTarget.style.color = '#8080B0'; }}
        >
          <Menu size={20} />
        </button>

        <div className="relative flex-1 hidden sm:block">
          <Search
            className="absolute left-3.5 top-1/2 -translate-y-1/2 transition-colors duration-200"
            size={16}
            style={{ color: searchFocused ? '#9B6AFF' : '#5050A0' }}
          />
          <input
            type="text"
            placeholder="Search people, reports..."
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            className="input-glow w-full pl-10 pr-4 py-2.5 rounded-xl text-sm transition-all duration-200"
            style={{
              background: 'rgba(255,255,255,0.04)',
              border: `1px solid ${searchFocused ? 'rgba(124,58,255,0.45)' : 'rgba(124,58,255,0.12)'}`,
              color: '#C4C4E0',
              outline: 'none',
            }}
          />
          {searchFocused && (
            <div
              className="absolute inset-0 rounded-xl pointer-events-none"
              style={{ boxShadow: '0 0 0 3px rgba(124,58,255,0.1), 0 0 20px rgba(124,58,255,0.06)' }}
            />
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Notification bell */}
        <button
          className="relative p-2.5 rounded-xl transition-all duration-200"
          style={{ color: '#8080B0', background: 'rgba(124,58,255,0.06)' }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(124,58,255,0.14)'; e.currentTarget.style.color = '#9B6AFF'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(124,58,255,0.06)'; e.currentTarget.style.color = '#8080B0'; }}
        >
          <Bell size={18} />
          <span
            className="absolute top-2 right-2 w-2 h-2 rounded-full animate-pulse"
            style={{ background: '#FF2D87', boxShadow: '0 0 6px rgba(255,45,135,0.8)' }}
          />
        </button>

        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          className="relative p-2.5 rounded-xl transition-all duration-200"
          style={{ color: '#8080B0', background: 'rgba(124,58,255,0.06)' }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(124,58,255,0.14)'; e.currentTarget.style.color = '#9B6AFF'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(124,58,255,0.06)'; e.currentTarget.style.color = '#8080B0'; }}
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        {/* Divider */}
        <div className="w-px h-6 hidden sm:block" style={{ background: 'rgba(124,58,255,0.12)' }} />

        {/* User chip */}
        <div
          className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl hidden sm:flex"
          style={{ background: 'rgba(124,58,255,0.06)', border: '1px solid rgba(124,58,255,0.12)' }}
        >
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #7C3AFF, #06D6FF)', color: '#fff' }}
          >
            {(staffSession?.name || user?.username || 'U').charAt(0).toUpperCase()}
          </div>
          <div className="hidden md:block">
            <p className="text-[12px] font-semibold text-white leading-tight">
              {staffSession ? staffSession.name : (user?.username || 'Guest')}
            </p>
            <p className="text-[10px] capitalize" style={{ color: '#5050A0' }}>
              {staffSession ? staffSession.role : (user?.role === 'admin' ? 'Admin' : 'User')}
            </p>
          </div>
        </div>

        {/* Online indicator */}
        <div className="flex items-center gap-1.5 hidden sm:flex">
          <span
            className="w-2 h-2 rounded-full animate-pulse"
            style={{ background: '#00E87A', boxShadow: '0 0 8px rgba(0,232,122,0.8)' }}
          />
          <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: '#00E87A' }}>Live</span>
        </div>
      </div>
    </header>
  );
};
