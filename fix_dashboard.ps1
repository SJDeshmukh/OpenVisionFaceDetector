$path = 'c:\OpenVisionX\web-dashboard\src\pages\Dashboard.jsx'
$content = [System.IO.File]::ReadAllText($path)

# Update imports
$old_import = "import { getBusinessTerminology, usesStudentRecords } from '../lib/businessTerminology';"
$new_import = "import { getBusinessTerminology, usesStudentRecords, isHostelVertical } from '../lib/businessTerminology';"

$content = $content.Replace($old_import, $new_import)

# Update const declarations
$old_const = "  const schoolFlow = usesStudentRecords(user?.vertical);`r`n  const lateMarkEnabled = user?.features?.includes('late_mark');"
$new_const = "  const schoolFlow = usesStudentRecords(user?.vertical);`r`n  const isHostel = isHostelVertical(user?.vertical);`r`n  const lateMarkEnabled = user?.features?.includes('late_mark');"

$content = $content.Replace($old_const, $new_const)

# Update newStats
$old_newstats = @'
        const newStats = {
          total: schoolFlow ? (summary.total_students ?? summary.total_users) : summary.total_users,
          present: summary.present_today,
          absent: summary.absent_today,
          late: summary.late_today,
          overdue_leaves_count: summary.overdue_leaves_count || 0,
          activeCameras: 1
        };
'@

$new_newstats = @'
        const newStats = {
          total: schoolFlow ? (summary.total_students ?? summary.total_users) : summary.total_users,
          present: summary.present_today,
          absent: summary.absent_today,
          late: summary.late_today,
          overdue_leaves_count: summary.overdue_leaves_count || 0,
          pending_leaves: summary.pending_leaves_count || 0,
          approved_leaves: summary.approved_leaves_count || 0,
          rejected_leaves: summary.rejected_leaves_count || 0,
          activeCameras: 1
        };
'@

$content = $content.Replace($old_newstats.Replace("`r`n", "`n"), $new_newstats.Replace("`r`n", "`n"))
$content = $content.Replace($old_newstats, $new_newstats)

# Update heading
$old_heading = @'
          <h1 className="text-2xl font-bold text-slate-800">Dashboard</h1>
          <p className="text-slate-500">Welcome back, here's your overview.</p>
'@

$new_heading = @'
          <h1 className="text-2xl font-bold text-slate-800">
            {isHostel ? 'Hostel Operations Dashboard' : (terminology.dashboard || 'Dashboard')}
          </h1>
          <p className="text-slate-500">
            {isHostel ? 'Hostel occupancy, residents movement, and gate pass management overview.' : "Welcome back, here's your overview."}
          </p>
'@

$content = $content.Replace($old_heading.Replace("`r`n", "`n"), $new_heading.Replace("`r`n", "`n"))
$content = $content.Replace($old_heading, $new_heading)

# Update KPI Cards
$old_kpi = @'
          {/* KPI Cards */}
          <div className={`grid grid-cols-1 md:grid-cols-2 ${lateMarkEnabled ? 'lg:grid-cols-4' : 'lg:grid-cols-3'} gap-6`}>
            <KpiCard
              title={`Total ${peopleLabel}`}
              value={stats.total}
              subtext="Registered in system"
              icon={Users}
              color="bg-blue-600"
            />
            <KpiCard
              title="Present Today"
              value={stats.present}
              subtext={`${((stats.present / (stats.total || 1)) * 100).toFixed(0)}% attendance rate`}
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
'@

$new_kpi = @'
          {/* KPI Cards */}
          {isHostel ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6">
              <KpiCard
                title="Total Residents"
                value={stats.total}
                subtext="Registered in hostel"
                icon={Users}
                color="bg-blue-600"
              />
              <KpiCard
                title="Inside Hostel"
                value={stats.present}
                subtext={`${((stats.present / (stats.total || 1)) * 100).toFixed(0)}% currently inside`}
                icon={UserCheck}
                color="bg-green-600"
              />
              <KpiCard
                title="Outside Hostel"
                value={stats.absent}
                subtext="Outside / on leave"
                icon={UserX}
                color="bg-blue-500"
              />
              <KpiCard
                title="Leave Pending"
                value={stats.pending_leaves || 0}
                subtext="Awaiting admin approval"
                icon={Clock}
                color="bg-amber-500"
              />
              <KpiCard
                title="Overdue Return"
                value={stats.overdue_leaves_count || 0}
                subtext="Expected return passed"
                icon={AlertTriangle}
                color="bg-red-500"
              />
            </div>
          ) : (
            <div className={`grid grid-cols-1 md:grid-cols-2 ${lateMarkEnabled ? 'lg:grid-cols-4' : 'lg:grid-cols-3'} gap-6`}>
              <KpiCard
                title={`Total ${peopleLabel}`}
                value={stats.total}
                subtext="Registered in system"
                icon={Users}
                color="bg-blue-600"
              />
              <KpiCard
                title="Present Today"
                value={stats.present}
                subtext={`${((stats.present / (stats.total || 1)) * 100).toFixed(0)}% attendance rate`}
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
          )}
'@

$content = $content.Replace($old_kpi.Replace("`r`n", "`n"), $new_kpi.Replace("`r`n", "`n"))
$content = $content.Replace($old_kpi, $new_kpi)

[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
Write-Host "SUCCESS: Dashboard.jsx updated with hostel KPI cards and terminology"
