import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  Activity, AlertTriangle, Bell, CalendarClock, CheckCheck,
  CircleDollarSign, Loader2, RefreshCw, ShieldCheck,
} from 'lucide-react';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';

const iconForCategory = (category) => {
  switch (category) {
    case 'leave': return CalendarClock;
    case 'advance': return CircleDollarSign;
    case 'security': return ShieldCheck;
    case 'warning': return AlertTriangle;
    default: return Activity;
  }
};

const relativeTime = (raw) => {
  if (!raw) return '';
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return '';
  const seconds = Math.round((parsed.getTime() - Date.now()) / 1000);
  const absolute = Math.abs(seconds);
  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  if (absolute < 60) return formatter.format(seconds, 'second');
  if (absolute < 3600) return formatter.format(Math.round(seconds / 60), 'minute');
  if (absolute < 86400) return formatter.format(Math.round(seconds / 3600), 'hour');
  if (absolute < 604800) return formatter.format(Math.round(seconds / 86400), 'day');
  return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
};

const NotificationCenter = () => {
  const { user, staffSession } = useAuth();
  const navigate = useNavigate();
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const identityKey = `${user?.role || ''}:${user?.username || ''}:${staffSession?.id || ''}`;
  const unreadCount = useMemo(() => items.filter(item => !item.read).length, [items]);

  const loadNotifications = useCallback(async ({ quiet = false } = {}) => {
    if (!user) return;
    if (!quiet) setLoading(true);
    try {
      const { data } = await axios.get(`${API_URL}/notifications`, { params: { limit: 40 } });
      setItems(Array.isArray(data?.items) ? data.items : []);
      setError('');
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'Unable to load notifications');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    setItems([]);
    setLoading(true);
    loadNotifications();
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') loadNotifications({ quiet: true });
    }, 60000);
    const refreshOnFocus = () => loadNotifications({ quiet: true });
    window.addEventListener('focus', refreshOnFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', refreshOnFocus);
    };
  }, [identityKey, loadNotifications]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = event => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const closeWithEscape = event => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', closeWithEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('keydown', closeWithEscape);
    };
  }, [open]);

  const markRead = async (keys) => {
    const uniqueKeys = [...new Set(keys.filter(Boolean))];
    if (!uniqueKeys.length) return;
    setItems(current => current.map(item => uniqueKeys.includes(item.key) ? { ...item, read: true } : item));
    try {
      await axios.post(`${API_URL}/notifications/read`, { keys: uniqueKeys });
    } catch {
      loadNotifications({ quiet: true });
    }
  };

  const openNotification = item => {
    if (!item.read) markRead([item.key]);
    setOpen(false);
    if (typeof item.href === 'string' && item.href.startsWith('/')) navigate(item.href);
  };

  return (
    <div className="notification-center" ref={rootRef}>
      <button
        type="button"
        className="notification-trigger"
        onClick={() => setOpen(value => !value)}
        aria-label={unreadCount ? `Notifications, ${unreadCount} unread` : 'Notifications'}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="notification-trigger__badge" aria-hidden="true">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <section className="notification-panel" role="dialog" aria-label="Notifications">
          <header className="notification-panel__header">
            <div>
              <span className="notification-panel__eyebrow">YOUR UPDATES</span>
              <h2>Notifications</h2>
            </div>
            {unreadCount > 0 && (
              <button type="button" onClick={() => markRead(items.filter(item => !item.read).map(item => item.key))}>
                <CheckCheck size={15} /> Mark all read
              </button>
            )}
          </header>

          <div className="notification-panel__body">
            {loading ? (
              <div className="notification-panel__state">
                <Loader2 className="animate-spin" size={22} />
                <span>Loading updates…</span>
              </div>
            ) : error ? (
              <div className="notification-panel__state is-error">
                <AlertTriangle size={22} />
                <span>{error}</span>
                <button type="button" onClick={() => loadNotifications()}><RefreshCw size={14} /> Retry</button>
              </div>
            ) : items.length === 0 ? (
              <div className="notification-panel__state">
                <CheckCheck size={24} />
                <strong>You’re all caught up</strong>
                <span>No action or status updates for this login.</span>
              </div>
            ) : (
              <div className="notification-list">
                {items.map(item => {
                  const Icon = iconForCategory(item.category);
                  return (
                    <button
                      type="button"
                      className={`notification-item ${item.read ? 'is-read' : 'is-unread'}`}
                      key={item.key}
                      onClick={() => openNotification(item)}
                    >
                      <span className={`notification-item__icon is-${item.category || 'system'}`}><Icon size={17} /></span>
                      <span className="notification-item__content">
                        <span className="notification-item__title">{item.title}</span>
                        <span className="notification-item__message">{item.message}</span>
                        <span className="notification-item__time">{relativeTime(item.created_at)}</span>
                      </span>
                      {!item.read && <span className="notification-item__unread" aria-label="Unread" />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
};

export default NotificationCenter;
