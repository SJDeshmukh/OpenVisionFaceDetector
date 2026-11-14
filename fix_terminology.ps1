$content = [System.IO.File]::ReadAllText('c:\OpenVisionX\web-dashboard\src\lib\businessTerminology.js')

$old = @'
  hostel: {
    person: 'Resident',
    people: 'Residents',
    group: 'Room',
    groups: 'Rooms',
    section: 'Block',
    staff: 'Warden',
    staffPlural: 'Wardens',
    groupedPeople: true,
    // The API stores hostel residents as the legacy `student` person type.
    studentRecords: true,
    academic: false,
  },
'@

$new = @'
  hostel: {
    person: 'Resident',
    people: 'Residents',
    group: 'Room',
    groups: 'Rooms',
    section: 'Block',
    staff: 'Warden',
    staffPlural: 'Wardens',
    groupedPeople: true,
    // The API stores hostel residents as the legacy `student` person type.
    studentRecords: true,
    academic: false,
    // Hostel-specific extended terminology used by hostel-aware components.
    registration: 'Resident Registration',
    attendance: 'Hostel Attendance',
    checkIn: 'Hostel Entry',
    checkOut: 'Hostel Exit',
    present: 'Inside Hostel',
    absent: 'Outside Hostel',
    insideLabel: 'Inside Hostel',
    outsideLabel: 'Outside Hostel',
    leaveManagement: 'Leave & Gate Pass Management',
    attendanceDashboard: 'Hostel Operations Dashboard',
  },
'@

$updated = $content.Replace($old, $new)
if ($updated -eq $content) {
    Write-Host "ERROR: no replacement made"
    # Debug: show what we have
    $idx = $content.IndexOf("  hostel: {")
    Write-Host "hostel block at index: $idx"
    Write-Host $content.Substring($idx, 400)
} else {
    [System.IO.File]::WriteAllText('c:\OpenVisionX\web-dashboard\src\lib\businessTerminology.js', $updated, [System.Text.UTF8Encoding]::new($false))
    Write-Host "SUCCESS: businessTerminology.js updated"
}
