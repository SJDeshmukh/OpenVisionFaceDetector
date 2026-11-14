const fs = require('fs');

const files = [
  'backend/routes/auth.py',
  'backend/routes/faces.py',
  'backend/routes/attendance_reports.py',
  'backend/routes/leave_routes.py',
  'backend/services/leave_workflow_service.py'
];

let hasErrors = false;

for (const f of files) {
  const content = fs.readFileSync(f, 'utf8');
  const lines = content.split(/\r?\n/);
  let stack = [];
  let inMultiDouble = false;
  let inMultiSingle = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    if (trimmed.startsWith('#')) continue;

    // Check for obvious balance issues
    for (let c = 0; c < line.length; c++) {
      const ch = line[c];
      const next3 = line.slice(c, c + 3);
      if (next3 === '"""') {
        inMultiDouble = !inMultiDouble;
        c += 2;
        continue;
      }
      if (next3 === "'''") {
        inMultiSingle = !inMultiSingle;
        c += 2;
        continue;
      }
      if (inMultiDouble || inMultiSingle) continue;
      if (ch === '#') break; // rest is comment

      if (ch === '(' || ch === '[' || ch === '{') {
        stack.push({ ch, line: i + 1 });
      } else if (ch === ')' || ch === ']' || ch === '}') {
        const last = stack.pop();
        if (!last) {
          console.error(`Unmatched ${ch} at ${f}:${i + 1}`);
          hasErrors = true;
        } else if (
          (ch === ')' && last.ch !== '(') ||
          (ch === ']' && last.ch !== '[') ||
          (ch === '}' && last.ch !== '{')
        ) {
          console.error(`Mismatched ${last.ch} (line ${last.line}) and ${ch} (line ${i + 1}) in ${f}`);
          hasErrors = true;
        }
      }
    }
  }

  if (stack.length > 0) {
    console.error(`Unclosed brackets in ${f}:`, stack);
    hasErrors = true;
  }
}

if (!hasErrors) {
  console.log("All modified Python files passed bracket and structure verification!");
} else {
  process.exit(1);
}
