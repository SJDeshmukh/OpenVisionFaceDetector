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
    limit: Optional[int] = 500
    offset: Optional[int] = 0

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

class ClassBatchStartSchema(BaseModel):
    class_year: Optional[str] = ""
    division: Optional[str] = ""
    branch: Optional[str] = ""

class ClassBatchAddSchema(BaseModel):
    batch_id: str
    class_year: Optional[str] = ""
    division: Optional[str] = ""
    branch: Optional[str] = ""
    fast: Optional[bool] = False
    det_max_side: Optional[int] = None

class ClassBatchAssignment(BaseModel):
    item_id: str
    face_index: int
    person_id: Any

class ClassBatchCommitSchema(BaseModel):
    batch_id: str
    assignments: List[ClassBatchAssignment]
    class_year: Optional[str] = ""
    division: Optional[str] = ""
    branch: Optional[str] = ""
    threshold: Optional[float] = None

class ClassBatchStatusSchema(BaseModel):
    batch_id: str

class PayrollReportRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class PublicAttendanceRequest(BaseModel):
    student_number: str
    limit: Optional[int] = 50
