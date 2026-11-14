$content = [System.IO.File]::ReadAllText('c:\OpenVisionX\backend\routes\auth.py')

$old = '            is_kiosk_login = is_designated_kiosk_account(user, kiosk_username)' + "`n"

$kioskBlock = @'

            # ---- Kiosk platform: enforce authorised-account-only access ----
            # For all business types, a kiosk login must ONLY be permitted for
            # the designated operational account(s) configured by the Super Admin.
            # Students and other person-linked accounts are blocked here at the
            # API layer so the restriction cannot be bypassed by calling the API
            # directly.
            if locals().get('_needs_kiosk_validation') and not is_kiosk_login:
                # Allow vendor_admin and super_admin through on kiosk platform
                # (they may need to access settings or reconfigure the device).
                _kiosk_role = str(user.get('role') or '').strip().lower()
                if _kiosk_role not in {'vendor_admin', 'super_admin', 'admin'}:
                    conn.close()
                    return jsonify({
                        'error': (
                            'This account is not authorised to log in to the kiosk. '
                            'Only designated kiosk operator accounts are permitted.'
                        )
                    }), 403

'@

$new = '            is_kiosk_login = is_designated_kiosk_account(user, kiosk_username)' + "`n" + $kioskBlock

$updated = $content.Replace($old, $new)
if ($updated -eq $content) {
    Write-Host "ERROR: no replacement made"
} else {
    [System.IO.File]::WriteAllText('c:\OpenVisionX\backend\routes\auth.py', $updated, [System.Text.UTF8Encoding]::new($false))
    Write-Host "SUCCESS: auth.py kiosk enforcement added"
}
