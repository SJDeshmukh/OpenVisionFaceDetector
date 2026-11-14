const fs = require('fs');
let content = fs.readFileSync('web-dashboard/src/pages/Dashboard.jsx', 'utf8');

function normalize(s) { return s.replace(/\r\n/g, '\n'); }
let norm = normalize(content);

// 1. Update newStats
const targetStats = `        const newStats = {
          total: schoolFlow ? (summary.total_students ?? summary.total_users) : summary.total_users,
          present: summary.present_today,
          absent: summary.absent_today,
          late: summary.late_today,
          overdue_leaves_count: summary.overdue_leaves_count || 0,
          activeCameras: 1
        };`;

const replaceStats = `        const newStats = {
          total: schoolFlow ? (summary.total_students ?? summary.total_users) : summary.total_users,
          present: summary.present_today,
          absent: summary.absent_today,
          late: summary.late_today,
          inside_today: summary.inside_today ?? summary.present_today ?? 0,
          outside_today: summary.outside_today ?? summary.absent_today ?? 0,
          pending_leaves_count: summary.pending_leaves_count || 0,
          approved_leaves_count: summary.approved_leaves_count || 0,
          rejected_leaves_count: summary.rejected_leaves_count || 0,
          overdue_leaves_count: summary.overdue_leaves_count || 0,
          activeCameras: 1
        };`;

// 2. Header
const targetHeader = `      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Dashboard</h1>
          <p className="text-slate-500">Welcome back, here's your overview.</p>
        </div>`;

const replaceHeader = `      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{isHostel ? "Hostel Operations Dashboard" : "Dashboard"}</h1>
          <p className="text-slate-500">{isHostel ? "Live resident movement, leave tracking & occupancy overview." : "Welcome back, here's your overview."}</p>
        </div>`;

// 3. Overdue Banner
const targetBanner = `            <div>
              <h3 className="font-bold text-lg">Leave Return Alerts</h3>
              <p className="text-sm text-amber-700/80">
                {stats.overdue_leaves_count} {stats.overdue_leaves_count === 1 ? personLabel : peopleLabel} {stats.overdue_leaves_count === 1 ? 'has' : 'have'} not returned after their approved leave ended.
              </p>
            </div>`;

const replaceBanner = `            <div>
              <h3 className="font-bold text-lg">{isHostel ? "Overdue Return Alerts" : "Leave Return Alerts"}</h3>
              <p className="text-sm text-amber-700/80">
                {stats.overdue_leaves_count} {stats.overdue_leaves_count === 1 ? personLabel : peopleLabel} {stats.overdue_leaves_count === 1 ? 'has' : 'have'} not returned to hostel after their approved leave ended.
              </p>
            </div>`;

// 4. KPI cards
const targetCards = `          {/* KPI Cards */}
          <div className={\`grid grid-cols-1 md:grid-cols-2 \${lateMarkEnabled ? 'lg:grid-cols-4' : 'lg:grid-cols-3'} gap-6\`}>
            <KpiCard
              title={\`Total \${peopleLabel}\`}
              value={stats.total}
              subtext="Registered in system"
              icon={Users}
              color="bg-blue-600"
            />
            <KpiCard
              title="Present Today"
              value={stats.present}
              subtext={\`\${((stats.present / (stats.total || 1)) * 100).toFixed(0)}% attendance rate\`}
              icon={UserCheck}
              color="bg-green-500"
            />
            <KpiCard
              title="Absent Today"
              value={stats.absent}
              subtext="Unaccounted for"
              icon={UserX}
              color="bg-red-500"
            />
            {lateMarkEnabled && (
              <KpiCard
                title="Late Arrivals"
                value={stats.late}
                subtext="Exceeded grace period"
                icon={Clock}
                color="bg-amber-500"
              />
            )}
          </div>`;

const replaceCards = `          {/* KPI Cards */}
          {isHostel ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-6">
              <KpiCard
                title="Total Residents"
                value={stats.total}
                subtext="Registered in hostel"
                icon={Users}
                color="bg-indigo-600"
              />
              <KpiCard
                title="Inside Hostel"
                value={stats.inside_today ?? stats.present}
                subtext={\`\${(((stats.inside_today ?? stats.present) / (stats.total || 1)) * 100).toFixed(0)}% in premises\`}
                icon={UserCheck}
                color="bg-emerald-600"
              />
              <KpiCard
                title="Outside Hostel"
                value={stats.outside_today ?? stats.absent}
                subtext="Off-campus / On leave"
                icon={UserX}
                color="bg-sky-600"
              />
              <KpiCard
                title="Leave Pending"
                value={stats.pending_leaves_count || 0}
                subtext="Awaiting admin approval"
                icon={Clock}
                color="bg-amber-500"
              />
              <KpiCard
                title="Overdue Return"
                value={stats.overdue_leaves_count || 0}
                subtext="Exceeded expected return"
                icon={AlertTriangle}
                color="bg-rose-600"
              />
            </div>
          ) : (
            <div className={\`grid grid-cols-1 md:grid-cols-2 \${lateMarkEnabled ? 'lg:grid-cols-4' : 'lg:grid-cols-3'} gap-6\`}>
              <KpiCard
                title={\`Total \${peopleLabel}\`}
                value={stats.total}
                subtext="Registered in system"
                icon={Users}
                color="bg-blue-600"
              />
              <KpiCard
                title="Present Today"
                value={stats.present}
                subtext={\`\${((stats.present / (stats.total || 1)) * 100).toFixed(0)}% attendance rate\`}
                icon={UserCheck}
                color="bg-green-500"
              />
              <KpiCard
                title="Absent Today"
                value={stats.absent}
                subtext="Unaccounted for"
                icon={UserX}
                color="bg-red-500"
              />
              {lateMarkEnabled && (
                <KpiCard
                  title="Late Arrivals"
                  value={stats.late}
                  subtext="Exceeded grace period"
                  icon={Clock}
                  color="bg-amber-500"
                />
              )}
            </div>
          )}`;

// 5. Chart title
const targetChartTitle = `<h3 className="text-lg font-bold text-slate-800 mb-6">Attendance Trend (Last 7 Days)</h3>`;
const replaceChartTitle = `<h3 className="text-lg font-bold text-slate-800 mb-6">{isHostel ? "Hostel Occupancy & Movement Trend (Last 7 Days)" : "Attendance Trend (Last 7 Days)"}</h3>`;

if (!norm.includes(normalize(targetStats))) { console.error("targetStats missing"); process.exit(1); }
if (!norm.includes(normalize(targetHeader))) { console.error("targetHeader missing"); process.exit(1); }
if (!norm.includes(normalize(targetBanner))) { console.error("targetBanner missing"); process.exit(1); }
if (!norm.includes(normalize(targetCards))) { console.error("targetCards missing"); process.exit(1); }
if (!norm.includes(normalize(targetChartTitle))) { console.error("targetChartTitle missing"); process.exit(1); }

norm = norm.replace(normalize(targetStats), normalize(replaceStats));
norm = norm.replace(normalize(targetHeader), normalize(replaceHeader));
norm = norm.replace(normalize(targetBanner), normalize(replaceBanner));
norm = norm.replace(normalize(targetCards), normalize(replaceCards));
norm = norm.replace(normalize(targetChartTitle), normalize(replaceChartTitle));

fs.writeFileSync('web-dashboard/src/pages/Dashboard.jsx', norm, 'utf8');
console.log("Successfully updated Dashboard.jsx");
