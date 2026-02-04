# OpenVisionX Customer Demo Video Kit (Slide-wise)

This kit gives you a complete **slide-by-slide script + voiceover** and a **screen-recording shot list** to produce a clean 6–10 minute customer demo video.

Target audience: a potential customer evaluating OpenVisionX for **Manufacturing/Daily Wages** and/or **School/Parents**.

---

## Video Settings (recommended)

- Duration: 6–10 minutes
- Format: 1920×1080 (1080p), 30 fps
- Audio: clear mic, minimal background noise
- Recording style: screen capture + small webcam (optional)

---

## Slide Deck (10 slides)

Use these as slide titles + bullets. Speaker notes are included per slide.

### Slide 1 — Title
**On-slide**
- OpenVisionX – Face Attendance Platform
- Two verticals: Manufacturing Wages + School Parent Updates

**Voiceover (10–15s)**
“Hi, this is a quick walkthrough of OpenVisionX, a face-based attendance platform designed for two use cases: manufacturing and daily wages workforce, and schools where parents want instant visibility of student check-in and check-out.”

---

### Slide 2 — Problem
**On-slide**
- Manufacturing: manual registers, buddy punching, payroll delays
- School: parents unsure about entry/exit, gate process is slow

**Voiceover (15–25s)**
“In manufacturing, attendance is often slow and error-prone—manual registers, proxy attendance, and payroll delays. In schools, parents mainly want one thing: confidence. They want to know exactly when a student entered and exited the campus.”

---

### Slide 3 — Solution Overview
**On-slide**
- TapInX (Camera) for capture
- Web Dashboard for Admin/Vendor
- Real-time updates (live feed + instant events)
- Optimized for low bandwidth and fast check-in/out

**Voiceover (20–30s)**
“OpenVisionX uses an Android camera kiosk to capture attendance, a web dashboard to manage people and view reports, and real-time updates so events appear instantly. It’s designed to work smoothly even on limited bandwidth.”

---

### Slide 4 — How it works (simple)
**On-slide**
- Kiosk captures → backend stores attendance
- Web updates live (super admin/vendor dashboards)
- Parent mode: student number → live + history (no images for parents)

**Voiceover (20–30s)**
“Here’s the flow: the kiosk captures a face event, the backend stores the attendance record, and dashboards update live. For schools, there is a parent mode where a parent can enter a student number and see live and historical attendance—without needing student images shared to the parent side.”

---

### Slide 5 — Manufacturing / Daily Wages Module
**On-slide**
- Worker enrollment + employee directory
- Live attendance feed
- Department / designation tagging
- Wage/payroll-ready reports (daily/monthly)

**Voiceover (20–30s)**
“For manufacturing, you get worker enrollment, an employee directory, a live attendance feed for supervisors and HR, and reports that support wage and payroll workflows. You can organize data by department or designation.”

---

### Slide 6 — Manufacturing Live Demo (screen recording)
**On-slide**
- Login → People → Live Attendance → Reports
- Kiosk check-ins (2–3 workers)
- Instant updates on web

**Voiceover (10–15s)**
“Now I’ll show a quick live demo: we’ll enroll or select workers, capture check-ins on the kiosk, watch updates appear on the dashboard, and open the report view.”

**Demo steps (recording)**
1. Web: login as vendor/admin
2. Web: show People list (search/filter)
3. Web: open Live Attendance feed
4. Android: perform 2–3 check-ins / check-outs
5. Web: show instant entries arriving
6. Web: open Reports / Wages view and show totals for the day

---

### Slide 7 — School / Parents Module
**On-slide**
- Student enrollment: student number + class/section
- Gate check-in/out via face recognition
- Parent view: enter student number → today + history
- Optional push notifications

**Voiceover (20–30s)**
“For schools, enrollment supports student number and class or section fields. At the gate, check-in and check-out are captured quickly. Parents can enter a student number to see attendance and optionally receive notifications.”

---

### Slide 8 — School Live Demo (screen recording)
**On-slide**
- Student check-in + check-out
- Parent mode: live update + date filter

**Voiceover (10–15s)**
“Next, I’ll demo the school flow: a student check-in and check-out at the gate, and the parent view showing live updates and history.”

**Demo steps (recording)**
1. Android (kiosk): student check-in event
2. Parent mode screen: show live update appearing
3. Parent mode: open history with a date filter
4. Android (kiosk): student check-out event
5. Parent mode: show the check-out update

---

### Slide 9 — Security & Privacy
**On-slide**
- Role-based access (super admin / vendor admin / kiosk)
- Vendor data isolation
- Parent mode designed to be image-free

**Voiceover (20–30s)**
“Security is role-based, and each vendor’s data is separated. For schools, parent mode is designed for privacy—attendance updates can be shared without exposing student images to parents.”

---

### Slide 10 — Deployment + Next Steps
**On-slide**
- Cloud hosted or customer-hosted
- Pilot plan: 1 site, X devices, Y users
- What we need: headcount, shifts, departments/classes, reporting needs

**Voiceover (20–30s)**
“Deployment can be cloud hosted or customer hosted depending on policy. A typical pilot starts with one site and a few devices. To get started, we only need approximate headcount, shift structure or class structure, and what reports you want from day one.”

---

## Shot List (what to record)

Record these as separate clips so editing is easy:
- Clip A (10–15s): Title slide
- Clip B (20–30s): Problem slide
- Clip C (30–40s): Solution + architecture slide
- Clip D (2–3 min): Manufacturing demo (web + android)
- Clip E (2–3 min): School demo (android + parent view)
- Clip F (20–30s): Security & privacy slide
- Clip G (20–30s): Deployment & next steps slide

---

## On-screen Prep (make it look clean)

- Use demo identities only:
  - Workers: “Worker 001”, “Worker 002”
  - Students: “Student 1023”, “Student 1024”
- Use a fresh dataset with 5–10 people so screens look populated
- Browser zoom: 110–125% for readability
- Close all notifications (WhatsApp, email, etc.)
- Hide any developer tools and console logs

---

## Troubleshooting (common issues during demo)

- CORS error when web dashboard calls backend:
  - Ensure backend allows your dev origin (example: `http://localhost:5174`) and not only production domains.
  - Confirm backend URL in the web app points to the correct host/port.
- Live updates not showing:
  - Check that backend and Redis/Socket adapter are running (for multi-process setups).
  - Confirm the web client joined the correct vendor room and the kiosk is posting events successfully.
- Android not reaching backend:
  - Confirm phone and laptop are on same Wi‑Fi (for LAN demos).
  - Use the backend LAN IP and port in the Android server URL setting.

---

## Editing Template (simple)

Recommended structure in your editor:
- 0:00–0:15 Slide 1 (title)
- 0:15–0:45 Slides 2–4 (problem + overview + how it works)
- 0:45–3:30 Manufacturing demo (with a few captions)
- 3:30–6:00 School demo (with a few captions)
- 6:00–7:00 Slides 9–10 (security + deployment)
- 7:00–7:10 Outro (logo + contact)

