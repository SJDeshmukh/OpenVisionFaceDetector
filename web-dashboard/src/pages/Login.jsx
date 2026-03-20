import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import axios from 'axios';
import { Lock, User } from 'lucide-react';

import { API_URL } from '../config';

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [pin, setPin] = useState('');
  const [step, setStep] = useState(0); // 0: Login, 1: PIN
  const [showPasswordChange, setShowPasswordChange] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showStudentPasswordModal, setShowStudentPasswordModal] = useState(false);
  const [studentPassword, setStudentPassword] = useState('');
  const [changing, setChanging] = useState(false);
  const { login, logout, loginAsStaff } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const result = await login(username, password);
    if (result.success) {
      if (result.role === 'super_admin') {
        logout();
        setError('Please use the Super Admin Portal to login.');
        return;
      }
      
      if (result.force_password_change) {
        setShowPasswordChange(true);
        return;
      }

      // INTELLIGENCE: Distinguish between Student and Staff
      if (result.status === 'success' && result.needs_student_password) {
        setShowStudentPasswordModal(true);
        return;
      }

      if (result.role === 'user') {
        // It's a student - go directly to leave-management (which handles student tabs)
        navigate('/leave-management');
        return;
      }

      // Check for leave management feature to show PIN prompt for STAFF (Vendors)
      const storedUser = JSON.parse(localStorage.getItem('user'));
      if (storedUser?.role === 'vendor_admin' && storedUser?.features?.includes('leave_management')) {
        setStep(1);
        return;
      }

      if (result.redirect_url) {
        navigate(result.redirect_url);
        return;
      }

      navigate('/dashboard');
    } else {
      setError(result.error);
    }
  };

  const handlePinSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const res = await loginAsStaff(pin);
    if (res.success) {
      navigate('/leave-management');
    } else {
      setError(res.error || "Invalid PIN");
    }
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (newPassword.length < 4) {
      setError("Password must be at least 4 characters");
      return;
    }

    setChanging(true);
    try {
      const res = await axios.post(`${API_URL}/leave/student/change-password`, {
        password: newPassword
      });
      if (res.data.status === 'success') {
        setShowPasswordChange(false);
        alert("Password changed successfully! Please login with your new password.");
        logout();
        setUsername('');
        setPassword('');
        setStep(0);
      }
    } catch (err) {
      setError(err.response?.data?.error || "Failed to change password");
    } finally {
      setChanging(false);
    }
  };

  const handleStudentPasswordSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const result = await login(username, password, studentPassword);
    if (result.success) {
      setShowStudentPasswordModal(false);
      setStudentPassword('');
      navigate('/leave-management');
    } else {
      setError(result.error || "Invalid custom password");
    }
  };

  const handleSkipPin = () => {
    navigate('/dashboard');
  };

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden">
        <div className="p-8 text-center bg-blue-600">
          <div className="w-20 h-20 bg-black rounded-full flex items-center justify-center mx-auto mb-4 p-3">
            <img src="/tapinx-logo.svg" alt="TapInX" className="w-full h-full object-contain" />
          </div>
          <h1 className="text-2xl font-bold text-white">TapInX Admin</h1>
          <p className="text-blue-100 mt-2 text-sm">Powered by OpenVisionX</p>
        </div>

        <div className="p-8">
          {step === 0 ? (
            <form onSubmit={handleSubmit} className="space-y-6">
              {error && (
                <div className="bg-red-50 text-red-600 text-sm p-3 rounded-lg border border-red-200">
                  {error}
                </div>
              )}
              
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Username</label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="w-full pl-10 pr-4 py-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                    placeholder="Enter username"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full pl-10 pr-4 py-3 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                    placeholder="Enter password"
                    required
                  />
                </div>
              </div>

              <button
                type="submit"
                className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-lg transition-colors shadow-lg shadow-blue-600/30"
              >
                Sign In
              </button>
            </form>
          ) : (
            <form onSubmit={handlePinSubmit} className="space-y-6 animate-in slide-in-from-right-4 duration-300">
              <div className="text-center mb-4">
                <h2 className="text-lg font-bold text-slate-800">Staff Verification</h2>
                <p className="text-sm text-slate-500">Enter your 4-digit PIN (Rector/HOD)</p>
              </div>

              {error && (
                <div className="bg-red-50 text-red-600 text-sm p-3 rounded-lg border border-red-200">
                  {error}
                </div>
              )}
              
              <div className="flex justify-center">
                <input
                  type="text"
                  maxLength={4}
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
                  className="w-32 text-center text-3xl font-bold tracking-[1em] py-4 border-2 border-slate-200 rounded-xl focus:outline-none focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 transition-all"
                  placeholder="••••"
                  autoFocus
                />
              </div>

              <div className="space-y-3">
                <button
                  type="submit"
                  disabled={pin.length < 4}
                  className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-lg transition-colors shadow-lg shadow-blue-600/30 disabled:opacity-50"
                >
                  Verify PIN
                </button>
                <button
                  type="button"
                  onClick={handleSkipPin}
                  className="w-full py-3 text-slate-500 hover:text-slate-700 font-medium rounded-lg transition-colors"
                >
                  Skip to Admin Dashboard
                </button>
              </div>
            </form>
          )}
        </div>
        
        <div className="bg-slate-50 p-4 text-center text-xs text-slate-500 border-t border-slate-100">
          Default Admin: admin / admin123
          <br/>
          Kiosk User: kiosk / kiosk123
        </div>
      </div>

      {showPasswordChange && (
        <div className="fixed inset-0 bg-slate-900/90 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in fade-in zoom-in duration-300">
            <div className="p-6 bg-blue-600 text-white">
              <h2 className="text-xl font-bold flex items-center gap-2">
                <Lock size={20} /> Change Password
              </h2>
              <p className="text-blue-100 text-sm mt-1">For your security, you must change your password on first login.</p>
            </div>
            <form onSubmit={handlePasswordChange} className="p-6 space-y-4">
              {error && (
                <div className="bg-red-50 text-red-600 text-xs p-3 rounded-lg border border-red-200">
                  {error}
                </div>
              )}
              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">New Password</label>
                <input
                  type="password"
                  required
                  autoFocus
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
                  placeholder="At least 4 characters"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">Confirm New Password</label>
                <input
                  type="password"
                  required
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
                  placeholder="Repeat new password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </div>
              <button
                type="submit"
                disabled={changing || !newPassword || newPassword !== confirmPassword}
                className="w-full bg-blue-600 text-white py-3.5 rounded-xl font-bold hover:bg-blue-700 transition-all shadow-lg shadow-blue-200 disabled:opacity-50"
              >
                {changing ? "Updating Password..." : "Update Password & Login"}
              </button>
            </form>
          </div>
        </div>
      )}
      {showStudentPasswordModal && (
        <div className="fixed inset-0 bg-slate-900/90 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in fade-in zoom-in duration-300">
            <div className="p-6 bg-blue-600 text-white">
              <h2 className="text-xl font-bold flex items-center gap-2">
                <Lock size={20} /> Identity Verification
              </h2>
              <p className="text-blue-100 text-sm mt-1">Please enter your custom password to continue.</p>
            </div>
            <form onSubmit={handleStudentPasswordSubmit} className="p-6 space-y-4">
              {error && (
                <div className="bg-red-50 text-red-600 text-xs p-3 rounded-lg border border-red-200">
                  {error}
                </div>
              )}
              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider">Custom Password</label>
                <input
                  type="password"
                  required
                  autoFocus
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
                  placeholder="Enter your set password"
                  value={studentPassword}
                  onChange={(e) => setStudentPassword(e.target.value)}
                />
              </div>
              <button
                type="submit"
                className="w-full py-4 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl transition-all shadow-lg shadow-blue-600/20"
              >
                Verify & login
              </button>
              <button
                type="button"
                onClick={() => setShowStudentPasswordModal(false)}
                className="w-full py-2 text-slate-400 text-sm font-medium hover:text-slate-600 transition-colors"
              >
                Cancel
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Login;
