import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ShieldCheck,
  Lock,
  Camera,
  MapPin,
  Clock,
  UserCheck,
  Building2,
  FileText,
  AlertTriangle,
  HelpCircle,
  ArrowLeft,
  ChevronRight,
  CheckCircle2,
  Cpu,
  Trash2,
  Share2,
  ShieldAlert,
  Users,
  Cookie,
  Globe,
  RefreshCw,
  Mail,
  Zap,
  Info
} from 'lucide-react';

const SECTIONS = [
  { id: 'section-1', title: '1. Company & Application Info' },
  { id: 'section-2', title: '2. Information We Collect' },
  { id: 'section-3', title: '3. Biometric & Facial Data' },
  { id: 'section-4', title: '4. Camera Permission' },
  { id: 'section-5', title: '5. Location & Geofencing' },
  { id: 'section-6', title: '6. How We Use Information' },
  { id: 'section-7', title: '7. Data Storage & Security' },
  { id: 'section-8', title: '8. Data Sharing & Third Parties' },
  { id: 'section-9', title: '9. Data Retention & Deletion' },
  { id: 'section-10', title: '10. User Rights & Consent' },
  { id: 'section-11', title: '11. Children & Student Privacy' },
  { id: 'section-12', title: '12. Cookies & Web Tracking' },
  { id: 'section-13', title: '13. International Transfers' },
  { id: 'section-14', title: '14. Policy Updates' },
  { id: 'section-15', title: '15. Contact & Privacy Redressal' },
];

export default function PrivacyPolicy() {
  const [activeSection, setActiveSection] = useState('section-1');

  // Enforce light theme on document element while this public policy page is mounted
  useEffect(() => {
    const prevTheme = document.documentElement.getAttribute('data-theme');
    document.documentElement.setAttribute('data-theme', 'light');

    const handleScroll = () => {
      const scrollPos = window.scrollY + 200;
      for (let i = SECTIONS.length - 1; i >= 0; i--) {
        const el = document.getElementById(SECTIONS[i].id);
        if (el && el.offsetTop <= scrollPos) {
          setActiveSection(SECTIONS[i].id);
          break;
        }
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', handleScroll);
      if (prevTheme) {
        document.documentElement.setAttribute('data-theme', prevTheme);
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
    };
  }, []);

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (el) {
      const offset = 90;
      const bodyRect = document.body.getBoundingClientRect().top;
      const elementRect = el.getBoundingClientRect().top;
      const elementPosition = elementRect - bodyRect;
      const offsetPosition = elementPosition - offset;

      window.scrollTo({
        top: offsetPosition,
        behavior: 'smooth'
      });
      setActiveSection(id);
    }
  };

  return (
    <div
      className="min-h-screen text-slate-800 antialiased selection:bg-violet-100 selection:text-violet-900"
      style={{
        backgroundColor: '#F8FAFC',
        color: '#0F172A',
        fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif"
      }}
    >
      {/* ─── Top Navigation Bar with TapInX & OpenVisionX Branding ─── */}
      <header className="sticky top-0 z-50 border-b border-slate-200/90 bg-white/95 backdrop-blur-md shadow-xs">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 h-18 flex items-center justify-between gap-4">
          
          {/* Left: TapInX Brand + Center Tag */}
          <div className="flex items-center gap-3.5">
            <Link to="/login" className="flex items-center gap-3 group">
              <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-violet-600 via-indigo-600 to-purple-700 p-0.5 shadow-sm shadow-violet-500/20 group-hover:scale-105 transition-transform flex items-center justify-center">
                <div className="h-full w-full bg-white rounded-[10px] flex items-center justify-center p-1">
                  <img src="/tapinx-logo.svg" alt="TapInX Logo" className="h-7 w-7 object-contain" />
                </div>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xl font-black text-slate-900 tracking-tight">TapInX</span>
                  <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold bg-violet-50 text-violet-700 border border-violet-200">
                    Privacy Center
                  </span>
                </div>
                <p className="text-[10px] font-semibold text-slate-400 tracking-wider uppercase">
                  Biometric Attendance &amp; Workforce OS
                </p>
              </div>
            </Link>
          </div>

          {/* Right: OpenVisionX Logo + Back to Login */}
          <div className="flex items-center gap-4 sm:gap-6">
            {/* OpenVisionX Branding Pill */}
            <div className="hidden md:flex items-center gap-2.5 px-3.5 py-1.5 rounded-xl bg-slate-50 border border-slate-200/90 shadow-2xs">
              <div className="text-right">
                <p className="text-[9px] font-bold text-slate-400 uppercase tracking-widest leading-none mb-0.5">Powered By</p>
                <p className="text-xs font-black text-slate-800 tracking-tight leading-none">OpenVisionX</p>
              </div>
              <div className="w-7 h-7 bg-white rounded-lg flex items-center justify-center p-1 border border-slate-100 shadow-2xs">
                <img src="/openVisionXLogo.png" alt="OpenVisionX" className="w-full h-full object-contain" />
              </div>
            </div>

            <Link
              to="/login"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-slate-700 bg-white border border-slate-200 shadow-2xs hover:bg-slate-50 hover:text-violet-700 hover:border-violet-200 transition-all active:scale-95"
            >
              <ArrowLeft size={14} />
              <span>Back to Login</span>
            </Link>
          </div>
        </div>
      </header>

      {/* ─── Hero Section with Light Shades & Brand Gradient ─── */}
      <section className="relative overflow-hidden border-b border-slate-200/80 bg-gradient-to-b from-white via-violet-50/30 to-slate-50 py-12 sm:py-16">
        {/* Soft atmospheric gradient accents */}
        <div className="absolute -top-32 left-1/2 -translate-x-1/2 w-[800px] h-[340px] bg-gradient-to-r from-violet-200/35 via-indigo-200/30 to-sky-200/30 blur-3xl rounded-full pointer-events-none" />
        <div className="absolute top-10 right-10 w-72 h-72 bg-pink-100/30 blur-2xl rounded-full pointer-events-none" />

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          {/* Trust Center Badge */}
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white border border-violet-200 text-violet-700 text-xs font-semibold shadow-xs mb-4">
            <ShieldCheck size={15} className="text-violet-600" />
            <span>OpenVisionX Technologies &bull; Official TapInX Privacy &amp; Trust Center</span>
          </div>

          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-black text-slate-900 tracking-tight leading-tight">
            TapInX Privacy Policy
          </h1>

          <p className="mx-auto mt-4 max-w-2xl text-sm sm:text-base text-slate-600 leading-relaxed font-normal">
            Your privacy, biometric security, and trust are our highest priorities. Learn how TapInX collects, processes, encrypts, and protects your personal, camera, location, and attendance data under Indian DPDP Act 2023 and Google Play Store standards.
          </p>

          {/* Compliance & Meta Pills */}
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2 sm:gap-3 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 font-medium text-slate-700 border border-slate-200 shadow-2xs">
              <Clock size={13} className="text-slate-400" />
              Effective: <strong>November 15, 2026</strong>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 font-medium text-slate-700 border border-slate-200 shadow-2xs">
              <RefreshCw size={13} className="text-slate-400" />
              Last Updated: <strong>November 15, 2026</strong>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-1.5 font-bold text-emerald-700 border border-emerald-200 shadow-2xs">
              <CheckCircle2 size={13} className="text-emerald-600" />
              DPDP Act 2023 &amp; Google Play Aligned
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-violet-50 px-3 py-1.5 font-bold text-violet-700 border border-violet-200 shadow-2xs">
              <Zap size={13} className="text-violet-600" />
              Zero Advertising Guarantee
            </span>
          </div>
        </div>
      </section>

      {/* ─── Main Content Container (2-Column Layout) ─── */}
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          
          {/* ── Left Sidebar (Table of Contents) ── */}
          <aside className="lg:col-span-4 xl:col-span-3 sticky top-24 z-10">
            <div className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xs">
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  Contents
                </span>
                <span className="text-[11px] font-semibold text-violet-600 bg-violet-50 px-2 py-0.5 rounded-md">
                  15 Sections
                </span>
              </div>
              <nav className="mt-3 space-y-1 max-h-[calc(100vh-220px)] overflow-y-auto pr-1">
                {SECTIONS.map((sec) => {
                  const isActive = activeSection === sec.id;
                  return (
                    <button
                      key={sec.id}
                      onClick={() => scrollTo(sec.id)}
                      className={`w-full text-left text-xs font-medium px-3 py-2 rounded-xl transition-all flex items-center justify-between group ${
                        isActive
                          ? 'bg-violet-600 text-white font-semibold shadow-xs'
                          : 'text-slate-600 hover:text-violet-700 hover:bg-violet-50/70'
                      }`}
                    >
                      <span className="truncate pr-2">{sec.title}</span>
                      <ChevronRight
                        size={13}
                        className={`transition-transform flex-shrink-0 ${
                          isActive
                            ? 'text-white translate-x-0.5'
                            : 'text-slate-300 group-hover:text-violet-500 group-hover:translate-x-0.5'
                        }`}
                      />
                    </button>
                  );
                })}
              </nav>

              {/* Sidebar Help Card */}
              <div className="mt-4 pt-3 border-t border-slate-100 text-center">
                <div className="rounded-xl bg-slate-50 p-3 border border-slate-100 text-left">
                  <p className="text-[11px] font-bold text-slate-800">Need Privacy Support?</p>
                  <p className="text-[10px] text-slate-500 mt-0.5 leading-snug">
                    Contact our Privacy and Support Team:
                  </p>
                  <a
                    href="mailto:support@tapinx.in"
                    className="inline-flex items-center gap-1 text-[11px] font-bold text-violet-700 hover:text-violet-900 hover:underline mt-2"
                  >
                    <Mail size={12} />
                    support@tapinx.in
                  </a>
                </div>
              </div>
            </div>
          </aside>

          {/* ── Right Content Area ── */}
          <main className="lg:col-span-8 xl:col-span-9 space-y-8">
            
            {/* ── Key Commitments at a Glance Card ── */}
            <div className="rounded-2xl border border-violet-200/90 bg-gradient-to-br from-violet-50/60 via-white to-indigo-50/40 p-6 shadow-xs">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-violet-600 text-white flex items-center justify-center shadow-xs">
                  <ShieldCheck size={18} />
                </div>
                <div>
                  <h2 className="text-base font-bold text-slate-900">
                    Key Privacy Commitments at a Glance
                  </h2>
                  <p className="text-xs text-slate-500">
                    Built-in safeguards protecting employee and student privacy by design
                  </p>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                {/* 1 */}
                <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
                  <div className="flex items-center gap-2 text-violet-700 font-bold text-xs mb-1.5">
                    <ShieldAlert size={15} />
                    <span>Zero Advertising Guarantee</span>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    We never sell, rent, monetize, or disclose your personal or biometric information to commercial third parties or ad networks.
                  </p>
                </div>

                {/* 2 */}
                <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
                  <div className="flex items-center gap-2 text-indigo-700 font-bold text-xs mb-1.5">
                    <Cpu size={15} />
                    <span>Edge Biometric Processing</span>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    Facial recognition operates via mathematical embeddings on authorized devices, backed by real-time anti-spoofing verification.
                  </p>
                </div>

                {/* 3 */}
                <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
                  <div className="flex items-center gap-2 text-amber-700 font-bold text-xs mb-1.5">
                    <MapPin size={15} />
                    <span>Strict Geofencing Only</span>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    GPS coordinates are captured strictly at the instant of attendance punch to validate workplace boundaries. No background tracking.
                  </p>
                </div>

                {/* 4 */}
                <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
                  <div className="flex items-center gap-2 text-emerald-700 font-bold text-xs mb-1.5">
                    <Trash2 size={15} />
                    <span>Right to Erasure &amp; Purge</span>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    Subscribing organizations and members can request permanent deletion of biometric templates and logs from devices and cloud at any time.
                  </p>
                </div>
              </div>
            </div>

            {/* ── Section 1: Company and Application Information ── */}
            <section
              id="section-1"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Building2 size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    1. Company and Application Information
                  </h2>
                  <p className="text-xs text-slate-400">Developer identity, application scope, and legal entity</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  This Privacy Policy describes the policies and procedures of <strong>OpenVisionX Technologies</strong> (&ldquo;Company&rdquo;, &ldquo;we&rdquo;, &ldquo;our&rdquo;, or &ldquo;us&rdquo;) regarding the collection, use, processing, storage, and disclosure of personal, camera, location, and biometric information when you access or use:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li>The <strong>TapInX Android mobile applications</strong> (kiosk mode, employee client, faculty, and parent modules).</li>
                  <li>The <strong>TapInX Web Portal and Admin Dashboard</strong> (hosted at <a href="https://tapinx.in" className="text-violet-600 font-semibold underline">https://tapinx.in</a>).</li>
                  <li>Our cloud synchronization backend and associated Application Programming Interfaces (APIs).</li>
                </ul>

                <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 text-xs space-y-2 mt-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div><span className="font-bold text-slate-700">Developer &amp; Legal Entity:</span> OpenVisionX Technologies</div>
                    <div><span className="font-bold text-slate-700">Product Name:</span> TapInX</div>
                    <div><span className="font-bold text-slate-700">Official Website:</span> <a href="https://tapinx.in" className="text-violet-600 underline">https://tapinx.in</a></div>
                    <div><span className="font-bold text-slate-700">Support Email:</span> <a href="mailto:support@tapinx.in" className="text-violet-600 underline">support@tapinx.in</a></div>
                    <div><span className="font-bold text-slate-700">Jurisdiction:</span> India (DPDP Act, 2023 Compliant)</div>
                    <div><span className="font-bold text-slate-700">Registered Office:</span> Pune, Maharashtra, India</div>
                  </div>
                </div>
              </div>
            </section>

            {/* ── Section 2: Information We Collect ── */}
            <section
              id="section-2"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <FileText size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    2. Information We Collect
                  </h2>
                  <p className="text-xs text-slate-400">Detailed disclosure of collected data categories and operational purpose</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  To provide secure identity verification, attendance tracking, and workforce management, TapInX collects only the information strictly necessary for legitimate enterprise and institutional purposes:
                </p>

                {/* Data Table */}
                <div className="overflow-x-auto rounded-xl border border-slate-200">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-100/80 text-slate-700 font-bold border-b border-slate-200">
                      <tr>
                        <th className="py-2.5 px-3">Data Category</th>
                        <th className="py-2.5 px-3">Information Collected</th>
                        <th className="py-2.5 px-3">Purpose &amp; Processing</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200 bg-white text-slate-700">
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Personal Information</td>
                        <td className="py-2.5 px-3">Full name, Employee ID / Roll Number, phone number, email address</td>
                        <td className="py-2.5 px-3">Roster enrollment, profile association, and identity management</td>
                      </tr>
                      <tr className="bg-violet-50/40">
                        <td className="py-2.5 px-3 font-semibold text-violet-950">Biometric Information</td>
                        <td className="py-2.5 px-3 font-medium text-violet-900">Facial reference images, encrypted mathematical facial embeddings</td>
                        <td className="py-2.5 px-3 text-violet-900">1:N &amp; 1:1 facial recognition, proxy prevention, anti-spoofing</td>
                      </tr>
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Camera Data</td>
                        <td className="py-2.5 px-3">Live face images captured during registration and verification punches</td>
                        <td className="py-2.5 px-3">Edge template extraction and visual audit verification</td>
                      </tr>
                      <tr className="bg-violet-50/40">
                        <td className="py-2.5 px-3 font-semibold text-violet-950">Location Data</td>
                        <td className="py-2.5 px-3 font-medium text-violet-900">Precise GPS coordinates (latitude, longitude) at the moment of punch</td>
                        <td className="py-2.5 px-3 text-violet-900">Validating punch against authorized workplace or campus geofences</td>
                      </tr>
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Attendance Data</td>
                        <td className="py-2.5 px-3">Check-in / check-out timestamps, operational date, shift ID, status</td>
                        <td className="py-2.5 px-3">Workforce attendance records, timesheets, and late arrival reporting</td>
                      </tr>
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Employment / Academic Data</td>
                        <td className="py-2.5 px-3">Department, designation, shift assignment, hostel room/bed assignment</td>
                        <td className="py-2.5 px-3">Shift scheduling, hostel allocation, and organizational workflows</td>
                      </tr>
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Payroll &amp; Wage Data</td>
                        <td className="py-2.5 px-3">Calculated hours worked, overtime, daily wage tier, authorized advances</td>
                        <td className="py-2.5 px-3">Automated wage and payout computation for subscribing employers</td>
                      </tr>
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Device &amp; Technical Info</td>
                        <td className="py-2.5 px-3">Device model, hardware identifier, Android OS version, app version, IP</td>
                        <td className="py-2.5 px-3">Device kiosk binding, diagnostic analytics, security fraud prevention</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            {/* ── Section 3: Biometric and Facial Recognition Data ── */}
            <section
              id="section-3"
              className="scroll-mt-24 rounded-2xl border border-violet-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-violet-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <UserCheck size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    3. Biometric and Facial Recognition Data
                  </h2>
                  <p className="text-xs text-slate-400">Critical disclosures on biometric AI, processing, and privacy safeguards</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-4">
                <div className="rounded-xl border border-violet-200 bg-violet-50/80 p-4 text-xs font-semibold text-violet-950 flex items-start gap-2.5">
                  <ShieldCheck size={18} className="text-violet-700 flex-shrink-0 mt-0.5" />
                  <span>
                    <strong>Critical Disclosure:</strong> TapInX uses artificial intelligence-based facial recognition technology exclusively to provide secure employee/student attendance verification and prevent proxy attendance. We do not use biometric data for advertising or sell biometric information to third parties.
                  </span>
                </div>
                
                <div>
                  <h3 className="font-bold text-slate-900 text-sm">A. How Facial Recognition Works</h3>
                  <p className="mt-1">
                    During member registration, a front-facing camera photo is captured. Our on-device biometric processing engine analyzes facial geometry and landmarks to compute a secure <strong>mathematical representation (facial embedding)</strong>. These representations are irreversible mathematical summaries used strictly for matching against live camera frames during attendance check-in.
                  </p>
                </div>

                <div>
                  <h3 className="font-bold text-slate-900 text-sm">B. Anti-Spoofing and Liveness Verification</h3>
                  <p className="mt-1">
                    To prevent fraudulent punches using photographs, smartphone displays, or paper cutouts, TapInX performs edge-based passive liveness verification. Live camera frames are analyzed for natural optical characteristics, surface reflections, and micro-motion before validating an identity.
                  </p>
                </div>

                <div>
                  <h3 className="font-bold text-slate-900 text-sm">C. Storage and Synchronization</h3>
                  <p className="mt-1">
                    Biometric embeddings are securely serialized and stored in protected local application storage on authorized kiosk devices. When cloud synchronization is enabled, these mathematical templates and reference photos are synchronized with our secure cloud backend over HTTPS/TLS to enable recognition across authorized devices within the organization.
                  </p>
                </div>

                <div>
                  <h3 className="font-bold text-slate-900 text-sm">D. Access and Deletion</h3>
                  <p className="mt-1">
                    Only authorized administrators of your organization can access member attendance logs. Raw facial embeddings cannot be reverse-engineered to reconstruct the original photograph. When an administrator removes a member, their facial templates and reference images are purged from both local devices and backend storage.
                  </p>
                </div>
              </div>
            </section>

            {/* ── Section 4: Camera Permission ── */}
            <section
              id="section-4"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Camera size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    4. Camera Permission
                  </h2>
                  <p className="text-xs text-slate-400">Android runtime permission and camera usage scope</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  TapInX requests Android runtime access to the device camera (<code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-800 font-mono">android.permission.CAMERA</code>). Camera access is required strictly for:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li>Capturing a clear reference face photo during employee/student enrollment.</li>
                  <li>Scanning faces during live check-in and check-out attendance verification.</li>
                  <li>Real-time anti-spoofing and liveness analysis.</li>
                </ul>
                <div className="rounded-xl bg-amber-50/80 p-3.5 border border-amber-200 text-xs text-amber-950 font-medium flex items-start gap-2">
                  <Info size={16} className="text-amber-700 flex-shrink-0 mt-0.5" />
                  <span>
                    <strong>Important Notice:</strong> Camera access is active only while the camera preview or attendance scanning interface is visible on screen. TapInX does not perform covert, background, or general surveillance video recording.
                  </span>
                </div>
              </div>
            </section>

            {/* ── Section 5: Location Permission and Geofencing ── */}
            <section
              id="section-5"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <MapPin size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    5. Location Permission and Geofencing
                  </h2>
                  <p className="text-xs text-slate-400">Attendance perimeter enforcement without background tracking</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  TapInX requests location permissions (<code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-800 font-mono">ACCESS_FINE_LOCATION</code> and <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-800 font-mono">ACCESS_COARSE_LOCATION</code>) to enforce attendance geofencing:
                </p>
                <ul className="list-disc list-inside space-y-2 pl-2 text-slate-700">
                  <li><strong>Purpose:</strong> Validating that attendance punches originate from authorized workplace, factory, or campus boundaries.</li>
                  <li><strong>Collection Timing:</strong> GPS coordinates are queried <em>strictly at the moment</em> an attendance punch is recorded.</li>
                  <li><strong>No Background Tracking:</strong> TapInX does not monitor, track, or broadcast your location continuously in the background when the app is idle.</li>
                  <li><strong>Audit Logs:</strong> The timestamped coordinates recorded during a punch are visible to authorized organization supervisors for compliance verification.</li>
                </ul>
              </div>
            </section>

            {/* ── Section 6: How We Use Collected Information ── */}
            <section
              id="section-6"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <FileText size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    6. How We Use Collected Information
                  </h2>
                  <p className="text-xs text-slate-400">Authorized business, academic, and operational functions</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>We process collected data solely for the following legitimate business and institutional functions:</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3 text-xs">
                  <div className="p-3.5 bg-slate-50/80 rounded-xl border border-slate-200/90">
                    <strong className="text-slate-900 block mb-1">Identity &amp; Attendance Verification</strong>
                    Accurately logging employee check-ins, check-outs, shift attendance, and lecture attendance without proxy punches.
                  </div>
                  <div className="p-3.5 bg-slate-50/80 rounded-xl border border-slate-200/90">
                    <strong className="text-slate-900 block mb-1">Working Hours &amp; Wage Calculation</strong>
                    Computing daily payable hours, overtime, and salary summaries for business payroll processing.
                  </div>
                  <div className="p-3.5 bg-slate-50/80 rounded-xl border border-slate-200/90">
                    <strong className="text-slate-900 block mb-1">Hostel &amp; Campus Movement</strong>
                    Tracking resident in/out movements, approved leave gate passes, and bed occupancy allocation.
                  </div>
                  <div className="p-3.5 bg-slate-50/80 rounded-xl border border-slate-200/90">
                    <strong className="text-slate-900 block mb-1">Security &amp; Fraud Prevention</strong>
                    Detecting attendance tampering, device spoofing, or unauthorized biometric impersonation attempts.
                  </div>
                </div>
              </div>
            </section>

            {/* ── Section 7: Data Storage and Security ── */}
            <section
              id="section-7"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Lock size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    7. Data Storage and Security
                  </h2>
                  <p className="text-xs text-slate-400">Technical, administrative, and physical encryption safeguards</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We implement multi-layered administrative, technical, and physical safeguards to protect biometric, personal, and location records:
                </p>
                <ul className="list-disc list-inside space-y-2 pl-2 text-slate-700">
                  <li><strong>Device-Level Security:</strong> Authorized Android devices utilize scoped, sandboxed application storage. Templates are stored as encoded mathematical representations rather than raw unencrypted image files.</li>
                  <li><strong>Transport Layer Security:</strong> All API communication between mobile applications, web dashboard, and cloud servers is enforced via <strong>HTTPS / TLS 1.3</strong> encryption.</li>
                  <li><strong>Secure Cloud Infrastructure:</strong> Cloud backend databases and services are hosted in enterprise data centers with managed firewalls, automated encrypted backups, and access policies.</li>
                  <li><strong>Access Controls:</strong> System access is guarded by cryptographic password hashing, JSON Web Tokens (JWT), and strict Role-Based Access Control (RBAC).</li>
                  <li><strong>Backup Protocols:</strong> Automated database snapshots are taken periodically to prevent data loss due to hardware failure.</li>
                </ul>
              </div>
            </section>

            {/* ── Section 8: Data Sharing and Third-Party Services ── */}
            <section
              id="section-8"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Share2 size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    8. Data Sharing and Third-Party Services
                  </h2>
                  <p className="text-xs text-slate-400">Restricted disclosure policy and infrastructure providers</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We do not share, sell, or rent biometric or personal records to data brokers, advertising agencies, or commercial third parties. Data is disclosed only in the following limited circumstances:
                </p>
                <ul className="list-disc list-inside space-y-2 pl-2 text-slate-700">
                  <li><strong>Subscribing Employer / Institution:</strong> Attendance logs, leave records, and department rosters are shared directly with the designated administrators of your subscribing organization.</li>
                  <li><strong>Cloud Infrastructure Partners:</strong> We utilize secure enterprise cloud providers for hosting application APIs, encrypted databases, and backend services under strict confidentiality and data protection agreements.</li>
                  <li><strong>Notification Services:</strong> Firebase Cloud Messaging (FCM) is utilized for delivering instant synchronization and attendance alert notifications.</li>
                  <li><strong>Legal Requirements:</strong> We may disclose records if required to do so by applicable Indian law, court order, or governmental law enforcement directive.</li>
                </ul>
              </div>
            </section>

            {/* ── Section 9: Data Retention and Deletion ── */}
            <section
              id="section-9"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Clock size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    9. Data Retention and Deletion
                  </h2>
                  <p className="text-xs text-slate-400">Lifecycle policies, purge schedules, and data deletion requests</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We retain personal and biometric information only for as long as necessary to fulfill the operational purposes outlined in this policy:
                </p>
                <ul className="list-disc list-inside space-y-2 pl-2 text-slate-700">
                  <li><strong>Active Tenure:</strong> Employee and student records remain active for the duration of their employment, academic term, or organizational subscription.</li>
                  <li><strong>Account Deletion:</strong> When an administrator deletes an employee or resident from the portal or mobile roster, their facial embeddings and photos are marked for immediate deletion and purged from active synchronization caches.</li>
                  <li><strong>Subscription Termination:</strong> Upon termination of an organization&rsquo;s contract with TapInX, all stored records and biometric embeddings are permanently purged within 30 days.</li>
                  <li><strong>Individual Deletion Requests:</strong> Users can request deletion of their biometric data by notifying their organization administrator or emailing us at <a href="mailto:support@tapinx.in" className="text-violet-600 font-semibold underline">support@tapinx.in</a>.</li>
                </ul>
              </div>
            </section>

            {/* ── Section 10: User Rights and Consent ── */}
            <section
              id="section-10"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <ShieldCheck size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    10. User Rights and Consent
                  </h2>
                  <p className="text-xs text-slate-400">Statutory entitlements under the Digital Personal Data Protection Act, 2023</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  Under applicable data protection frameworks (including India&rsquo;s Digital Personal Data Protection Act, 2023), users possess fundamental rights regarding their personal data:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div className="p-3.5 bg-slate-50/80 rounded-xl border border-slate-200/90">
                    <strong className="text-slate-900 block mb-1">Right of Access &amp; Correction</strong>
                    You may review and request correction of inaccurate personal or attendance entries through your organization administrator.
                  </div>
                  <div className="p-3.5 bg-slate-50/80 rounded-xl border border-slate-200/90">
                    <strong className="text-slate-900 block mb-1">Right to Withdraw Consent</strong>
                    You may withdraw consent for facial recognition attendance at any time. In such cases, your employer may provide alternative manual or card-based attendance methods.
                  </div>
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  <strong>Employer Responsibility:</strong> Subscribing employers and educational institutions act as Data Fiduciaries and are responsible for obtaining valid informed consent from employees, contractors, or students before enrolling them into TapInX.
                </p>
              </div>
            </section>

            {/* ── Section 11: Children's and Student Privacy ── */}
            <section
              id="section-11"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Users size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    11. Children&rsquo;s and Student Privacy
                  </h2>
                  <p className="text-xs text-slate-400">Safeguards for minors, schools, colleges, and resident hostels</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  When TapInX is deployed in schools, colleges, or hostels with residents under the age of 18:
                </p>
                <ul className="list-disc list-inside space-y-2 pl-2 text-slate-700">
                  <li>Data is processed strictly under the supervision and authorization of the educational institution acting in loco parentis.</li>
                  <li>Institutions are required to ensure parental or legal guardian consent before capturing student facial images.</li>
                  <li>Student biometric data is used exclusively for campus gate safety, hostel curfew verification, and lecture attendance. It is never profiled or monetized.</li>
                </ul>
              </div>
            </section>

            {/* ── Section 12: Cookies and Website Tracking ── */}
            <section
              id="section-12"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Cookie size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    12. Cookies and Website Tracking
                  </h2>
                  <p className="text-xs text-slate-400">Web dashboard session cookies and tracking technologies</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  The TapInX Web Dashboard uses essential cookies and local storage tokens strictly to maintain authenticated user sessions, prevent CSRF attacks, and remember UI display preferences. We do not deploy third-party advertising cookies, cross-site trackers, or behavioral profiling pixels on <a href="https://tapinx.in" className="text-violet-600 font-semibold underline">https://tapinx.in</a>.
                </p>
              </div>
            </section>

            {/* ── Section 13: International Data Transfers ── */}
            <section
              id="section-13"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <Globe size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    13. International Data Transfers
                  </h2>
                  <p className="text-xs text-slate-400">Data residency commitments within Indian borders</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  TapInX servers and primary database instances are situated in regional cloud infrastructure located within India (Mumbai region). In the event that technical diagnostic telemetry is processed across cross-border cloud networks, such processing is governed by robust data security clauses and standard contractual safeguards.
                </p>
              </div>
            </section>

            {/* ── Section 14: Changes to This Privacy Policy ── */}
            <section
              id="section-14"
              className="scroll-mt-24 rounded-2xl border border-slate-200/90 bg-white p-6 sm:p-7 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 border border-violet-100 flex items-center justify-center">
                  <RefreshCw size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    14. Changes to This Privacy Policy
                  </h2>
                  <p className="text-xs text-slate-400">Revision notices and material amendment process</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We may periodically update this Privacy Policy to reflect enhancements in technology, statutory amendments, or evolving Google Play Store requirements. Material revisions will be prominently announced via our web dashboard banner or mobile app update release notes. Continued use of TapInX after notification constitutes acceptance of the updated terms.
                </p>
              </div>
            </section>

            {/* ── Section 15: Contact and Privacy Redressal ── */}
            <section
              id="section-15"
              className="scroll-mt-24 rounded-2xl border border-violet-300 bg-gradient-to-br from-white via-violet-50/30 to-indigo-50/40 p-6 sm:p-8 shadow-xs space-y-4"
            >
              <div className="flex items-center gap-3 border-b border-violet-100 pb-3">
                <div className="w-9 h-9 rounded-xl bg-violet-600 text-white flex items-center justify-center shadow-xs">
                  <HelpCircle size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    15. Contact and Privacy Redressal
                  </h2>
                  <p className="text-xs text-slate-400">Dedicated statutory privacy and grievance redressal channel</p>
                </div>
              </div>

              <div className="text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  If you have inquiries, complaints, or grievance requests concerning your personal or biometric information, or wish to exercise your data protection rights, please contact our Privacy and Support Team:
                </p>

                <div className="rounded-xl border border-violet-200 bg-white p-5 text-xs space-y-2 shadow-2xs">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <span className="font-bold text-slate-800 block text-[11px] uppercase tracking-wider text-slate-400">Legal Entity</span>
                      <span className="font-semibold text-slate-900 text-sm">OpenVisionX Technologies</span>
                    </div>
                    <div>
                      <span className="font-bold text-slate-800 block text-[11px] uppercase tracking-wider text-slate-400">Product Name</span>
                      <span className="font-semibold text-slate-900 text-sm">TapInX</span>
                    </div>
                    <div>
                      <span className="font-bold text-slate-800 block text-[11px] uppercase tracking-wider text-slate-400">Official Privacy Email</span>
                      <a href="mailto:support@tapinx.in" className="font-bold text-violet-700 underline text-sm">support@tapinx.in</a>
                    </div>
                    <div>
                      <span className="font-bold text-slate-800 block text-[11px] uppercase tracking-wider text-slate-400">Official Portal</span>
                      <a href="https://tapinx.in" className="text-violet-600 underline">https://tapinx.in</a>
                    </div>
                    <div className="sm:col-span-2">
                      <span className="font-bold text-slate-800 block text-[11px] uppercase tracking-wider text-slate-400">Response Turnaround</span>
                      <span className="font-semibold text-emerald-700">All inquiries and requests resolved within 72 business hours</span>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </main>
        </div>
      </div>

      {/* ─── Modern Co-Branded Footer ─── */}
      <footer className="mt-20 border-t border-slate-200 bg-white py-10 text-xs text-slate-500">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
            
            {/* Left: Branding & Copyright */}
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-slate-50 border border-slate-200 flex items-center justify-center p-1">
                <img src="/tapinx-logo.svg" alt="TapInX" className="w-full h-full object-contain" />
              </div>
              <div className="w-8 h-8 rounded-lg bg-white border border-slate-200 flex items-center justify-center p-1">
                <img src="/openVisionXLogo.png" alt="OpenVisionX" className="w-full h-full object-contain" />
              </div>
              <div className="text-left">
                <p className="font-semibold text-slate-800">
                  &copy; {new Date().getFullYear()} OpenVisionX Technologies. All rights reserved.
                </p>
                <p className="text-[11px] text-slate-400">
                  TapInX is a registered product and trademark of OpenVisionX Technologies.
                </p>
              </div>
            </div>

            {/* Right: Quick Links */}
            <div className="flex items-center gap-6 font-medium">
              <Link to="/login" className="hover:text-violet-700 transition-colors">
                Login Portal
              </Link>
              <a href="mailto:support@tapinx.in" className="hover:text-violet-700 transition-colors">
                Support
              </a>
              <button
                onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                className="hover:text-violet-700 transition-colors font-bold flex items-center gap-1"
              >
                Back to Top &uarr;
              </button>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}