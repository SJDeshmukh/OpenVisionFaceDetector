import { useEffect } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import BrandLogo from './BrandLogo';

const SessionTransitionLayer = () => {
  const { sessionTransition, authNotice, setAuthNotice } = useAuth();
  const { active, kind, phase } = sessionTransition;

  useEffect(() => {
    const root = document.documentElement;
    if (!active) {
      root.removeAttribute('data-session-transition');
      document.body.removeAttribute('aria-busy');
      return undefined;
    }

    root.setAttribute('data-session-transition', `${kind}-${phase}`);
    document.body.setAttribute('aria-busy', 'true');
    const blockKeyboardInteraction = (event) => {
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener('keydown', blockKeyboardInteraction, true);
    return () => {
      root.removeAttribute('data-session-transition');
      document.body.removeAttribute('aria-busy');
      window.removeEventListener('keydown', blockKeyboardInteraction, true);
    };
  }, [active, kind, phase]);

  return (
    <>
      {active && (
        <div
          className={`session-transition-layer session-transition--${kind} phase-${phase}`}
          role="status"
          aria-live="polite"
          aria-label={kind === 'login' ? 'Opening TapInX' : 'Signing out of TapInX'}
        >
          <div className="session-transition__ambient" aria-hidden="true" />
          <div className="session-transition__wave" aria-hidden="true" />
          <div className="session-transition__rim" aria-hidden="true" />
          <div className="session-transition__brand" aria-hidden="true">
            <span className="session-transition__logo"><BrandLogo /></span>
            <span>{kind === 'login' ? 'Opening your workspace' : 'Closing your workspace'}</span>
          </div>
        </div>
      )}

      {authNotice?.message && (
        <div className="auth-session-notice" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{authNotice.message}</span>
          <button type="button" onClick={() => setAuthNotice(null)} aria-label="Dismiss sign-out error">
            <X size={16} />
          </button>
        </div>
      )}
    </>
  );
};

export default SessionTransitionLayer;
