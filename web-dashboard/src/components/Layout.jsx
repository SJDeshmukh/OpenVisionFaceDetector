import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar, Topbar } from './EnterpriseLayout';

const Layout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-slate-50 font-inter text-slate-900">
      <Sidebar isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
      <Topbar onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)} />
      <main className="lg:pl-64 pt-16 min-h-screen transition-all duration-300">
        <div className="p-4 lg:p-8 max-w-[1600px] mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
