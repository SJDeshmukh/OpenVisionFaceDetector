const fs = require('fs');
let content = fs.readFileSync('backend/routes/auth.py', 'utf8');

const target1 = `    if pass_condition:
        is_student_mobile_login = user.get("role") == "student"
        if (
            not is_student_mobile_login
            and user.get("role") == "user"
            and user.get("person_id")
            and platform.lower() in {"mobile", "kiosk"}
        ):`;

const replacement1 = `    if pass_condition:
        is_student_mobile_login = user.get("role") in {"student", "resident"}
        app_type = (data.get('app_type', '') if data else '').strip().lower()
        _is_kiosk_request = platform.lower() == "kiosk" or app_type == "tapinx"
        if (
            not is_student_mobile_login
            and user.get("role") in {"user", "student", "resident"}
            and user.get("person_id")
            and (platform.lower() in {"mobile", "kiosk"} or _is_kiosk_request)
        ):`;

const target2 = `        if platform.lower() in {"mobile", "kiosk"} and is_student_mobile_login:
            return jsonify({"error": "Student accounts must use the Parent Portal, not kiosk login"}), 403

        # Hostel kiosk security: on the kiosk platform, only accounts that are
        # explicitly designated as kiosk accounts may proceed. This prevents
        # students or other person-linked accounts from logging into the kiosk
        # via a direct API call even if the front-end hides the option.
        # The actual kiosk-designation check is performed below, after the
        # vendor row has been fetched and kiosk_username is known.
        _needs_kiosk_validation = platform.lower() == "kiosk"`;

const replacement2 = `        if (_is_kiosk_request or platform.lower() in {"mobile", "kiosk"}) and is_student_mobile_login:
            return jsonify({"error": "Student and resident accounts are not permitted to log in at the kiosk level."}), 403

        # Hostel kiosk security: on the kiosk platform or TapinX kiosk app, only accounts that are
        # explicitly designated as kiosk accounts or administrators may proceed. This prevents
        # students or unauthorized accounts from logging into the kiosk
        # via a direct API call even if the front-end hides the option.
        # The actual kiosk-designation check is performed below, after the
        # vendor row has been fetched and kiosk_username is known.
        _needs_kiosk_validation = _is_kiosk_request`;

const target3 = `                _kiosk_role = str(user.get('role') or '').strip().lower()
                if _kiosk_role not in {'vendor_admin', 'super_admin', 'admin'}:`;

const replacement3 = `                _kiosk_role = str(user.get('role') or '').strip().lower()
                if _kiosk_role not in {'vendor_admin', 'super_admin', 'admin', 'owner'}:`;

function normalize(s) { return s.replace(/\r\n/g, '\n'); }

let normContent = normalize(content);
if (!normContent.includes(normalize(target1))) {
    console.error("target1 not found");
    process.exit(1);
}
if (!normContent.includes(normalize(target2))) {
    console.error("target2 not found");
    process.exit(1);
}
if (!normContent.includes(normalize(target3))) {
    console.error("target3 not found");
    process.exit(1);
}

normContent = normContent.replace(normalize(target1), normalize(replacement1));
normContent = normContent.replace(normalize(target2), normalize(replacement2));
normContent = normContent.replace(normalize(target3), normalize(replacement3));

fs.writeFileSync('backend/routes/auth.py', normContent, 'utf8');
console.log("Successfully patched auth.py kiosk validations");
