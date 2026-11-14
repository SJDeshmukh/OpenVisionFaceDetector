$content = [System.IO.File]::ReadAllText('c:\OpenVisionX\backend\routes\faces.py')

$old1 = '            email_cursor.execute(' + "`n" + '                "SELECT username FROM system_users WHERE LOWER(username) = LOWER(?) AND (? IS NULL OR person_id <> ?)",' + "`n" + '                (profile_email, person_id, person_id),' + "`n" + '            )'

$new1 = '            email_cursor.execute(' + "`n" + '                "SELECT username FROM system_users WHERE LOWER(username) = LOWER(?) AND (? IS NULL OR person_id IS NULL OR person_id <> ?)",' + "`n" + '                (profile_email, person_id, person_id),' + "`n" + '            )'

$updated = $content.Replace($old1, $new1)
if ($updated -eq $content) {
    Write-Host "Trying with \r\n line endings..."
    $old1_crlf = '            email_cursor.execute(' + "`r`n" + '                "SELECT username FROM system_users WHERE LOWER(username) = LOWER(?) AND (? IS NULL OR person_id <> ?)",' + "`r`n" + '                (profile_email, person_id, person_id),' + "`r`n" + '            )'
    $new1_crlf = '            email_cursor.execute(' + "`r`n" + '                "SELECT username FROM system_users WHERE LOWER(username) = LOWER(?) AND (? IS NULL OR person_id IS NULL OR person_id <> ?)",' + "`r`n" + '                (profile_email, person_id, person_id),' + "`r`n" + '            )'
    $updated = $content.Replace($old1_crlf, $new1_crlf)
}

if ($updated -eq $content) {
    Write-Host "ERROR: could not replace email validation check in faces.py"
} else {
    # Also add rollback to outer exception handler
    $old_except = '    except Exception as e:' + "`n" + '        return jsonify({"error": str(e)}), 500'
    $new_except = '    except Exception as e:' + "`n" + '        if getattr(conn, "_is_pg", False):' + "`n" + '            try: conn.rollback()' + "`n" + '            except Exception: pass' + "`n" + '        return jsonify({"error": str(e)}), 500'
    $updated2 = $updated.Replace($old_except, $new_except)
    if ($updated2 -eq $updated) {
        $old_except_crlf = '    except Exception as e:' + "`r`n" + '        return jsonify({"error": str(e)}), 500'
        $new_except_crlf = '    except Exception as e:' + "`r`n" + '        if getattr(conn, "_is_pg", False):' + "`r`n" + '            try: conn.rollback()' + "`r`n" + '            except Exception: pass' + "`r`n" + '        return jsonify({"error": str(e)}), 500'
        $updated2 = $updated.Replace($old_except_crlf, $new_except_crlf)
    }
    
    [System.IO.File]::WriteAllText('c:\OpenVisionX\backend\routes\faces.py', $updated2, [System.Text.UTF8Encoding]::new($false))
    Write-Host "SUCCESS: faces.py validation and rollback updated"
}
