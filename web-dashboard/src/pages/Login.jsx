import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import axios from 'axios';
import { Lock, User, Eye, EyeOff, Zap } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { API_URL } from '../config';
import BrandLogo from '../components/BrandLogo';

const cardVariants = {
  hidden:  { opacity: 0, y: 28, scale: 0.96 },
  visible: { opacity: 1, y: 0,  scale: 1,
    transition: { duration: 0.52, ease: [0.22, 1, 0.36, 1] } },
};

const itemVariants = {
  hidden:  { opacity: 0, y: 12 },
  visible: (i) => ({
    opacity: 1, y: 0,
    transition: { delay: 0.18 + i * 0.08, duration: 0.4, ease: [0.22, 1, 0.36, 1] },
  }),
};

const errorVariants = {
  hidden:  { opacity: 0, y: -8, scale: 0.97 },
  visible: { opacity: 1, y: 0,  scale: 1 },
  exit:    { opacity: 0, scale: 0.97 },
};

/* ── Field ── */
const Field = ({ label, icon: Icon, type, value, onChange, placeholder, extra, custom }) => {
  const [focused, setFocused] = useState(false);
  return (
    <motion.div custom={custom} variants={itemVariants} initial="hidden" animate="visible" className="space-y-1.5">
      <label className="block text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: '#5050A0' }}>
        {label}
      </label>
      <div className="relative">
        <Icon
          size={16}
          className="absolute left-3.5 top-1/2 -translate-y-1/2 transition-colors duration-200"
          style={{ color: focused ? '#9B6AFF' : '#505080' }}
        />
        <input
          type={type}
          value={value}
          onChange={onChange}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={placeholder}
          required
          className="w-full pl-10 pr-10 py-3 rounded-xl text-sm font-medium transition-all duration-200"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: `1px solid ${focused ? 'rgba(124,58,255,0.5)' : 'rgba(124,58,255,0.18)'}`,
            boxShadow: focused ? '0 0 0 3px rgba(124,58,255,0.1), 0 0 20px rgba(124,58,255,0.06)' : 'none',
            color: '#fff',
            outline: 'none',
          }}
        />
        {extra}
      </div>
    </motion.div>
  );
};

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [pin, setPin] = useState('');
  const [pinFocused, setPinFocused] = useState(false);
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
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
    setLoading(true);
    const result = await login(username, password);
    setLoading(false);
    if (result.success) {
      if (result.role === 'super_admin') { logout(); setError('Please use the Super Admin Portal.'); return; }
      if (result.force_password_change) { setShowPasswordChange(true); return; }
      if (result.status === 'success' && result.needs_student_password) { setShowStudentPasswordModal(true); return; }
      if (result.role === 'faculty') { navigate('/classes'); return; }
      if (result.role === 'user') { navigate('/leave-management'); return; }
      const storedUser = JSON.parse(localStorage.getItem('user'));
      if (storedUser?.role === 'vendor_admin' && storedUser?.features?.includes('leave_management')) { setStep(1); return; }
      if (result.redirect_url) { navigate(result.redirect_url); return; }
      navigate('/dashboard');
    } else {
      setError(result.error);
    }
  };

  const handlePinSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const res = await loginAsStaff(pin);
    if (res.success) navigate('/leave-management');
    else setError(res.error || 'Invalid PIN');
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) { setError('Passwords do not match'); return; }
    if (newPassword.length < 4) { setError('Password must be at least 4 characters'); return; }
    setChanging(true);
    try {
      const res = await axios.post(`${API_URL}/leave/student/change-password`, { password: newPassword });
      if (res.data.status === 'success') {
        setShowPasswordChange(false);
        alert('Password changed! Please login with your new password.');
        logout(); setUsername(''); setPassword(''); setStep(0);
      }
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to change password');
    } finally {
      setChanging(false);
    }
  };

  const handleStudentPasswordSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const result = await login(username, password, studentPassword);
    if (result.success) { setShowStudentPasswordModal(false); setStudentPassword(''); navigate('/leave-management'); }
    else setError(result.error || 'Invalid custom password');
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden"
      style={{ background: '#07071A' }}
    >
      {/* ── Background orbs ── */}
      <div
        className="absolute pointer-events-none rounded-full"
        style={{
          width: 560, height: 560,
          background: 'radial-gradient(circle, rgba(124,58,255,0.22) 0%, transparent 70%)',
          top: '-16%', left: '-12%',
          animation: 'floatOrb 12s ease-in-out infinite',
          filter: 'blur(1px)',
        }}
      />
      <div
        className="absolute pointer-events-none rounded-full"
        style={{
          width: 420, height: 420,
          background: 'radial-gradient(circle, rgba(6,214,255,0.18) 0%, transparent 70%)',
          bottom: '-12%', right: '-8%',
          animation: 'floatOrb 10s ease-in-out infinite 3s',
          filter: 'blur(1px)',
        }}
      />
      <div
        className="absolute pointer-events-none rounded-full"
        style={{
          width: 280, height: 280,
          background: 'radial-gradient(circle, rgba(255,45,135,0.14) 0%, transparent 70%)',
          top: '45%', right: '18%',
          animation: 'floatOrbSlow 16s ease-in-out infinite 6s',
          filter: 'blur(1px)',
        }}
      />

      {/* Grid pattern */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: `linear-gradient(rgba(124,58,255,0.035) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(124,58,255,0.035) 1px, transparent 1px)`,
          backgroundSize: '42px 42px',
        }}
      />

      {/* ── Login Card ── */}
      <motion.div
        variants={cardVariants} initial="hidden" animate="visible"
        className="relative w-full max-w-[400px] rounded-2xl overflow-hidden"
        style={{
          background: 'rgba(13, 12, 42, 0.92)',
          backdropFilter: 'blur(28px)',
          WebkitBackdropFilter: 'blur(28px)',
          border: '1px solid rgba(124,58,255,0.22)',
          boxShadow: '0 30px 90px rgba(0,0,0,0.7), 0 0 0 1px rgba(124,58,255,0.07) inset, 0 1px 0 rgba(255,255,255,0.05) inset',
        }}
      >
        {/* Header */}
        <div
          className="relative px-8 pt-8 pb-7 text-center overflow-hidden"
          style={{
            background: 'linear-gradient(135deg, rgba(124,58,255,0.28) 0%, rgba(6,214,255,0.12) 100%)',
          }}
        >
          {/* Shimmer line */}
          <div
            className="absolute top-0 left-0 right-0 h-px"
            style={{ background: 'linear-gradient(90deg, transparent, rgba(124,58,255,0.6), rgba(6,214,255,0.6), transparent)' }}
          />

          {/* Logo with pulse rings */}
          <div className="relative w-[72px] h-[72px] mx-auto mb-4">
            <div
              className="absolute inset-[-10px] rounded-full"
              style={{ border: '1.5px solid rgba(124,58,255,0.35)', animation: 'pulseRing 2.8s ease-in-out infinite' }}
            />
            <div
              className="absolute inset-[-4px] rounded-full"
              style={{ border: '1px solid rgba(6,214,255,0.25)', animation: 'pulseRing 2.8s ease-in-out infinite 0.55s' }}
            />
            <div
              className="w-full h-full rounded-2xl flex items-center justify-center"
              style={{
                background: 'linear-gradient(145deg, #090C28 0%, #111748 100%)',
                border: '1px solid rgba(182,108,255,0.5)',
                boxShadow: '0 0 28px rgba(124,58,255,0.7), 0 0 56px rgba(124,58,255,0.25)',
              }}
            >
              <BrandLogo className="h-[58px] w-[58px]" />
            </div>
          </div>

          <h1 className="text-xl font-bold text-white tracking-tight">TapInX Admin</h1>
          <p className="text-xs mt-1 flex items-center justify-center gap-1.5" style={{ color: 'rgba(196,196,224,0.6)' }}>
            <Zap size={11} style={{ color: '#7C3AFF' }} />
            Powered by OpenVisionX
          </p>
        </div>

        {/* Body */}
        <div className="px-8 py-7">
          <AnimatePresence mode="wait">
            {step === 0 ? (
              <motion.form
                key="login"
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 16 }}
                transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                onSubmit={handleSubmit}
                className="space-y-4"
              >
                <AnimatePresence>
                  {error && (
                    <motion.div
                      variants={errorVariants} initial="hidden" animate="visible" exit="exit"
                      className="flex items-center gap-2.5 p-3 rounded-xl text-sm animate-error-shake"
                      style={{ background: 'rgba(255,59,59,0.1)', border: '1px solid rgba(255,59,59,0.22)', color: '#FF7070' }}
                    >
                      <span className="flex-shrink-0">⚠</span>
                      <span>{error}</span>
                    </motion.div>
                  )}
                </AnimatePresence>

                <Field label="Username" icon={User} type="text"
                  value={username} onChange={e => setUsername(e.target.value)}
                  placeholder="Enter username" custom={0} />

                <Field label="Password" icon={Lock}
                  type={showPassword ? 'text' : 'password'}
                  value={password} onChange={e => setPassword(e.target.value)}
                  placeholder="Enter password" custom={1}
                  extra={
                    <button
                      type="button"
                      onClick={() => setShowPassword(p => !p)}
                      className="absolute right-3.5 top-1/2 -translate-y-1/2 transition-colors duration-200"
                      style={{ color: '#505080' }}
                      onMouseEnter={e => e.currentTarget.style.color = '#9B6AFF'}
                      onMouseLeave={e => e.currentTarget.style.color = '#505080'}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  }
                />

                <motion.button
                  custom={2} variants={itemVariants} initial="hidden" animate="visible"
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full py-3.5 rounded-xl text-sm font-semibold tracking-wide mt-1"
                >
                  {loading ? (
                    <span className="flex items-center justify-center gap-2">
                      <span
                        className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full"
                        style={{ animation: 'spin360 0.7s linear infinite' }}
                      />
                      Signing in…
                    </span>
                  ) : 'Sign In'}
                </motion.button>
              </motion.form>
            ) : (
              <motion.form
                key="pin"
                initial={{ opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -16 }}
                transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                onSubmit={handlePinSubmit}
                className="space-y-5"
              >
                <div className="text-center">
                  <p className="text-base font-bold text-white">Staff Verification</p>
                  <p className="text-xs mt-1" style={{ color: '#5050A0' }}>Enter your 4-digit PIN (Rector/HOD)</p>
                </div>

                <AnimatePresence>
                  {error && (
                    <motion.div
                      variants={errorVariants} initial="hidden" animate="visible" exit="exit"
                      className="flex items-center gap-2.5 p-3 rounded-xl text-sm"
                      style={{ background: 'rgba(255,59,59,0.1)', border: '1px solid rgba(255,59,59,0.22)', color: '#FF7070' }}
                    >
                      <span>⚠</span><span>{error}</span>
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="flex justify-center">
                  <input
                    type="text" maxLength={4} value={pin}
                    onChange={e => setPin(e.target.value.replace(/\D/g, ''))}
                    onFocus={() => setPinFocused(true)}
                    onBlur={() => setPinFocused(false)}
                    autoFocus
                    className="w-36 text-center text-3xl font-bold py-4 rounded-2xl transition-all duration-200"
                    style={{
                      background: 'rgba(255,255,255,0.04)',
                      border: `2px solid ${pinFocused ? 'rgba(124,58,255,0.55)' : 'rgba(124,58,255,0.2)'}`,
                      boxShadow: pinFocused ? '0 0 0 4px rgba(124,58,255,0.1), 0 0 24px rgba(124,58,255,0.08)' : 'none',
                      color: '#fff',
                      letterSpacing: '0.8em',
                      outline: 'none',
                    }}
                    placeholder="••••"
                  />
                </div>

                <div className="space-y-2">
                  <button
                    type="submit"
                    disabled={pin.length < 4}
                    className="btn-primary w-full py-3.5 rounded-xl text-sm font-semibold"
                  >
                    Verify PIN
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/dashboard')}
                    className="w-full py-2.5 text-sm font-medium rounded-xl transition-colors duration-200"
                    style={{ color: '#5050A0' }}
                    onMouseEnter={e => e.currentTarget.style.color = '#C4C4E0'}
                    onMouseLeave={e => e.currentTarget.style.color = '#5050A0'}
                  >
                    Skip to Dashboard
                  </button>
                </div>
              </motion.form>
            )}
          </AnimatePresence>
        </div>

        {/* Footer */}
        <div
          className="px-8 py-3.5 text-center text-[11px]"
          style={{ borderTop: '1px solid rgba(124,58,255,0.1)', color: '#404070' }}
        >
          Default: admin / admin123 · Kiosk: kiosk / kiosk123
        </div>
      </motion.div>

      {/* ── Change Password Modal ── */}
      <AnimatePresence>
        {showPasswordChange && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(4,4,20,0.88)', backdropFilter: 'blur(8px)' }}
          >
            <motion.div
              initial={{ scale: 0.93, y: 16 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.93, y: 16 }}
              transition={{ type: 'spring', stiffness: 280, damping: 28 }}
              className="w-full max-w-sm rounded-2xl overflow-hidden"
              style={{
                background: 'rgba(13,12,42,0.97)',
                border: '1px solid rgba(124,58,255,0.25)',
                boxShadow: '0 24px 80px rgba(0,0,0,0.7)',
              }}
            >
              <div className="px-7 pt-7 pb-5" style={{ background: 'linear-gradient(135deg, rgba(124,58,255,0.28) 0%, rgba(6,214,255,0.1) 100%)' }}>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Lock size={18} style={{ color: '#9B6AFF' }} /> Change Password
                </h2>
                <p className="text-xs mt-1.5" style={{ color: 'rgba(196,196,224,0.65)' }}>
                  You must change your password on first login.
                </p>
              </div>
              <form onSubmit={handlePasswordChange} className="px-7 py-6 space-y-4">
                {error && (
                  <div className="text-xs p-3 rounded-xl" style={{ background: 'rgba(255,59,59,0.1)', border: '1px solid rgba(255,59,59,0.22)', color: '#FF7070' }}>
                    {error}
                  </div>
                )}
                {[
                  { label: 'New Password', value: newPassword, onChange: e => setNewPassword(e.target.value) },
                  { label: 'Confirm Password', value: confirmPassword, onChange: e => setConfirmPassword(e.target.value) },
                ].map(({ label, value, onChange }) => (
                  <div key={label} className="space-y-1.5">
                    <label className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: '#5050A0' }}>{label}</label>
                    <input
                      type="password" required value={value} onChange={onChange}
                      className="w-full px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 input-glow"
                      style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(124,58,255,0.18)', color: '#fff', outline: 'none' }}
                      placeholder="At least 4 characters"
                    />
                  </div>
                ))}
                <button
                  type="submit"
                  disabled={changing || !newPassword || newPassword !== confirmPassword}
                  className="btn-primary w-full py-3.5 rounded-xl text-sm font-semibold mt-1"
                >
                  {changing ? 'Updating…' : 'Update Password & Login'}
                </button>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Student Password Modal ── */}
      <AnimatePresence>
        {showStudentPasswordModal && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(4,4,20,0.88)', backdropFilter: 'blur(8px)' }}
          >
            <motion.div
              initial={{ scale: 0.93, y: 16 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.93, y: 16 }}
              transition={{ type: 'spring', stiffness: 280, damping: 28 }}
              className="w-full max-w-sm rounded-2xl overflow-hidden"
              style={{
                background: 'rgba(13,12,42,0.97)',
                border: '1px solid rgba(124,58,255,0.25)',
                boxShadow: '0 24px 80px rgba(0,0,0,0.7)',
              }}
            >
              <div className="px-7 pt-7 pb-5" style={{ background: 'linear-gradient(135deg, rgba(124,58,255,0.28) 0%, rgba(6,214,255,0.1) 100%)' }}>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Lock size={18} style={{ color: '#9B6AFF' }} /> Identity Verification
                </h2>
                <p className="text-xs mt-1.5" style={{ color: 'rgba(196,196,224,0.65)' }}>
                  Enter your custom password to continue.
                </p>
              </div>
              <form onSubmit={handleStudentPasswordSubmit} className="px-7 py-6 space-y-4">
                {error && (
                  <div className="text-xs p-3 rounded-xl" style={{ background: 'rgba(255,59,59,0.1)', border: '1px solid rgba(255,59,59,0.22)', color: '#FF7070' }}>
                    {error}
                  </div>
                )}
                <div className="space-y-1.5">
                  <label className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: '#5050A0' }}>Custom Password</label>
                  <input
                    type="password" required autoFocus
                    value={studentPassword} onChange={e => setStudentPassword(e.target.value)}
                    className="w-full px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 input-glow"
                    style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(124,58,255,0.18)', color: '#fff', outline: 'none' }}
                    placeholder="Enter your set password"
                  />
                </div>
                <button type="submit" className="btn-primary w-full py-3.5 rounded-xl text-sm font-semibold">
                  Verify & Login
                </button>
                <button
                  type="button"
                  onClick={() => setShowStudentPasswordModal(false)}
                  className="w-full py-2.5 text-sm font-medium transition-colors duration-200"
                  style={{ color: '#5050A0' }}
                  onMouseEnter={e => e.currentTarget.style.color = '#C4C4E0'}
                  onMouseLeave={e => e.currentTarget.style.color = '#5050A0'}
                >
                  Cancel
                </button>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default Login;
