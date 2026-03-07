import { NavLink } from 'react-router-dom';
import { Home, LayoutDashboard, Users, Settings, CalendarClock, Image as ImageIcon } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const Navbar = () => {
  const { user } = useAuth();
  
  const navItems = [
    { name: 'Home', path: '/', icon: Home },
    { name: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
    { name: 'Users', path: '/users', icon: Users },
    { name: 'Faces', path: '/faces', icon: ImageIcon },
  ];

  if (user?.role === 'admin') {
    navItems.push({ name: 'Timetable', path: '/timetable', icon: CalendarClock });
  }

  // Always show Settings
  navItems.push({ name: 'Settings', path: '/settings', icon: Settings });

  return (
    <nav className="fixed top-6 left-1/2 transform -translate-x-1/2 z-50">
      <div className="bg-white/10 backdrop-blur-md border border-white/20 rounded-full px-6 py-3 shadow-lg flex items-center space-x-8">
        {navItems.map((item) => (
          <NavLink
            key={item.name}
            to={item.path}
            className={({ isActive }) =>
              `flex items-center space-x-2 text-sm font-medium transition-all duration-300 ${
                isActive
                  ? 'text-blue-400 scale-105'
                  : 'text-gray-400 hover:text-white hover:scale-105'
              }`
            }
          >
            <item.icon size={18} />
            <span>{item.name}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
};

export default Navbar;
