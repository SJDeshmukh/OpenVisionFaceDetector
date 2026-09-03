import React from 'react';

const imageSource = (value) => {
  if (!value) return '';
  if (value.startsWith('data:') || value.startsWith('http://') || value.startsWith('https://')) return value;
  return `data:image/jpeg;base64,${value}`;
};

const ActivityDashboard = ({ activities = [] }) => {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="p-6 border-b border-slate-200 flex justify-between items-center">
        <h3 className="text-lg font-bold text-slate-800">Live Recognition Feed</h3>
        <span className="flex items-center text-xs text-green-600 font-medium bg-green-50 px-3 py-1 rounded-full border border-green-100">
          <span className="w-2 h-2 bg-green-500 rounded-full mr-2 animate-pulse"></span>
          Live
        </span>
      </div>
      <div className="divide-y divide-slate-100">
        {activities.map((activity, idx) => (
          <div key={idx} className="p-4 hover:bg-slate-50 transition-colors flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="relative w-10 h-10 shrink-0 overflow-hidden rounded-full bg-slate-100 flex items-center justify-center text-slate-500 font-bold">
                <span>{activity.name ? activity.name.charAt(0) : '?'}</span>
                {activity.captured_image && (
                  <img src={imageSource(activity.captured_image)} alt={`${activity.name || 'Person'} attendance capture`}
                    onError={event => { event.currentTarget.style.display = 'none'; }}
                    className="absolute inset-0 h-full w-full object-cover" />
                )}
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-800">{activity.name || 'Unknown'}</p>
                <p className="text-xs text-slate-500">{activity.device_name || 'Unknown device'}{activity.department ? ` • ${activity.department}` : ''}</p>
              </div>
            </div>
            <div className="text-right">
              <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                activity.is_late === 1
                  ? 'bg-amber-100 text-amber-800'
                  : activity.status === 'CHECK_IN' 
                    ? 'bg-green-100 text-green-800' 
                    : 'bg-purple-100 text-purple-800'
              }`}>
                {activity.is_late === 1 
                  ? 'Late' 
                  : (activity.status === 'CHECK_IN' ? 'Check In' : 'Check Out')}
                {activity.activity && activity.activity !== 'Work' && ` (${activity.activity})`}
              </span>
              <p className="text-xs text-slate-400 mt-1">
                {activity.timestamp ? new Date(activity.timestamp.replace(' ', 'T')).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '--:--'}
              </p>
            </div>
          </div>
        ))}
        {activities.length === 0 && (
          <div className="p-8 text-center text-slate-400">No activity recorded yet.</div>
        )}
      </div>
    </div>
  );
};

export default ActivityDashboard;
