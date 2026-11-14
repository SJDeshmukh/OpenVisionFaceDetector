const fs = require('fs');
let content = fs.readFileSync('web-dashboard/src/pages/Attendance.jsx', 'utf8');

function normalize(s) { return s.replace(/\r\n/g, '\n'); }
let norm = normalize(content);

// 1. Import
const targetImport = "import { getBusinessTerminology, usesStudentRecords } from '../lib/businessTerminology';";
const replaceImport = "import { getBusinessTerminology, usesStudentRecords, isHostelVertical } from '../lib/businessTerminology';";

// 2. Define isHostel
const targetHostel = `  const schoolFlow = usesStudentRecords(user?.vertical);`;
const replaceHostel = `  const schoolFlow = usesStudentRecords(user?.vertical);
  const isHostel = isHostelVertical(user?.vertical);`;

// 3. getStatus
const targetStatus = `  const getStatus = (log) => {
    if (!lateMarkEnabled) {`;

const replaceStatus = `  const getStatus = (log) => {
    if (isHostel) {
      if (log.status === 'CHECK_OUT') {
        return { label: 'Hostel Exit', color: 'bg-sky-100 text-sky-800' };
      }
      return { label: 'Hostel Entry', color: 'bg-emerald-100 text-emerald-800' };
    }

    if (!lateMarkEnabled) {`;

// 4. Header title & subtext
const targetHead = `          <h1 className="text-2xl font-bold text-slate-800">{isRegularUser ? "My Attendance" : "Attendance Logs"}</h1>
          <p className="text-slate-500">{isRegularUser ? "View your personal punch logs and attendance history." : \`Track \${personLabel.toLowerCase()} check-ins and movements.\`}</p>`;

const replaceHead = `          <h1 className="text-2xl font-bold text-slate-800">
            {isRegularUser ? "My Attendance" : (isHostel ? "Hostel Attendance Logs" : "Attendance Logs")}
          </h1>
          <p className="text-slate-500">
            {isRegularUser ? "View your personal punch logs and attendance history." : (isHostel ? "Track resident entries, exits, and gate movements." : \`Track \${personLabel.toLowerCase()} check-ins and movements.\`)}
          </p>`;

// 5. Table Header Activity
const targetTh = `<th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Activity</th>`;
const replaceTh = `<th className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">{isHostel ? 'Movement' : 'Activity'}</th>`;

// 6. Table Cell Activity
const targetTd = `{log.activity || 'Work'}{log.activity === 'Lecture' && log.subject ? \`: \${log.subject}\` : ''}`;
const replaceTd = `{log.activity || (isHostel ? 'Hostel Movement' : 'Work')}{log.activity === 'Lecture' && log.subject ? \`: \${log.subject}\` : ''}`;

if (!norm.includes(normalize(targetImport))) { console.error("targetImport missing"); process.exit(1); }
if (!norm.includes(normalize(targetHostel))) { console.error("targetHostel missing"); process.exit(1); }
if (!norm.includes(normalize(targetStatus))) { console.error("targetStatus missing"); process.exit(1); }
if (!norm.includes(normalize(targetHead))) { console.error("targetHead missing"); process.exit(1); }
if (!norm.includes(normalize(targetTh))) { console.error("targetTh missing"); process.exit(1); }
if (!norm.includes(normalize(targetTd))) { console.error("targetTd missing"); process.exit(1); }

norm = norm.replace(normalize(targetImport), normalize(replaceImport));
norm = norm.replace(normalize(targetHostel), normalize(replaceHostel));
norm = norm.replace(normalize(targetStatus), normalize(replaceStatus));
norm = norm.replace(normalize(targetHead), normalize(replaceHead));
norm = norm.replace(normalize(targetTh), normalize(replaceTh));
norm = norm.replace(normalize(targetTd), normalize(replaceTd));

fs.writeFileSync('web-dashboard/src/pages/Attendance.jsx', norm, 'utf8');
console.log("Successfully updated Attendance.jsx");
