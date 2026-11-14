const fs = require('fs');
let content = fs.readFileSync('backend/services/leave_workflow_service.py', 'utf8');
const target = 'if actor_type == "staff" and stage["role_key"] != role_key:';
const replacement = 'if actor_type == "staff" and stage["role_key"] != role_key and role_key not in ("admin", "vendor_admin", "owner", "super_admin"):';
if (!content.includes(target)) {
  console.error('Target not found!');
  process.exit(1);
}
content = content.replace(target, replacement);
fs.writeFileSync('backend/services/leave_workflow_service.py', content, 'utf8');
console.log('Successfully updated leave_workflow_service.py');
