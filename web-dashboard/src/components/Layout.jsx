import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar, Topbar } from './EnterpriseLayout';
import XChat from './XChat';

const Layout = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  return (
    <div className="app-shell min-h-screen font-inter w-full">
      <Sidebar isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
      <Topbar onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)} />
      <main className="lg:pl-64 pt-16 min-h-screen min-w-0 transition-all duration-300">
        <div className="app-content p-3 sm:p-5 lg:p-8 xl:p-10 max-w-[1640px] min-w-0 mx-auto">
          <Outlet />
        </div>
      </main>
      <XChat />
    </div>
  );
};

export default Layout;
