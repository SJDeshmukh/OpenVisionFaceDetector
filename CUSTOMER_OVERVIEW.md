# OpenVisionX — Face Attendance Platform (Customer Overview)

OpenVisionX is a modern face-based attendance platform built for two use-cases:
1. **Manufacturing / Daily Wages**: fast, reliable worker attendance + wages/payroll-ready reporting
2. **Schools / Colleges**: parent-friendly check-in/check-out visibility for students (no-login option)

The system combines an **Android camera app** (kiosk/user), a **web dashboard** (admin/vendor), and a **backend server** with real-time updates.

---

## 1) Manufacturing / Daily Wages

### What it solves
- Accurate attendance at gates/floors without manual registers
- Faster payroll processing with clear daily/monthly summaries
- Visibility for supervisors/HR through live feeds and reports

### Key features
- **Face-based check-in / check-out** with instant confirmation
- **Shift-ready attendance** (supports shift rules; can be extended for multiple gates/lines)
- **Employee directory** with department/designation fields
- **Live attendance feed** for supervisors and HR
- **Wage & payroll reporting** (daily wages style reporting, totals and detailed exports)
- **Device-friendly operations**: low-bandwidth streaming, power-saver UX, optional offline queue on mobile
- **Audit-friendly** records: vendor-scoped data separation and role-based access (admin/vendor/kiosk)

### Typical workflows
- **Enrollment**: capture worker face + employee details
- **Daily attendance**: camera recognizes person → check-in/out stored → supervisors see updates live
- **Payroll**: HR downloads payroll-ready reports by date range / worker / department

---

## 2) School / Parents (Student Check-In / Check-Out)

### What it solves
- Parents want confidence: “Has my child entered school?” “When did they leave?”
- Schools want a smooth gate process with minimal staff effort

### Key features
- **Student check-in / check-out** through face recognition at gate
- **Parent experience with no-login option**:
  - parent enters student number to view attendance history
  - parents can receive **real-time updates** (live) when events occur
- **Privacy-first parent mode**:
  - parent flows can work **without sending student images**
  - only lightweight attendance events are delivered to parent mode
- **Optional push notifications** (FCM) for attendance events
- **Date-filtered history** (single-day or range)

### Typical workflows
- **Student enrollment**: capture face, assign student number + class/section
- **Gate attendance**: student recognized → check-in/out stored → parent gets live update and can view history

---

## How the System Works (High Level)

### Components
- **Android app (Camera/Kiosk/User)**: runs on a phone/tablet at entry gate or attendance point
- **Web dashboard**:
  - Super Admin: onboarding, subscriptions, limits
  - Vendor Admin: people directory, live feed, reports, settings
- **Backend server**: APIs + real-time updates (Socket-based) with a database for all records

### Real-time updates
When attendance is captured, dashboards and parent mode can receive instant updates (no refresh needed).

---

## Data, Privacy & Security

- **Role-based access**: super admin, vendor admin, kiosk/user roles
- **Vendor isolation**: each business (factory/school) data is logically separated
- **Parent privacy**:
  - parent viewing mode is designed to avoid sharing images
  - the parent side can operate on lightweight attendance events + history
- **Configurable storage**:
  - attendance images can be optional (based on customer policy)
  - storage can use DB + optional S3-compatible object storage for media

---

## Deployment Options

- **Cloud hosted** (recommended): managed backend + worker + Redis + web dashboard
- **Customer hosting** (optional): deploy to customer cloud/VPS based on security needs
- **Local network setup** (for kiosk devices): Android can point to the backend over LAN/Wi‑Fi

---

## What You Get

- Android attendance app (CameraX + Face recognition SDK integration)
- Web dashboard (Admin + Vendor views)
- Backend APIs + real-time updates
- Reports for attendance and wages (manufacturing) and parent-friendly visibility (school)

---

## Implementation (Typical)

- **Day 1–3**: setup + branding + vendor onboarding + initial configuration
- **Week 1**: pilot in one gate / one site; enrollment process and staff training
- **Week 2+**: rollout to additional gates/departments/classes; report customization

---

## Add-ons (Optional Enhancements)

Manufacturing:
- Multi-gate tracking, geo/Wi‑Fi restriction, break tracking, overtime rules, contractor billing reports

School:
- Parent linking to multiple students, richer notifications, ID card printing, analytics by class/section

---

## Contact / Demo

Share your preferred demo scenario (manufacturing or school), number of devices, and approximate headcount, and we can prepare a tailored walkthrough and sample reports.

