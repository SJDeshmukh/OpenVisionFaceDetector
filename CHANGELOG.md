# Changelog

## 2026-01-31

### Super Admin
- Vendor web session limits enforced; UI field to configure max admin web sessions
- Delete vendor now archives all related data and supports restore from archive
- Vendor creation detects archived matches and offers a one-click restore
- Employee detail view is configurable by business (school vs payroll)
- Live Feed tab hidden by default; unlock with the "jonas" key sequence per session

### Attendance & Reports
- Attendance filters driven by vendor registration_config
- School view shows attendance-based KPIs; payroll vendors show payroll metrics
- Payroll report fallback to attendance when feature not enabled

### Auth & CORS
- Web login sends stable device_id and platform for session tracking
- CORS allows Authorization and vendor-context headers; UI uses vendor_id param to avoid preflight

### Billing
- Invoice generation and status update endpoints refined with breakdown details

### Misc
- UI fixes and minor export tweaks across dashboards

