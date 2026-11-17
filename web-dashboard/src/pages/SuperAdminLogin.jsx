import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Lock } from 'lucide-react';
import BrandLogo from '../components/BrandLogo';

const SuperAdminLogin = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login, logout } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    const result = await login(username, password);
    if (result.success) {
      if (result.role !== 'super_admin') {
        logout();
        setError('Access Denied. You are not a Super Admin.');
        return;
      }
      navigate('/admin/vendors');
    } else {
      setError(result.error);
    }
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden"
      style={{
        background: 'radial-gradient(circle at 18% 5%, rgba(124,58,255,0.15), transparent 34rem), #08090A',
      }}
    >
      <div
        className="rounded-[22px] w-full max-w-md overflow-hidden"
        style={{
          background: 'rgba(17,19,21,0.96)',
          border: '1px solid rgba(255,255,255,0.11)',
          boxShadow: '0 32px 90px rgba(0,0,0,0.58), inset 0 1px 0 rgba(255,255,255,0.04)',
        }}
      >
        <div className="p-8 text-center" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div
            className="w-20 h-20 rounded-2xl flex items-center justify-center mx-auto mb-5 p-3"
            style={{ background: '#0C0D0F', border: '1px solid rgba(255,255,255,0.12)' }}
          >
            <BrandLogo className="h-12 w-12" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-[-0.035em]">Super Admin Portal</h1>
          <p className="mt-2 text-sm" style={{ color: '#888C92' }}>System management access only</p>
        </div>

        <div className="p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {error && (
              <div className="text-sm p-3 rounded-xl" style={{ background: 'rgba(255,59,59,0.1)', color: '#FF7070', border: '1px solid rgba(255,59,59,0.22)' }}>
                {error}
              </div>
            )}
            
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-[0.12em] mb-2" style={{ color: '#9B9EA3' }}>Username</label>
              <div className="relative">
                <input
                  type="text"
                  required
                  className="input-glow w-full pl-4 pr-4 py-3 rounded-xl transition-colors"
                  style={{ background: '#16181B', border: '1px solid rgba(255,255,255,0.11)', color: '#fff', outline: 'none' }}
                  placeholder="superadmin"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-[0.12em] mb-2" style={{ color: '#9B9EA3' }}>Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#73777D' }} size={18} />
                <input
                  type="password"
                  required
                  className="input-glow w-full pl-10 pr-4 py-3 rounded-xl transition-colors"
                  style={{ background: '#16181B', border: '1px solid rgba(255,255,255,0.11)', color: '#fff', outline: 'none' }}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            </div>

            <button
              type="submit"
              className="btn-primary w-full text-white font-semibold py-3 px-4 rounded-xl"
            >
              Authenticate
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default SuperAdminLogin;
