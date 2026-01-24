import { Outlet } from 'react-router-dom';
import { Sidebar, Topbar } from './EnterpriseLayout';

const Layout = () => {
  return (
    <div className="min-h-screen bg-slate-50 font-inter text-slate-900">
      <Sidebar />
      <Topbar />
      <main className="pl-64 pt-16 min-h-screen">
        <div className="p-8 max-w-[1600px] mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;