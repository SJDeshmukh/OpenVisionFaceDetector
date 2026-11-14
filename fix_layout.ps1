$path = 'c:\OpenVisionX\web-dashboard\src\components\EnterpriseLayout.jsx'
$content = [System.IO.File]::ReadAllText($path)

$old = '  const navLabel = (item) => {' + "`r`n" +
'    if (item.path === ''/people'') return terminology.people;' + "`r`n" +
'    if (item.path === ''/classes'') return terminology.groups;' + "`r`n" +
'    return item.name;' + "`r`n" +
'  };'

$new = '  const navLabel = (item) => {' + "`r`n" +
'    if (item.path === ''/people'') return terminology.people;' + "`r`n" +
'    if (item.path === ''/classes'') return terminology.groups;' + "`r`n" +
'    if (item.path === ''/leave-management'' && terminology.leaveManagement) return terminology.leaveManagement;' + "`r`n" +
'    if (item.path === ''/attendance'' && terminology.attendance) return terminology.attendance;' + "`r`n" +
'    if (item.path === ''/dashboard'' && terminology.dashboard) return terminology.dashboard;' + "`r`n" +
'    return item.name;' + "`r`n" +
'  };'

$updated = $content.Replace($old, $new)
if ($updated -eq $content) {
    # Try LF
    $old_lf = '  const navLabel = (item) => {' + "`n" +
    '    if (item.path === ''/people'') return terminology.people;' + "`n" +
    '    if (item.path === ''/classes'') return terminology.groups;' + "`n" +
    '    return item.name;' + "`n" +
    '  };'
    $new_lf = '  const navLabel = (item) => {' + "`n" +
    '    if (item.path === ''/people'') return terminology.people;' + "`n" +
    '    if (item.path === ''/classes'') return terminology.groups;' + "`n" +
    '    if (item.path === ''/leave-management'' && terminology.leaveManagement) return terminology.leaveManagement;' + "`n" +
    '    if (item.path === ''/attendance'' && terminology.attendance) return terminology.attendance;' + "`n" +
    '    if (item.path === ''/dashboard'' && terminology.dashboard) return terminology.dashboard;' + "`n" +
    '    return item.name;' + "`n" +
    '  };'
    $updated = $content.Replace($old_lf, $new_lf)
}

if ($updated -eq $content) {
    Write-Host "ERROR: could not update EnterpriseLayout.jsx"
} else {
    [System.IO.File]::WriteAllText($path, $updated, [System.Text.UTF8Encoding]::new($false))
    Write-Host "SUCCESS: EnterpriseLayout.jsx updated"
}
