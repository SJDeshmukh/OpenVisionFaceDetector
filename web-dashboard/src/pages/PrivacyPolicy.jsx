import React from 'react';
import { 
  ShieldCheck, 
  Camera, 
  MapPin, 
  Lock, 
  Database, 
  FileText, 
  UserCheck, 
  AlertTriangle, 
  HelpCircle, 
  Building2, 
  Mail, 
  ExternalLink,
  ChevronRight,
  ArrowLeft
} from 'lucide-react';
import { Link } from 'react-router-dom';

export default function PrivacyPolicy() {
  const lastUpdated = "November 15, 2026";
  const effectiveDate = "November 15, 2026";

  const scrollToSection = (id) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 antialiased font-sans">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-600 shadow-md shadow-indigo-200 text-white font-black text-xl">
              T
            </div>
            <div>
              <span className="text-lg font-black tracking-tight text-slate-900">TapInX</span>
              <span className="ml-2 rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-bold text-indigo-700 border border-indigo-100">
                Privacy Center
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
            >
              <ArrowLeft size={14} /> Back to Login
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Banner */}
      <section className="border-b border-indigo-100 bg-gradient-to-b from-indigo-50/70 via-white to-slate-50 py-12 px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-5xl text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-100/70 px-3.5 py-1 text-xs font-bold text-indigo-800 mb-4 shadow-sm">
            <ShieldCheck size={16} className="text-indigo-600" />
            AI-Powered Biometric Attendance &amp; Workforce Platform
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            TapInX Privacy Policy
          </h1>
          <p className="mt-3 text-base text-slate-600 sm:text-lg max-w-3xl mx-auto">
            Your privacy and biometric security are our highest priority. Learn how TapInX collects, processes, encrypts, and protects your personal, camera, location, and facial recognition data.
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3 text-xs font-medium text-slate-500">
            <span className="rounded-lg bg-white px-3 py-1.5 border border-slate-200 shadow-xs">
              <strong>Effective Date:</strong> {effectiveDate}
            </span>
            <span className="rounded-lg bg-white px-3 py-1.5 border border-slate-200 shadow-xs">
              <strong>Last Updated:</strong> {lastUpdated}
            </span>
            <span className="rounded-lg bg-emerald-50 px-3 py-1.5 border border-emerald-200 text-emerald-800 shadow-xs font-semibold">
              ✓ DPDP Act 2023 &amp; Google Play Data Safety Aligned
            </span>
          </div>
        </div>
      </section>

      {/* Main Layout: Sidebar & Content */}
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[280px_minmax(0,1fr)]">
          {/* Table of Contents Sticky Sidebar */}
          <aside className="hidden lg:block">
            <div className="sticky top-20 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
                Contents
              </h2>
              <nav className="space-y-1 text-xs font-medium max-h-[75vh] overflow-y-auto pr-1">
                {[
                  { id: 'section-1', title: '1. Company & Application Info' },
                  { id: 'section-2', title: '2. Information We Collect' },
                  { id: 'section-3', title: '3. Biometric & Facial Data' },
                  { id: 'section-4', title: '4. Camera Permission' },
                  { id: 'section-5', title: '5. Location Permission & Geofencing' },
                  { id: 'section-6', title: '6. How We Use Information' },
                  { id: 'section-7', title: '7. Data Storage & Security' },
                  { id: 'section-8', title: '8. Data Sharing & Third Parties' },
                  { id: 'section-9', title: '9. Data Retention & Deletion' },
                  { id: 'section-10', title: '10. User Rights & Consent' },
                  { id: 'section-11', title: '11. Children’s & Student Privacy' },
                  { id: 'section-12', title: '12. Cookies & Web Tracking' },
                  { id: 'section-13', title: '13. International Transfers' },
                  { id: 'section-14', title: '14. Policy Updates' },
                  { id: 'section-15', title: '15. Contact & Grievance Officer' },
                ].map((item) => (
                  <button
                    key={item.id}
                    onClick={() => scrollToSection(item.id)}
                    className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-slate-600 hover:bg-indigo-50 hover:text-indigo-700 transition"
                  >
                    <span className="truncate">{item.title}</span>
                    <ChevronRight size={13} className="shrink-0 opacity-50" />
                  </button>
                ))}
              </nav>
            </div>
          </aside>

          {/* Privacy Policy Content Body */}
          <main className="space-y-10">
            {/* Quick Highlights Card */}
            <div className="rounded-2xl border border-indigo-200 bg-gradient-to-br from-indigo-50/60 via-white to-violet-50/50 p-6 shadow-xs">
              <h3 className="text-base font-bold text-indigo-950 flex items-center gap-2">
                <ShieldCheck className="text-indigo-600" size={20} />
                Key Privacy Commitments at a Glance
              </h3>
              <ul className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs text-slate-700">
                <li className="flex items-start gap-2 bg-white/80 p-3 rounded-xl border border-indigo-100">
                  <span className="font-bold text-indigo-600">✓</span>
                  <span><strong>Zero Advertising:</strong> We never sell, rent, or monetize your biometric or personal data to third parties or advertising networks.</span>
                </li>
                <li className="flex items-start gap-2 bg-white/80 p-3 rounded-xl border border-indigo-100">
                  <span className="font-bold text-indigo-600">✓</span>
                  <span><strong>Edge Biometric AI:</strong> Face recognition operates via on-device mathematical embeddings (512-D vectors) with live anti-spoofing verification.</span>
                </li>
                <li className="flex items-start gap-2 bg-white/80 p-3 rounded-xl border border-indigo-100">
                  <span className="font-bold text-indigo-600">✓</span>
                  <span><strong>Geofence Only:</strong> Location coordinates are captured strictly at the instant of attendance check-in/out. No background tracking.</span>
                </li>
                <li className="flex items-start gap-2 bg-white/80 p-3 rounded-xl border border-indigo-100">
                  <span className="font-bold text-indigo-600">✓</span>
                  <span><strong>Right to Erasure:</strong> Organizations and employees can request permanent deletion of biometric templates and attendance history at any time.</span>
                </li>
              </ul>
            </div>

            {/* Section 1 */}
            <section id="section-1" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <Building2 className="text-indigo-600" size={22} />
                1. Company and Application Information
              </h2>
              <div className="mt-4 text-sm text-slate-600 space-y-3 leading-relaxed">
                <p>
                  This Privacy Policy describes the policies and procedures of <strong>OpenVisionX Technologies</strong> (&ldquo;Company&rdquo;, &ldquo;we&rdquo;, &ldquo;our&rdquo;, or &ldquo;us&rdquo;) regarding the collection, use, processing, storage, and disclosure of personal, camera, location, and biometric information when you access or use:
                </p>
                <ul className="list-disc list-inside space-y-1 pl-2 text-slate-700 font-medium">
                  <li>The <strong>TapInX</strong> Android mobile applications (kiosk mode, employee client, and faculty modules).</li>
                  <li>The <strong>TapInX Web Portal and Admin Dashboard</strong> (hosted at <a href="https://tapinx.in" className="text-indigo-600 hover:underline">https://tapinx.in</a>).</li>
                  <li>Our cloud synchronization backend and associated Application Programming Interfaces (APIs).</li>
                </ul>
                <div className="mt-4 rounded-xl bg-slate-50 p-4 border border-slate-200 text-xs space-y-1.5">
                  <div><strong>Developer &amp; Legal Entity:</strong> OpenVisionX Technologies</div>
                  <div><strong>Product Name:</strong> TapInX</div>
                  <div><strong>Official Website:</strong> <a href="https://tapinx.in" className="text-indigo-600 underline">https://tapinx.in</a></div>
                  <div><strong>Privacy Support &amp; Data Protection Email:</strong> <a href="mailto:support@tapinx.in" className="text-indigo-600 underline">support@tapinx.in</a></div>
                  <div><strong>Scope:</strong> TapInX Android Application, Web Dashboard, and Cloud Infrastructure</div>
                </div>
              </div>
            </section>

            {/* Section 2 */}
            <section id="section-2" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <Database className="text-indigo-600" size={22} />
                2. Information We Collect
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We collect only the categories of information strictly necessary to provide identity verification, attendance logging, leave and shift management, and geofence validation for our subscribing customer organizations:
                </p>
                <div className="overflow-x-auto rounded-xl border border-slate-200 mt-3">
                  <table className="min-w-full divide-y divide-slate-200 text-xs text-left">
                    <thead className="bg-slate-50 text-slate-700 font-bold">
                      <tr>
                        <th className="py-2.5 px-3">Data Category</th>
                        <th className="py-2.5 px-3">Information Collected</th>
                        <th className="py-2.5 px-3">Purpose &amp; Processing</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200 bg-white">
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Personal Information</td>
                        <td className="py-2.5 px-3">Full name, Employee ID / Roll Number, phone number, email address</td>
                        <td className="py-2.5 px-3">Roster enrollment, profile association, and identity management</td>
                      </tr>
                      <tr className="bg-indigo-50/30">
                        <td className="py-2.5 px-3 font-semibold text-indigo-950">Biometric Information</td>
                        <td className="py-2.5 px-3 font-medium">Facial images, 512-dimensional facial mathematical embeddings</td>
                        <td className="py-2.5 px-3">1:N &amp; 1:1 facial recognition, proxy prevention, anti-spoofing</td>
                      </tr>
                      <tr>
                        <td className="py-2.5 px-3 font-semibold text-slate-900">Camera Data</td>
                        <td className="py-2.5 px-3">Live face images captured during registration and verification punches</td>
                        <td className="py-2.5 px-3">Edge template extraction and visual audit verification</td>
                      </tr>
                      <tr className="bg-indigo-50/30">
                        <td className="py-2.5 px-3 font-semibold text-indigo-950">Location Data</td>
                        <td className="py-2.5 px-3 font-medium">Precise GPS coordinates (latitude, longitude) at the moment of punch</td>
                        <td className="py-2.5 px-3">Validating punch against authorized workplace or campus geofences</td>
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

            {/* Section 3 */}
            <section id="section-3" className="scroll-mt-24 rounded-2xl border border-indigo-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-indigo-100 pb-3 flex items-center gap-2">
                <UserCheck className="text-indigo-600" size={22} />
                3. Biometric and Facial Recognition Data
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-4">
                <div className="rounded-xl border border-indigo-100 bg-indigo-50/70 p-4 text-xs font-semibold text-indigo-900">
                  Critical Disclosure: TapInX uses artificial intelligence-based facial recognition technology exclusively to provide secure employee/student attendance verification and prevent proxy attendance. We do not use biometric data for advertising or sell biometric information to third parties.
                </div>
                
                <h3 className="font-bold text-slate-900 text-sm">A. How Facial Recognition Works</h3>
                <p>
                  During member registration, a front-facing camera photo is captured. Our on-device neural network (SCRFD face detector and MobileFaceNet feature extractor) analyzes facial landmarks (such as distance between eyes, nose contour, and jawline) to compute a <strong>512-dimensional normalized mathematical representation (facial embedding)</strong>.
                </p>

                <h3 className="font-bold text-slate-900 text-sm">B. Anti-Spoofing and Liveness Verification</h3>
                <p>
                  To prevent fraudulent punches using photographs, smartphone displays, or paper cutouts, TapInX performs edge 2D passive liveness verification (MiniFASNet). Live frames are checked for specular reflections, moiré patterns, and micro-motion before validating an identity.
                </p>

                <h3 className="font-bold text-slate-900 text-sm">C. Storage and Synchronization</h3>
                <p>
                  Biometric embeddings are serialized in a compact proprietary format (FID1) and stored locally in encrypted SQLite storage on authorized kiosk devices. When cloud synchronization is enabled, these mathematical vectors and compressed reference photos are synchronized with our secure AWS backend over HTTPS/TLS to enable recognition across authorized devices within the organization.
                </p>

                <h3 className="font-bold text-slate-900 text-sm">D. Access and Deletion</h3>
                <p>
                  Only authorized administrators of your organization can access member attendance logs. Raw facial embeddings cannot be reverse-engineered to reconstruct the original photograph. When an administrator removes a member, their facial templates and reference images are purged from both local devices and backend storage.
                </p>
              </div>
            </section>

            {/* Section 4 */}
            <section id="section-4" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <Camera className="text-indigo-600" size={22} />
                4. Camera Permission
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  TapInX requests Android runtime access to the device camera (<code>android.permission.CAMERA</code>). Camera access is required strictly for:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li>Capturing a clear reference face photo during employee/student enrollment.</li>
                  <li>Scanning faces during live check-in and check-out attendance verification.</li>
                  <li>Real-time anti-spoofing and liveness analysis.</li>
                </ul>
                <p className="rounded-lg bg-amber-50 p-3 border border-amber-200 text-xs text-amber-900 font-medium">
                  <strong>Important Notice:</strong> Camera access is active only while the camera preview or attendance scanning interface is visible on screen. TapInX does not perform covert, background, or general surveillance video recording.
                </p>
              </div>
            </section>

            {/* Section 5 */}
            <section id="section-5" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <MapPin className="text-indigo-600" size={22} />
                5. Location Permission and Geofencing
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  TapInX requests location permissions (<code>ACCESS_FINE_LOCATION</code> and <code>ACCESS_COARSE_LOCATION</code>) to enforce attendance geofencing:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li><strong>Purpose:</strong> Validating that attendance punches originate from authorized workplace, factory, or campus boundaries.</li>
                  <li><strong>Collection Timing:</strong> GPS coordinates are queried <em>strictly at the moment</em> an attendance punch is recorded.</li>
                  <li><strong>No Background Tracking:</strong> TapInX does not monitor, track, or broadcast your location continuously in the background when the app is idle.</li>
                  <li><strong>Audit Logs:</strong> The timestamped coordinates recorded during a punch are visible to authorized organization supervisors for compliance verification.</li>
                </ul>
              </div>
            </section>

            {/* Section 6 */}
            <section id="section-6" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <FileText className="text-indigo-600" size={22} />
                6. How We Use Collected Information
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-2">
                <p>We process collected data solely for the following legitimate business and institutional functions:</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3 text-xs">
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <strong className="text-slate-900 block mb-1">Identity &amp; Attendance Verification</strong>
                    Accurately logging employee check-ins, check-outs, shift attendance, and lecture attendance without proxy punches.
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <strong className="text-slate-900 block mb-1">Working Hours &amp; Wage Calculation</strong>
                    Computing daily payable hours, overtime, and salary summaries for business payroll processing.
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <strong className="text-slate-900 block mb-1">Hostel &amp; Campus Movement</strong>
                    Tracking resident in/out movements, approved leave gate passes, and bed occupancy allocation.
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <strong className="text-slate-900 block mb-1">Security &amp; Fraud Prevention</strong>
                    Detecting attendance tampering, device spoofing, or unauthorized biometric impersonation attempts.
                  </div>
                </div>
              </div>
            </section>

            {/* Section 7 */}
            <section id="section-7" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <Lock className="text-indigo-600" size={22} />
                7. Data Storage and Security
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We implement multi-layered administrative, technical, and physical safeguards to protect biometric, personal, and location records:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li><strong>Device-Level Security:</strong> Android local SQLite databases utilize scoped app-private sandbox storage. Templates are encoded in compact binary format, not raw images.</li>
                  <li><strong>Transport Layer Security:</strong> All API communication between mobile applications, web dashboard, and cloud servers is enforced via <strong>HTTPS / TLS 1.3</strong> encryption.</li>
                  <li><strong>AWS Cloud Infrastructure:</strong> Cloud backend databases and services are hosted on Amazon Web Services (AWS) in regional data centers with managed firewall and access policies.</li>
                  <li><strong>Access Controls:</strong> System access is guarded by cryptographic password hashing, JSON Web Tokens (JWT), and strict Role-Based Access Control (RBAC).</li>
                  <li><strong>Backup Protocols:</strong> Automated database snapshots are taken periodically to prevent data loss due to hardware failure.</li>
                </ul>
              </div>
            </section>

            {/* Section 8 */}
            <section id="section-8" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <ExternalLink className="text-indigo-600" size={22} />
                8. Data Sharing and Third-Party Services
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We do not share, sell, or rent biometric or personal records to data brokers, advertising agencies, or commercial third parties. Data is disclosed only in the following limited circumstances:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li><strong>Subscribing Employer / Institution:</strong> Attendance logs, leave records, and department rosters are shared directly with the designated administrators of your subscribing organization.</li>
                  <li><strong>Cloud Infrastructure Partners:</strong> We utilize Amazon Web Services (AWS) for hosting cloud servers, APIs, and PostgreSQL database storage under strict data protection agreements.</li>
                  <li><strong>Notification Services:</strong> Firebase Cloud Messaging (FCM) is utilized for delivering instant synchronization and attendance alert notifications.</li>
                  <li><strong>Legal Requirements:</strong> We may disclose records if required to do so by applicable Indian law, court order, or governmental law enforcement directive.</li>
                </ul>
              </div>
            </section>

            {/* Section 9 */}
            <section id="section-9" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <AlertTriangle className="text-indigo-600" size={22} />
                9. Data Retention and Deletion
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We retain personal and biometric information only for as long as necessary to fulfill the operational purposes outlined in this policy:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li><strong>Active Tenure:</strong> Employee and student records remain active for the duration of their employment, academic term, or organizational subscription.</li>
                  <li><strong>Account Deletion:</strong> When an administrator deletes an employee or resident from the portal or mobile roster, their facial embeddings and photos are marked for immediate deletion and purged from active synchronization caches.</li>
                  <li><strong>Subscription Termination:</strong> Upon termination of an organization&rsquo;s contract with TapInX, all stored records and biometric embeddings are permanently purged within 30 days.</li>
                  <li><strong>Individual Deletion Requests:</strong> Users can request deletion of their biometric data by notifying their organization administrator or emailing us at <a href="mailto:support@tapinx.in" className="text-indigo-600 underline">support@tapinx.in</a>.</li>
                </ul>
              </div>
            </section>

            {/* Section 10 */}
            <section id="section-10" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <ShieldCheck className="text-indigo-600" size={22} />
                10. User Rights and Consent
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  Under applicable data protection frameworks (including India&rsquo;s Digital Personal Data Protection Act, 2023), users possess fundamental rights regarding their personal data:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <strong>Right of Access &amp; Correction:</strong> You may review and request correction of inaccurate personal or attendance entries through your organization administrator.
                  </div>
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <strong>Right to Withdraw Consent:</strong> You may withdraw consent for facial recognition attendance at any time. In such cases, your employer may provide alternative manual or card-based attendance methods.
                  </div>
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  <strong>Employer Responsibility:</strong> Subscribing employers and educational institutions act as Data Fiduciaries and are responsible for obtaining valid informed consent from employees, contractors, or students before enrolling them into TapInX.
                </p>
              </div>
            </section>

            {/* Section 11 */}
            <section id="section-11" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <UserCheck className="text-indigo-600" size={22} />
                11. Children&rsquo;s and Student Privacy
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  When TapInX is deployed in schools, colleges, or hostels with residents under the age of 18:
                </p>
                <ul className="list-disc list-inside space-y-1.5 pl-2 text-slate-700">
                  <li>Data is processed strictly under the supervision and authorization of the educational institution acting in loco parentis.</li>
                  <li>Institutions are required to ensure parental or legal guardian consent before capturing student facial images.</li>
                  <li>Student biometric data is used exclusively for campus gate safety, hostel curfew verification, and lecture attendance. It is never profiled or monetized.</li>
                </ul>
              </div>
            </section>

            {/* Section 12 */}
            <section id="section-12" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <Database className="text-indigo-600" size={22} />
                12. Cookies and Website Tracking
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  The TapInX Web Dashboard uses essential cookies and local storage tokens strictly to maintain authenticated user sessions, prevent CSRF attacks, and remember UI display preferences. We do not deploy third-party advertising cookies, cross-site trackers, or behavioral profiling pixels on <a href="https://tapinx.in" className="text-indigo-600 underline">https://tapinx.in</a>.
                </p>
              </div>
            </section>

            {/* Section 13 */}
            <section id="section-13" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <Lock className="text-indigo-600" size={22} />
                13. International Data Transfers
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  TapInX servers and primary database instances are situated in regional cloud infrastructure located within India (AWS Asia Pacific - Mumbai region, <code>ap-south-1</code>). In the event that technical diagnostic telemetry is processed across cross-border cloud networks, such processing is governed by robust data security clauses and standard contractual safeguards.
                </p>
              </div>
            </section>

            {/* Section 14 */}
            <section id="section-14" className="scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-3 flex items-center gap-2">
                <FileText className="text-indigo-600" size={22} />
                14. Changes to This Privacy Policy
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  We may periodically update this Privacy Policy to reflect enhancements in technology, statutory amendments, or evolving Google Play Store requirements. Material revisions will be prominently announced via our web dashboard banner or mobile app update release notes. Continued use of TapInX after notification constitutes acceptance of the updated terms.
                </p>
              </div>
            </section>

            {/* Section 15 */}
            <section id="section-15" className="scroll-mt-24 rounded-2xl border border-indigo-200 bg-gradient-to-br from-white via-indigo-50/30 to-violet-50/40 p-6 shadow-xs">
              <h2 className="text-xl font-bold text-slate-900 border-b border-indigo-100 pb-3 flex items-center gap-2">
                <HelpCircle className="text-indigo-600" size={22} />
                15. Contact and Grievance Officer
              </h2>
              <div className="mt-4 text-sm text-slate-600 leading-relaxed space-y-3">
                <p>
                  If you have inquiries, complaints, or grievance requests concerning your personal or biometric information, or wish to exercise your data protection rights, please contact our designated Grievance Officer:
                </p>
                <div className="rounded-xl border border-indigo-100 bg-white p-4 text-xs space-y-1.5 shadow-xs">
                  <div><strong>Legal Entity:</strong> OpenVisionX Technologies</div>
                  <div><strong>Product:</strong> TapInX</div>
                  <div><strong>Designated Grievance &amp; Privacy Officer:</strong> Sudhanshu Deshmukh</div>
                  <div><strong>Email:</strong> <a href="mailto:support@tapinx.in" className="text-indigo-600 font-semibold underline">support@tapinx.in</a></div>
                  <div><strong>Official Portal:</strong> <a href="https://tapinx.in" className="text-indigo-600 underline">https://tapinx.in</a></div>
                  <div><strong>Response Turnaround:</strong> All privacy grievances are addressed within 72 business hours.</div>
                </div>
              </div>
            </section>
          </main>
        </div>
      </div>

      {/* Footer */}
      <footer className="mt-16 border-t border-slate-200 bg-white py-8 text-center text-xs text-slate-500">
        <div className="mx-auto max-w-7xl px-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p>© {new Date().getFullYear()} OpenVisionX Technologies. TapInX is a registered trademark. All rights reserved.</p>
          <div className="flex gap-4">
            <Link to="/login" className="hover:text-indigo-600">Login Portal</Link>
            <a href="mailto:support@tapinx.in" className="hover:text-indigo-600">Support</a>
            <button onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} className="hover:text-indigo-600">Back to Top ↑</button>
          </div>
        </div>
      </footer>
    </div>
  );
}
