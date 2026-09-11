const normalizeVertical = (vertical) => String(vertical || '').trim().toLowerCase();

const PROFILES = {
  school: {
    person: 'Student',
    people: 'Students',
    group: 'Class',
    groups: 'Classes',
    section: 'Section',
    staff: 'Faculty',
    staffPlural: 'Faculty',
    groupedPeople: true,
    studentRecords: true,
    academic: true,
  },
  college: {
    person: 'Student',
    people: 'Students',
    group: 'Class',
    groups: 'Classes',
    section: 'Section',
    staff: 'Faculty',
    staffPlural: 'Faculty',
    groupedPeople: true,
    studentRecords: true,
    academic: true,
  },
  tuition: {
    person: 'Student',
    people: 'Students',
    group: 'Batch',
    groups: 'Batches',
    section: 'Group',
    staff: 'Teacher',
    staffPlural: 'Teachers',
    groupedPeople: true,
    studentRecords: true,
    academic: true,
  },
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
  daily_wages: {
    person: 'Employee',
    people: 'Employees',
    group: 'Department',
    groups: 'Departments',
    section: 'Team',
    staff: 'Supervisor',
    staffPlural: 'Supervisors',
    groupedPeople: false,
    studentRecords: false,
    academic: false,
  },
  wages: {
    person: 'Employee',
    people: 'Employees',
    group: 'Department',
    groups: 'Departments',
    section: 'Team',
    staff: 'Supervisor',
    staffPlural: 'Supervisors',
    groupedPeople: false,
    studentRecords: false,
    academic: false,
  },
  factory: {
    person: 'Employee',
    people: 'Employees',
    group: 'Department',
    groups: 'Departments',
    section: 'Team',
    staff: 'Supervisor',
    staffPlural: 'Supervisors',
    groupedPeople: false,
    studentRecords: false,
    academic: false,
  },
};

const DEFAULT_PROFILE = {
  person: 'Employee',
  people: 'Employees',
  group: 'Department',
  groups: 'Departments',
  section: 'Team',
  staff: 'Staff',
  staffPlural: 'Staff',
  groupedPeople: false,
  studentRecords: false,
  academic: false,
};

export const getBusinessTerminology = (vertical) => ({
  ...DEFAULT_PROFILE,
  ...(PROFILES[normalizeVertical(vertical)] || {}),
  vertical: normalizeVertical(vertical),
});

export const usesStudentRecords = (vertical) => getBusinessTerminology(vertical).studentRecords;

const preserveCase = (source, replacement) => {
  if (source === source.toUpperCase()) return replacement.toUpperCase();
  if (source[0] === source[0].toUpperCase()) return replacement;
  return replacement.toLowerCase();
};

/** Translate legacy/configured labels without changing their stored field keys. */
export const localizeBusinessLabel = (label, terminology) => {
  if (!label || !terminology) return label;
  let result = String(label);
  const replacements = [
    [/\bstudents\b/gi, terminology.people],
    [/\bstudent\b/gi, terminology.person],
    [/\bclasses\b/gi, terminology.groups],
    [/\bclass\b/gi, terminology.group],
    [/\bsection\b/gi, terminology.section],
    [/\bfaculty\b/gi, terminology.staff],
  ];
  replacements.forEach(([pattern, replacement]) => {
    result = result.replace(pattern, match => preserveCase(match, replacement));
  });
  return result.replace(/\b([A-Za-z]+)\s*\/\s*\1\b/gi, '$1');
};
