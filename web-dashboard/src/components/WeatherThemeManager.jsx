import { useCallback, useEffect, useRef } from 'react';
import axios from 'axios';

import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';
import { useSocket } from '../context/SocketContext';


const REFRESH_INTERVAL_MS = 15 * 60 * 1000;
const ALLOWED_THEMES = new Set(['summer', 'rainy', 'winter', 'autumn', 'snow']);

const clearWeatherTheme = () => {
  const root = document.documentElement;
  root.removeAttribute('data-weather-theme');
  root.removeAttribute('data-weather-is-day');
  root.removeAttribute('data-weather-condition');
};

const applyWeatherTheme = (data) => {
  if (!data?.enabled || !data?.available || !ALLOWED_THEMES.has(data?.theme)) {
    clearWeatherTheme();
    return;
  }
  const root = document.documentElement;
  root.setAttribute('data-weather-theme', data.theme);
  root.setAttribute('data-weather-is-day', data.is_day ? 'true' : 'false');
  root.setAttribute('data-weather-condition', String(data.condition || 'Seasonal condition').slice(0, 80));
};

const getBrowserCoordinates = () => new Promise((resolve) => {
  if (!navigator.geolocation) {
    resolve(null);
    return;
  }
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => resolve({
      latitude: Number(coords.latitude.toFixed(4)),
      longitude: Number(coords.longitude.toFixed(4)),
    }),
    () => resolve(null),
    { enableHighAccuracy: false, maximumAge: REFRESH_INTERVAL_MS, timeout: 5000 },
  );
});

const WeatherThemeManager = () => {
  const { user } = useAuth();
  const { socket } = useSocket();
  const requestInFlight = useRef(false);
  const mounted = useRef(true);
  const globallyEnabled = useRef(null);

  const refreshTheme = useCallback(async (forcedEnabled) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    try {
      let enabled = forcedEnabled;
      if (typeof enabled !== 'boolean') {
        const { data } = await axios.get(`${API_URL}/public/weather-theme/config`);
        enabled = Boolean(data?.enabled);
      }
      globallyEnabled.current = enabled;
      if (!mounted.current) return;
      if (!enabled || !user) {
        clearWeatherTheme();
        return;
      }

      const coordinates = await getBrowserCoordinates();
      if (!mounted.current) return;
      const { data } = await axios.post(`${API_URL}/weather-theme/current`, coordinates || {});
      if (mounted.current && globallyEnabled.current !== false) applyWeatherTheme(data);
    } catch {
      // Decorative weather must never interrupt navigation or core workflows.
      if (mounted.current) clearWeatherTheme();
    } finally {
      requestInFlight.current = false;
    }
  }, [user]);

  useEffect(() => {
    mounted.current = true;
    refreshTheme();
    const interval = window.setInterval(() => refreshTheme(), REFRESH_INTERVAL_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') refreshTheme();
    };
    const onSettingChange = (event) => {
      const enabled = Boolean(event?.detail?.enabled ?? event?.enabled);
      globallyEnabled.current = enabled;
      if (!enabled) clearWeatherTheme();
      window.setTimeout(() => refreshTheme(enabled), 50);
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('tapinx:weather-theme-setting', onSettingChange);
    socket?.on('weather_theme_setting_updated', onSettingChange);
    return () => {
      mounted.current = false;
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('tapinx:weather-theme-setting', onSettingChange);
      socket?.off('weather_theme_setting_updated', onSettingChange);
      clearWeatherTheme();
    };
  }, [refreshTheme, socket]);

  return (
    <div className="weather-atmosphere" aria-hidden="true">
      <span className="weather-atmosphere__sky" />
      <span className="weather-atmosphere__orb" />
      <span className="weather-atmosphere__particles" />
      <span className="weather-atmosphere__foreground" />
    </div>
  );
};

export default WeatherThemeManager;

