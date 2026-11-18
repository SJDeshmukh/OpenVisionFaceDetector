const PageLoader = ({
  label = 'Loading your workspace',
  description = 'Synchronizing the latest TapInX data…',
  compact = false,
  fullScreen = false,
}) => (
  <div
    className={`tapinx-page-loader ${compact ? 'is-compact' : ''} ${fullScreen ? 'is-fullscreen' : ''}`}
    role="status"
    aria-live="polite"
    aria-label={label}
  >
    <div className="container_SevMini" aria-hidden="true">
      <div className="SevMini">
        <svg viewBox="0 0 160 145" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="tapinx-loader-top" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#A78BFA" />
              <stop offset="1" stopColor="#7C3AFF" />
            </linearGradient>
            <linearGradient id="tapinx-loader-front" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#6D28D9" />
              <stop offset="1" stopColor="#3B168A" />
            </linearGradient>
            <linearGradient id="tapinx-loader-side" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#39DDCD" />
              <stop offset="1" stopColor="#087F87" />
            </linearGradient>
          </defs>

          <g className="server-layer server-layer--bottom">
            <path d="M80 76L132 101L80 126L28 101L80 76Z" fill="url(#tapinx-loader-top)" />
            <path d="M28 101L80 126V143L28 118V101Z" fill="url(#tapinx-loader-front)" />
            <path d="M80 126L132 101V118L80 143V126Z" fill="url(#tapinx-loader-side)" />
            <circle className="strobe-color strobe-color--green" cx="44" cy="112" r="3.4" />
            <path d="M54 116L70 124" stroke="#CABFFD" strokeWidth="3" strokeLinecap="round" />
          </g>
          <g className="server-layer server-layer--middle">
            <path d="M80 48L132 73L80 98L28 73L80 48Z" fill="url(#tapinx-loader-top)" />
            <path d="M28 73L80 98V115L28 90V73Z" fill="url(#tapinx-loader-front)" />
            <path d="M80 98L132 73V90L80 115V98Z" fill="url(#tapinx-loader-side)" />
            <circle className="strobe-color strobe-color--blue" cx="44" cy="84" r="3.4" />
            <path d="M54 88L70 96" stroke="#CABFFD" strokeWidth="3" strokeLinecap="round" />
          </g>
          <g className="server-layer server-layer--top">
            <path d="M80 20L132 45L80 70L28 45L80 20Z" fill="url(#tapinx-loader-top)" />
            <path d="M28 45L80 70V87L28 62V45Z" fill="url(#tapinx-loader-front)" />
            <path d="M80 70L132 45V62L80 87V70Z" fill="url(#tapinx-loader-side)" />
            <circle className="strobe-led" cx="44" cy="56" r="3.4" fill="#FFFFFF" />
            <path d="M54 60L70 68" stroke="#CABFFD" strokeWidth="3" strokeLinecap="round" />
          </g>
        </svg>
      </div>
      <span className="Ghost" />
    </div>

    <div className="tapinx-page-loader__copy">
      <strong>{label}</strong>
      {!compact && <span>{description}</span>}
    </div>
    <span className="sr-only">Please wait.</span>
  </div>
);

export default PageLoader;
