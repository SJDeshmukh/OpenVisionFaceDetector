import { 
  CreditCard,
  Calendar,
  Users,
  Shield,
  AlertTriangle,
  LogOut
} from 'lucide-react';
import { useState, useEffect } from 'react';
import axios from 'axios';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';

const Recharge = () => {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [subscription, setSubscription] = useState(null);
  
  useEffect(() => {
    // Fetch ONLY subscription data (safe endpoint)
    axios.get(`${API_URL}/vendor/subscription`)
      .then(res => setSubscription(res.data))
      .catch(err => {
          console.error("Error fetching subscription:", err);
          if (err.response?.status === 401) {
              logout();
          }
      });
  }, [logout]);

  return (
    <div className="min-h-screen bg-slate-50 p-8">
      <div className="max-w-5xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex justify-between items-center bg-white p-6 rounded-xl border border-red-200 shadow-sm">
            <div className="flex items-center gap-4">
                <div className="p-3 bg-red-100 text-red-600 rounded-full">
                    <AlertTriangle size={32} />
                </div>
                <div>
                    <h1 className="text-2xl font-bold text-slate-800">Plan Expired</h1>
                    <p className="text-red-600 font-medium">Please recharge your plan to continue using the dashboard.</p>
                </div>
            </div>
            <button 
                onClick={logout}
                className="flex items-center gap-2 px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            >
                <LogOut size={20} />
                Logout
            </button>
        </div>

        {/* Plan Details (Copied/Adapted from Dashboard) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
           {subscription ? (
             <>
               <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm space-y-6">
                 <div className="flex justify-between items-start">
                    <div>
                      <h2 className="text-2xl font-bold text-slate-800 mb-1">Current Subscription</h2>
                      <p className="text-slate-500">Manage your billing and plan details</p>
                    </div>
                    <span className="px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-700">
                      EXPIRED
                    </span>
                 </div>
                 
                 <div className="p-4 bg-slate-50 rounded-lg border border-slate-100">
                    <div className="flex justify-between items-center mb-2">
                       <span className="text-sm text-slate-500">Current Plan</span>
                       <span className="font-bold text-slate-800 text-lg capitalize">{subscription.plan_type}</span>
                    </div>
                    <div className="flex justify-between items-center">
                       <span className="text-sm text-slate-500">Cost per User</span>
                       <span className="font-bold text-slate-800">₹{subscription.cost_per_user}/mo</span>
                    </div>
                 </div>

                 <div className="space-y-4">
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-500">Subscription Period</span>
                        <span className="font-medium text-red-600">0 Days Left</span>
                      </div>
                      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full bg-red-500 w-full"></div>
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-4">
                       <div className="p-3 border border-slate-200 rounded-lg">
                          <div className="flex items-center gap-2 text-slate-500 mb-1">
                             <Calendar size={16} />
                             <span className="text-xs">Start Date</span>
                          </div>
                          <p className="font-medium text-slate-800">{subscription.start_date}</p>
                       </div>
                       <div className="p-3 border border-slate-200 rounded-lg">
                          <div className="flex items-center gap-2 text-slate-500 mb-1">
                             <Calendar size={16} />
                             <span className="text-xs">End Date</span>
                          </div>
                          <p className="font-medium text-slate-800">{subscription.end_date}</p>
                       </div>
                    </div>
                 </div>
               </div>

               <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm space-y-6">
                  <h2 className="text-xl font-bold text-slate-800">Payment & Usage</h2>
                  
                  <div className="space-y-4">
                     <div className="flex items-center justify-between p-4 border-2 border-red-100 bg-red-50 rounded-lg">
                        <div className="flex items-center gap-4">
                           <div className="p-3 bg-white text-red-600 rounded-lg shadow-sm">
                              <CreditCard size={24} />
                           </div>
                           <div>
                              <p className="font-medium text-red-900">Payment Overdue</p>
                              <p className="text-sm text-red-700">Due since {subscription.end_date}</p>
                           </div>
                        </div>
                        <span className="font-bold text-red-900 text-lg">
                           ₹{(subscription.cost_per_user * subscription.max_users).toLocaleString()}
                        </span>
                     </div>

                     <div className="flex items-center justify-between p-4 border border-slate-200 rounded-lg">
                        <div className="flex items-center gap-4">
                           <div className="p-3 bg-purple-50 text-purple-600 rounded-lg">
                              <Users size={24} />
                           </div>
                           <div>
                              <p className="font-medium text-slate-800">User Limit</p>
                              <p className="text-sm text-slate-500">Active users allowed</p>
                           </div>
                        </div>
                        <span className="font-bold text-slate-800 text-lg">{subscription.max_users} Users</span>
                     </div>
                     
                     <div className="bg-blue-50 text-blue-800 p-4 rounded-lg text-sm flex gap-3 items-start">
                        <Shield size={20} className="shrink-0 mt-0.5" />
                        <p>Contact your Super Admin to renew your subscription and restore full access.</p>
                     </div>
                  </div>
               </div>
             </>
           ) : (
             <div className="col-span-2 text-center py-12 text-slate-400">
                <p>Loading subscription details...</p>
             </div>
           )}
        </div>
      </div>
    </div>
  );
};

export default Recharge;