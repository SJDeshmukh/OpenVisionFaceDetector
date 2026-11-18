import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { API_URL } from '../config';
import PageLoader from '../components/PageLoader';

axios.defaults.withCredentials = true;

const AuthContext = createContext();
const STAFF_HEADER = 'X-Leave-Staff-Token';
const IDLE_TRANSITION = Object.freeze({ active: false, kind: null, phase: 'idle' });

const wait = (duration) => new Promise(resolve => window.setTimeout(resolve, duration));

const reducedMotionPreferred = () => (
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
);

const applyStaffSession = (staff) => {
  if (staff?.access_token) {
    axios.defaults.headers.common[STAFF_HEADER] = staff.access_token;
  } else {
    delete axios.defaults.headers.common[STAFF_HEADER];
  }
};

const signOutFirebase = async () => {
  try {
    const [{ signOut }, { firebaseAuth }] = await Promise.all([
      import('firebase/auth'),
      import('../lib/firebaseAuth'),
    ]);
    await signOut(firebaseAuth);
  } catch {
    // TapInX logout must still complete if Firebase is unavailable.
  }
};

const withoutToken = (value) => {
  if (!value) return value;
  const safe = { ...value };
  delete safe.token;
  return safe;
};

const isSessionUnauthorized = (error) => {
  if (error.response?.status !== 401) return false;
  const code = String(error.response?.data?.code || '').toUpperCase();
  const message = String(error.response?.data?.error || '').toLowerCase();
  const endpoint = String(error.config?.url || '');

  if (endpoint.includes('/auth/me') || code === 'UNAUTHORIZED' || code === 'USER_NOT_FOUND') {
    return true;
  }

  return message === 'unauthorized' ||
    message === 'authentication required' ||
    message === 'invalid token' ||
    message === 'invalid or expired token' ||
    message === 'missing authorization header' ||
    message.startsWith('session expired');
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [staffSession, setStaffSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [entryTransitionPending, setEntryTransitionPending] = useState(false);
  const [sessionTransition, setSessionTransition] = useState(IDLE_TRANSITION);
  const [authNotice, setAuthNotice] = useState(null);
  const transitionLockRef = useRef(false);
  const logoutTransitionActiveRef = useRef(false);
  const logoutRequestRef = useRef(null);

  const clearSensitiveCaches = useCallback(() => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('people_cache_') || key.startsWith('dashboard_cache_') ||
          key.startsWith('bulk_attendance_batch_') || key.startsWith('registration_batch_id_') ||
          key.startsWith('admin_')) {
        localStorage.removeItem(key);
      }
    }
    ['registration_batch_id', 'active_lecture_id', 'lastClassFilter', 'token']
      .forEach((key) => localStorage.removeItem(key));
  }, []);

  const clearLocalSession = useCallback(async () => {
    setUser(null);
    setStaffSession(null);
    setEntryTransitionPending(false);
    localStorage.removeItem('user');
    localStorage.removeItem('staffSession');
    clearSensitiveCaches();
    delete axios.defaults.headers.common.Authorization;
    applyStaffSession(null);
    await signOutFirebase();
  }, [clearSensitiveCaches]);

  const requestServerLogout = useCallback(() => {
    if (logoutRequestRef.current) return logoutRequestRef.current;
    const deviceId = localStorage.getItem('web_device_id');
    const request = axios.post(`${API_URL}/auth/logout`, { device_id: deviceId })
      .then(() => ({ success: true }))
      .catch((error) => {
        // A rejected/missing session is already unusable, which is a safe
        // terminal state for logout. Network and 5xx failures keep local state.
        const responseMessage = String(error.response?.data?.error || '').toLowerCase();
        const alreadyLoggedOut = error.response?.status === 401 ||
          (error.response?.status === 400 && responseMessage.includes('token or credentials required'));
        if (alreadyLoggedOut) return { success: true };
        return {
          success: false,
          error: error.response?.data?.error || 'Could not securely sign out. Check your connection and try again.',
        };
      })
      .finally(() => {
        logoutRequestRef.current = null;
      });
    logoutRequestRef.current = request;
    return request;
  }, []);

  const logout = useCallback(async ({ serverAlreadyRevoked = false } = {}) => {
    const result = serverAlreadyRevoked ? { success: true } : await requestServerLogout();
    if (!result.success) {
      setAuthNotice({ type: 'error', message: result.error });
      return result;
    }
    await clearLocalSession();
    return { success: true };
  }, [clearLocalSession, requestServerLogout]);

  const completeLoginTransition = useCallback(async (showAuthenticatedView) => {
    if (transitionLockRef.current) return { success: false, busy: true };
    transitionLockRef.current = true;
    setAuthNotice(null);
    const reducedMotion = reducedMotionPreferred();
    try {
      setSessionTransition({ active: true, kind: 'login', phase: 'opening' });
      await wait(reducedMotion ? 0 : 900);

      // The wave fully covers the viewport before protected routes can render.
      setEntryTransitionPending(false);
      setSessionTransition({ active: true, kind: 'login', phase: 'revealing' });
      await showAuthenticatedView?.();
      await wait(reducedMotion ? 0 : 600);
      setSessionTransition(IDLE_TRANSITION);
      return { success: true };
    } finally {
      transitionLockRef.current = false;
    }
  }, []);

  const logoutWithTransition = useCallback(async (showLoginView) => {
    if (transitionLockRef.current) return { success: false, busy: true };
    transitionLockRef.current = true;
    setAuthNotice(null);
    const reducedMotion = reducedMotionPreferred();
    const startedAt = performance.now();
    let transitioningTimer;
    logoutTransitionActiveRef.current = true;
    try {
      setSessionTransition({ active: true, kind: 'logout', phase: 'closing' });
      if (reducedMotion) {
        setSessionTransition({ active: true, kind: 'logout', phase: 'transitioning' });
      } else {
        transitioningTimer = window.setTimeout(() => {
          setSessionTransition({ active: true, kind: 'logout', phase: 'transitioning' });
        }, 400);
      }
      const result = await requestServerLogout();
      if (!result.success) {
        window.clearTimeout(transitioningTimer);
        setSessionTransition({ active: true, kind: 'logout', phase: 'restore' });
        await wait(reducedMotion ? 0 : 200);
        setSessionTransition(IDLE_TRANSITION);
        setAuthNotice({ type: 'error', message: result.error });
        return result;
      }

      const elapsed = performance.now() - startedAt;
      await wait(reducedMotion ? 0 : Math.max(0, 900 - elapsed));
      await clearLocalSession();
      setSessionTransition({ active: true, kind: 'logout', phase: 'logged-out' });
      await showLoginView?.();
      await wait(reducedMotion ? 0 : 200);
      setSessionTransition(IDLE_TRANSITION);
      return { success: true };
    } finally {
      window.clearTimeout(transitioningTimer);
      logoutTransitionActiveRef.current = false;
      transitionLockRef.current = false;
    }
  }, [clearLocalSession, requestServerLogout]);

  useEffect(() => {
    if (!authNotice) return undefined;
    const timeout = window.setTimeout(() => setAuthNotice(null), 6000);
    return () => window.clearTimeout(timeout);
  }, [authNotice]);

  const refreshUserData = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_URL}/auth/me`);
      if (!data) return null;
      if (data.web_login_enabled === 0 && data.role !== 'super_admin') {
        await logout();
        return null;
      }
      setUser((previous) => {
        const next = withoutToken({
          ...(previous || {}), username: data.username, role: data.role,
          vendor_id: data.vendor_id, company_id: data.company_id, frontend_bundle_id: data.frontend_bundle_id,
          backend_service_id: data.backend_service_id, vendor_config: data.vendor_config,
          features: data.features || [], vertical: data.vertical,
          web_login_enabled: data.web_login_enabled, person_id: data.person_id,
          id: data.username,
        });
        localStorage.setItem('user', JSON.stringify(next));
        return next;
      });
      return data;
    } catch (error) {
      if (error.response?.status !== 401) console.error('Refresh user data failed:', error);
      return null;
    }
  }, [logout]);

  useEffect(() => {
    let cancelled = false;
    delete axios.defaults.headers.common['ngrok-skip-browser-warning'];
    delete axios.defaults.headers.common.Authorization;

    const interceptor = axios.interceptors.response.use(
      (response) => response,
      (error) => {
        const status = error.response?.status;
        const message = error.response?.data?.error || '';
        const suspended = message.includes('Subscription Expired') ||
          message.includes('Account Suspended') || message.includes('Service Suspended');
        const featureMissing = message.includes('Feature') && message.includes('not enabled');
        if (isSessionUnauthorized(error) && logoutTransitionActiveRef.current) {
          // The explicit logout flow already revoked the server session and is
          // intentionally holding the covered application until its 900 ms mark.
        } else if (isSessionUnauthorized(error)) {
          // The backend has already rejected this session. Clear the local view
          // without sending another logout request, then leave protected routes.
          void logout({ serverAlreadyRevoked: true }).finally(() => {
            if (window.location.pathname !== '/login') window.location.assign('/login');
          });
        } else if (status === 403 && suspended) {
          void logout().then((result) => {
            if (result.success && window.location.pathname !== '/login') window.location.assign('/login');
          });
        } else if (status === 403 && featureMissing) {
          refreshUserData().catch(() => {});
        }
        return Promise.reject(error);
      },
    );

    const initializeSession = async () => {
      let shouldVerifySession = false;
      try {
        const storedUser = localStorage.getItem('user');
        if (storedUser) {
          const safeUser = withoutToken(JSON.parse(storedUser));
          setUser(safeUser);
          localStorage.setItem('user', JSON.stringify(safeUser));
          shouldVerifySession = true;
        }
        const storedStaff = localStorage.getItem('staffSession');
        if (storedStaff) {
          const parsedStaff = JSON.parse(storedStaff);
          if (parsedStaff?.access_token) {
            setStaffSession(parsedStaff);
            applyStaffSession(parsedStaff);
          } else {
            localStorage.removeItem('staffSession');
            applyStaffSession(null);
          }
        }
      } catch {
        localStorage.removeItem('user');
        localStorage.removeItem('staffSession');
        applyStaffSession(null);
      }

      // Do not render protected pages from localStorage until the httpOnly
      // session cookie has been accepted by the backend. Otherwise a refresh
      // briefly renders stale people data, fires unauthenticated image loads,
      // and redirects only after a later API request returns 401.
      if (shouldVerifySession) {
        await refreshUserData().catch(() => null);
      }
      if (!cancelled) setLoading(false);
    };

    initializeSession();
    return () => {
      cancelled = true;
      axios.interceptors.response.eject(interceptor);
    };
  }, [logout, refreshUserData]);

  // Subscription features can be changed by SuperAdmin while this session is
  // already open. Refresh when the operator returns to the tab so navigation
  // updates even if a Socket.IO feature event was missed during deployment or
  // a temporary disconnect.
  useEffect(() => {
    if (!user) return undefined;
    const refreshOnFocus = () => refreshUserData().catch(() => {});
    const refreshOnVisible = () => {
      if (document.visibilityState === 'visible') refreshOnFocus();
    };
    window.addEventListener('focus', refreshOnFocus);
    document.addEventListener('visibilitychange', refreshOnVisible);
    return () => {
      window.removeEventListener('focus', refreshOnFocus);
      document.removeEventListener('visibilitychange', refreshOnVisible);
    };
  }, [Boolean(user), refreshUserData]);

  useEffect(() => {
    if (!user || !staffSession?.access_token) return undefined;
    let cancelled = false;
    const refreshStaffSession = async () => {
      try {
        const { data } = await axios.get(`${API_URL}/leave/admin/staff-session`, {
          headers: { 'X-Leave-Staff-Token': staffSession.access_token },
        });
        if (cancelled || !data?.staff) return;
        setStaffSession(previous => {
          if (!previous?.access_token) return previous;
          const next = { ...previous, ...data.staff, access_token: previous.access_token };
          localStorage.setItem('staffSession', JSON.stringify(next));
          applyStaffSession(next);
          return next;
        });
      } catch (error) {
        if (cancelled) return;
        if (error.response?.status === 403) {
          setStaffSession(null);
          localStorage.removeItem('staffSession');
          applyStaffSession(null);
        }
      }
    };
    refreshStaffSession();
    const refreshOnFocus = () => refreshStaffSession();
    window.addEventListener('focus', refreshOnFocus);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', refreshOnFocus);
    };
  }, [Boolean(user), staffSession?.access_token]);

  const login = async (username, password) => {
    try {
      let deviceId = localStorage.getItem('web_device_id');
      if (!deviceId) {
        deviceId = `web-${crypto.randomUUID()}`;
        localStorage.setItem('web_device_id', deviceId);
      }
      const response = await axios.post(`${API_URL}/auth/login`, {
        username, password, device_id: deviceId, platform: 'web',
      });
      if (response.data.status !== 'success') {
        return { success: false, error: response.data.error || 'Unexpected response from server' };
      }
      if (response.data.needs_student_password) {
        return {
          success: false,
          error: 'Email and password web login is available to administrators only.',
        };
      }
      const userData = withoutToken({
        id: response.data.username, username: response.data.username, role: response.data.role,
        vendor_id: response.data.vendor_id, company_id: response.data.company_id,
        frontend_bundle_id: response.data.frontend_bundle_id,
        backend_service_id: response.data.backend_service_id,
        vendor_config: response.data.vendor_config, features: response.data.features || [],
        vertical: response.data.vertical, person_id: response.data.person_id,
      });
      setEntryTransitionPending(true);
      setUser(userData);
      localStorage.setItem('user', JSON.stringify(userData));
      setStaffSession(null);
      localStorage.removeItem('staffSession');
      applyStaffSession(null);
      return {
        success: true, role: userData.role, vertical: userData.vertical, person_id: userData.person_id,
        redirect_url: response.data.redirect_url,
        force_password_change: response.data.force_password_change || false,
      };
    } catch (error) {
      return { success: false, error: error.response?.data?.error || error.message || 'Login failed' };
    }
  };

  const googleLogin = async () => {
    try {
      let deviceId = localStorage.getItem('web_device_id');
      if (!deviceId) {
        deviceId = `web-${crypto.randomUUID()}`;
        localStorage.setItem('web_device_id', deviceId);
      }

      const [{ signInWithPopup }, { firebaseAuth, googleAuthProvider }] = await Promise.all([
        import('firebase/auth'),
        import('../lib/firebaseAuth'),
      ]);
      const credential = await signInWithPopup(firebaseAuth, googleAuthProvider);
      const idToken = await credential.user.getIdToken(true);
      const { data } = await axios.post(`${API_URL}/auth/google`, {
        id_token: idToken,
        device_id: deviceId,
      });
      if (data?.status !== 'success') {
        throw new Error(data?.error || 'Google sign-in failed');
      }

      setEntryTransitionPending(true);
      const staff = data.staff_session || null;
      setStaffSession(staff);
      if (staff?.access_token) localStorage.setItem('staffSession', JSON.stringify(staff));
      else localStorage.removeItem('staffSession');
      applyStaffSession(staff);

      const current = await refreshUserData();
      if (!current) throw new Error('Unable to load your TapInX account');
      return {
        success: true,
        role: current.role,
        vertical: current.vertical,
        staff,
        redirect_url: data.redirect_url,
      };
    } catch (error) {
      setEntryTransitionPending(false);
      applyStaffSession(null);
      setStaffSession(null);
      localStorage.removeItem('staffSession');
      signOutFirebase();
      const firebaseCode = String(error?.code || '');
      if (firebaseCode === 'auth/popup-closed-by-user' || firebaseCode === 'auth/cancelled-popup-request') {
        return { success: false, error: 'Google sign-in was cancelled.' };
      }
      if (firebaseCode === 'auth/popup-blocked') {
        return { success: false, error: 'Your browser blocked the Google sign-in window. Allow pop-ups and try again.' };
      }
      return {
        success: false,
        error: error.response?.data?.error || error.message || 'Google sign-in failed',
      };
    }
  };

  const loginAsStaff = async (pin) => {
    if (!user?.vendor_id) return { success: false, error: 'Not logged in' };
    try {
      const { data } = await axios.post(`${API_URL}/leave/admin/verify-pin`, { vendor_id: user.vendor_id, pin });
      if (data.status === 'success') {
        setStaffSession(data.staff);
        localStorage.setItem('staffSession', JSON.stringify(data.staff));
        applyStaffSession(data.staff);
        return { success: true, staff: data.staff };
      }
      return { success: false, error: 'Invalid PIN' };
    } catch (error) {
      return { success: false, error: error.response?.data?.error || 'Verification failed' };
    }
  };

  const logoutStaff = () => {
    setStaffSession(null);
    localStorage.removeItem('staffSession');
    applyStaffSession(null);
  };

  return (
    <AuthContext.Provider value={{
      user, staffSession, login, googleLogin, logout, loginAsStaff, logoutStaff,
      loading, refreshFeatures: refreshUserData, refreshUserData,
      entryTransitionPending, sessionTransition,
      isAuthTransitioning: sessionTransition.active,
      completeLoginTransition, logoutWithTransition, authNotice, setAuthNotice,
    }}>
      {loading
        ? <PageLoader fullScreen label="Opening TapInX" description="Restoring your secure workspace…" />
        : children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
