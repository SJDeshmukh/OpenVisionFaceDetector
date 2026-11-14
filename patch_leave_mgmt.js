const fs = require('fs');
let content = fs.readFileSync('web-dashboard/src/pages/LeaveManagement.jsx', 'utf8');

function normalize(s) { return s.replace(/\r\n/g, '\n'); }
let norm = normalize(content);

// 1. Import
const targetImport = "import { getBusinessTerminology, usesStudentRecords } from '../lib/businessTerminology';";
const replaceImport = "import { getBusinessTerminology, usesStudentRecords, isHostelVertical } from '../lib/businessTerminology';";

// 2. Define isHostel
const targetHostel = `  const isStudentFlow = usesStudentRecords(user?.vertical);`;
const replaceHostel = `  const isStudentFlow = usesStudentRecords(user?.vertical);
  const isHostel = isHostelVertical(user?.vertical);`;

// 3. Page Header
const targetHeader = `          <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <ShieldCheck className="text-blue-600" />
            Leave Management
          </h1>
          <p className="text-slate-500">
            {isRegularUser
              ? (isStudentFlow ? "Apply for campus leave and view your status." : "Submit and track employee leave requests.")
              : (isStudentFlow ? "Review and approve student leave permissions." : "Review and approve employee leave requests.")}
          </p>`;

const replaceHeader = `          <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <ShieldCheck className="text-blue-600" />
            {isHostel ? "Leave & Gate Pass Management" : "Leave Management"}
          </h1>
          <p className="text-slate-500">
            {isRegularUser
              ? (isHostel ? "Apply for hostel leave/gate pass and view approval status." : isStudentFlow ? "Apply for campus leave and view your status." : "Submit and track employee leave requests.")
              : (isHostel ? "Review and approve resident leave requests and gate passes." : isStudentFlow ? "Review and approve student leave permissions." : "Review and approve employee leave requests.")}
          </p>`;

// 4. Tabs
const targetTabs = `              <button
                onClick={() => setActiveTab('tracking')}
                className={\`px-4 py-2 rounded-md text-sm font-medium transition-colors \${activeTab === 'tracking' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}\`}
              >
                Leave Tracking
              </button>
              {isStudentFlow && (
                <button
                  onClick={() => setActiveTab('parents')}
                  className={\`px-4 py-2 rounded-md text-sm font-medium transition-colors \${activeTab === 'parents' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}\`}
                >
                  Parent Validation
                </button>
              )}`;

const replaceTabs = `              <button
                onClick={() => setActiveTab('tracking')}
                className={\`px-4 py-2 rounded-md text-sm font-medium transition-colors \${activeTab === 'tracking' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}\`}
              >
                {isHostel ? "Gate Pass Tracking" : "Leave Tracking"}
              </button>
              {isStudentFlow && (
                <button
                  onClick={() => setActiveTab('parents')}
                  className={\`px-4 py-2 rounded-md text-sm font-medium transition-colors \${activeTab === 'parents' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}\`}
                >
                  {isHostel ? "Parent Verification" : "Parent Validation"}
                </button>
              )}`;

if (!norm.includes(normalize(targetImport))) { console.error("targetImport missing"); process.exit(1); }
if (!norm.includes(normalize(targetHostel))) { console.error("targetHostel missing"); process.exit(1); }
if (!norm.includes(normalize(targetHeader))) { console.error("targetHeader missing"); process.exit(1); }
if (!norm.includes(normalize(targetTabs))) { console.error("targetTabs missing"); process.exit(1); }

norm = norm.replace(normalize(targetImport), normalize(replaceImport));
norm = norm.replace(normalize(targetHostel), normalize(replaceHostel));
norm = norm.replace(normalize(targetHeader), normalize(replaceHeader));
norm = norm.replace(normalize(targetTabs), normalize(replaceTabs));

fs.writeFileSync('web-dashboard/src/pages/LeaveManagement.jsx', norm, 'utf8');
console.log("Successfully updated LeaveManagement.jsx");
