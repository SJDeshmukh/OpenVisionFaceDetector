$path = 'c:\OpenVisionX\backend\routes\attendance_reports.py'
$content = [System.IO.File]::ReadAllText($path)

$search = "    result = {"
$idx = $content.IndexOf($search)

$before = $content.Substring(0, $idx)
$after = $content.Substring($idx)

$insert = @'
    overdue_leaves_count = 0
    pending_leaves_count = 0
    approved_leaves_count = 0
    rejected_leaves_count = 0
    try:
        is_pg = getattr(conn, "_is_pg", False)
        today_iso = date.today().isoformat()
        if is_pg:
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = %s AND final_status = 'pending'", (vendor_id,))
            pending_leaves_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = %s AND final_status = 'approved'", (vendor_id,))
            approved_leaves_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = %s AND final_status = 'rejected'", (vendor_id,))
            rejected_leaves_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = %s AND final_status = 'approved' AND end_date < %s", (vendor_id, today_iso))
            overdue_leaves_count = c.fetchone()[0] or 0
        else:
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = ? AND final_status = 'pending'", (vendor_id,))
            pending_leaves_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = ? AND final_status = 'approved'", (vendor_id,))
            approved_leaves_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = ? AND final_status = 'rejected'", (vendor_id,))
            rejected_leaves_count = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM leave_requests WHERE vendor_id = ? AND final_status = 'approved' AND end_date < ?", (vendor_id, today_iso))
            overdue_leaves_count = c.fetchone()[0] or 0
    except Exception:
        pass

'@

$insert_crlf = $insert.Replace("`n", "`r`n")

# In $after, also add fields into summary
$summary_search = '"late_today": late_today,'
$summary_replace = '"late_today": late_today,' + "`r`n" +
'            "inside_today": present_today,' + "`r`n" +
'            "outside_today": absent_today,' + "`r`n" +
'            "overdue_leaves_count": overdue_leaves_count,' + "`r`n" +
'            "pending_leaves_count": pending_leaves_count,' + "`r`n" +
'            "approved_leaves_count": approved_leaves_count,' + "`r`n" +
'            "rejected_leaves_count": rejected_leaves_count,'

$after_modified = $after.Replace($summary_search, $summary_replace)

$final = $before + $insert_crlf + $after_modified
[System.IO.File]::WriteAllText($path, $final, [System.Text.UTF8Encoding]::new($false))
Write-Host "SUCCESS: attendance_reports.py updated with leave metrics"
