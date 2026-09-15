from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime

class AttendanceFilterSchema(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    name: Optional[str] = None
    person_id: Optional[int] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    shift: Optional[str] = None
    phone: Optional[str] = None
    person_type: Optional[str] = None
    limit: Optional[int] = 500
    offset: Optional[int] = 0

    @validator('person_type')
    def validate_person_type(cls, value):
        if value is None:
            return value
        normalized = str(value).strip().lower()
        if normalized not in {'student', 'faculty', 'employee'}:
            raise ValueError('person_type must be student, faculty, or employee')
        return normalized

class PersonEventSchema(BaseModel):
    detected: bool = False
    recognized: bool = False
    name: Optional[str] = None
    person_id: Optional[Any] = None # Can be int or "local:UUID"
    confidence: Optional[float] = 0.0
    image: Optional[str] = None # Base64
    timestamp: Optional[str] = None
    is_attendance: bool = True
    device_id: Optional[str] = None
    source_event_id: Optional[str] = None
    source_timezone: Optional[str] = None
    event_source: Optional[str] = None

class ClassBatchStartSchema(BaseModel):
    class_year: Optional[str] = ""
    division: Optional[str] = ""
    branch: Optional[str] = ""

class ClassBatchAddSchema(BaseModel):
    batch_id: str
    class_year: Optional[str] = ""
    division: Optional[str] = ""
    branch: Optional[str] = ""
    fast: Optional[bool] = True
    det_max_side: Optional[int] = None

class ClassBatchAssignment(BaseModel):
    item_id: str
    face_index: int
    person_id: Any
    # Old clients omit this field.  Defaulting to auto_match is deliberately
    # conservative: an unlabelled assignment may mark attendance, but it must
    # never be learned as a trusted gallery template.
    assignment_source: str = "auto_match"

    @validator('person_id')
    def validate_person_id(cls, value):
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise ValueError('person_id must be a positive integer')
        if normalized <= 0:
            raise ValueError('person_id must be a positive integer')
        return normalized

    @validator('assignment_source')
    def validate_assignment_source(cls, value):
        normalized = str(value or '').strip().lower()
        allowed = {'auto_match', 'manual_confirm', 'manual_correction'}
        if normalized not in allowed:
            raise ValueError('assignment_source must be auto_match, manual_confirm, or manual_correction')
        return normalized

class ClassBatchCommitSchema(BaseModel):
    batch_id: str
    assignments: List[ClassBatchAssignment]
    class_year: Optional[str] = ""
    division: Optional[str] = ""
    branch: Optional[str] = ""
    threshold: Optional[float] = None

    @validator('threshold')
    def validate_threshold(cls, value):
        if value is None:
            return value
        normalized = float(value)
        if not 0.40 <= normalized <= 0.95:
            raise ValueError('threshold must be between 0.40 and 0.95')
        return normalized

class ClassBatchStatusSchema(BaseModel):
    batch_id: str

class PayrollReportRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    person_type: Optional[str] = None

    @validator('person_type')
    def validate_person_type(cls, value):
        if value is None:
            return value
        normalized = str(value).strip().lower()
        if normalized not in {'student', 'faculty', 'employee'}:
            raise ValueError('person_type must be student, faculty, or employee')
        return normalized

class PublicAttendanceRequest(BaseModel):
    student_number: str
    limit: Optional[int] = 50

class RegistrationBatchStartSchema(BaseModel):
    pass

class RegistrationBatchAddSchema(BaseModel):
    batch_id: str
    fast: Optional[bool] = False
    det_max_side: Optional[int] = None

class RegistrationBatchStatusSchema(BaseModel):
    batch_id: str

class RegistrationBatchAssignment(BaseModel):
    item_id: str
    face_index: int
    name: str
    phone: Optional[str] = ""
    student_number: Optional[str] = ""
    class_id: Optional[str] = ""
    class_year: Optional[str] = ""
    division: Optional[str] = ""
    branch: Optional[str] = ""
    person_type: Optional[str] = None
    custom_data: Optional[Dict[str, Any]] = {}

class RegistrationBatchCommitSchema(BaseModel):
    batch_id: str
    assignments: List[RegistrationBatchAssignment]
