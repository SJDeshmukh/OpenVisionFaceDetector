import { Shield, Clock } from 'lucide-react';

const AuditLogs = () => {
  const logs = [
    { id: 1, admin: 'System Admin', action: 'Updated system configuration (Threshold: 0.7)', ip: '192.168.1.10', timestamp: '2023-10-27T10:30:00' },
    { id: 2, admin: 'HR Manager', action: 'Added new employee (EMP-1045)', ip: '192.168.1.15', timestamp: '2023-10-27T09:15:00' },
    { id: 3, admin: 'System Admin', action: 'Deleted camera "Back Gate"', ip: '192.168.1.10', timestamp: '2023-10-26T16:45:00' },
    { id: 4, admin: 'Ops Manager', action: 'Exported Monthly Report', ip: '192.168.1.22', timestamp: '2023-10-26T14:20:00' },
    { id: 5, admin: 'System', action: 'Auto-backup completed', ip: 'localhost', timestamp: '2023-10-26T00:00:00' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Audit Logs</h1>
        <p className="text-slate-500">Immutable record of all administrative actions.</p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Timestamp</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Admin User</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Action</th>
              <th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">IP Address</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {logs.map((log) => (
              <tr key={log.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600 font-mono">
                  <div className="flex items-center">
                    <Clock size={14} className="mr-2 text-slate-400" />
                    {new Date(log.timestamp).toLocaleString()}
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-slate-900">
                  <div className="flex items-center">
                    <Shield size={14} className="mr-2 text-blue-500" />
                    {log.admin}
                  </div>
                </td>
                <td className="px-6 py-4 text-sm text-slate-700">
                  {log.action}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500 font-mono">
                  {log.ip}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
};

export default AuditLogs;