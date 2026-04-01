from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Date, ForeignKey, Boolean, LargeBinary, JSON
from sqlalchemy.orm import relationship, declarative_base

db = SQLAlchemy()
Base = db.Model

class Vendor(Base):
    __tablename__ = 'vendors'
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(50))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default='active')
    registration_config = Column(Text)
    contact_person = Column(String(255))
    web_login_enabled = Column(Integer, default=1)
    frontend_bundle_id = Column(String(255))
    backend_service_id = Column(String(255))
    vertical = Column(String(255))
    attendance_type = Column(String(50), default='total_time')
    retention_days = Column(Integer, default=90)
    num_rectors = Column(Integer, default=0)
    num_hods = Column(Integer, default=0)
    departments = Column(Text)

    # Relationships
    companies = relationship("Company", back_populates="vendor")
    faces = relationship("Face", back_populates="vendor")
    attendance = relationship("Attendance", back_populates="vendor")
    system_users = relationship("SystemUser", back_populates="vendor")
    subscription = relationship("Subscription", back_populates="vendor", uselist=False)
    devices = relationship("VendorDevice", back_populates="vendor")
    parent_users = relationship("ParentUser", back_populates="vendor")
    leave_requests = relationship("LeaveRequest", back_populates="vendor")
    leave_staff = relationship("LeaveStaff", back_populates="vendor")

class Company(Base):
    __tablename__ = 'companies'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    name = Column(String(255))
    working_hours = Column(Float)
    shifts = Column(Text) # JSON string
    draft_timetable = Column(Text) # JSON string
    live_timetable = Column(Text) # JSON string
    last_modified_by = Column(String(255))
    last_modified_at = Column(DateTime)
    published_by = Column(String(255))
    published_at = Column(DateTime)

    vendor = relationship("Vendor", back_populates="companies")

class Face(Base):
    __tablename__ = 'faces'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    templates = Column(Text) # Base64 encoded or JSON
    face_image = Column(Text) # Base64 or Path
    department = Column(String(255))
    designation = Column(String(255))
    phone = Column(String(50))
    shift = Column(String(50))
    daily_wage = Column(Float, default=0.0)
    late_allowance_days = Column(Integer)
    late_deduction_amount = Column(Float)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    custom_data = Column(Text) # JSON string
    display_id = Column(Integer)

    vendor = relationship("Vendor", back_populates="faces")
    attendance_records = relationship("Attendance", back_populates="person")
    system_user = relationship("SystemUser", back_populates="person", uselist=False)
    embeddings = relationship("PersonEmbedding", back_populates="person")
    leave_requests = relationship("LeaveRequest", back_populates="student")

class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50))
    captured_image = Column(Text) # Base64 or Path
    activity = Column(String(255))
    is_late = Column(Integer, default=0)
    device_id = Column(String(255))
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    person_id = Column(Integer, ForeignKey('faces.id'))

    vendor = relationship("Vendor", back_populates="attendance")
    person = relationship("Face", back_populates="attendance_records")

class SystemUser(Base):
    __tablename__ = 'system_users'
    username = Column(String(255), primary_key=True)
    password = Column(String(255))
    password_plain = Column(String(255))
    role = Column(String(50))
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    person_id = Column(Integer, ForeignKey('faces.id'))
    has_set_password = Column(Integer, default=0)
    last_active_at = Column(DateTime)

    vendor = relationship("Vendor", back_populates="system_users")
    person = relationship("Face", back_populates="system_user")

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'), unique=True)
    plan_type = Column(String(50))
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    status = Column(String(50), default='active')
    max_users = Column(Integer)
    max_employees = Column(Integer)
    cost_per_user = Column(Float)
    setup_fee = Column(Float)
    setup_fee_paid = Column(Integer)
    features = Column(Text) # JSON string
    max_mobile_devices = Column(Integer, default=1)
    cost_per_employee = Column(Float, default=0.0)
    grace_period_days = Column(Integer, default=0)
    max_web_sessions = Column(Integer, default=1)

    vendor = relationship("Vendor", back_populates="subscription")

class VendorDevice(Base):
    __tablename__ = 'vendor_devices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    device_id = Column(String(255))
    device_name = Column(String(255))
    registered_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)
    last_active_at = Column(DateTime)
    battery_level = Column(Float)

    vendor = relationship("Vendor", back_populates="devices")

class ActiveSession(Base):
    __tablename__ = 'active_sessions'
    token = Column(String(255), primary_key=True)
    username = Column(String(255))
    vendor_id = Column(Integer)
    device_id = Column(String(255))
    platform = Column(String(50))
    last_active = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class Invoice(Base):
    __tablename__ = 'invoices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    amount = Column(Float)
    status = Column(String(50), default='generated')
    due_date = Column(Date)
    generated_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime)
    invoice_date = Column(Date)
    details = Column(Text)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_username = Column(String(255))
    actor_role = Column(String(50))
    target_vendor_id = Column(Integer)
    action = Column(String(255))
    details = Column(Text)
    ip = Column(String(50))
    timestamp = Column(DateTime, default=datetime.utcnow)

class SystemSetting(Base):
    __tablename__ = 'system_settings'
    key = Column(String(255), primary_key=True)
    value = Column(Text)

class ParentUser(Base):
    __tablename__ = 'parent_users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    username = Column(String(255), unique=True)
    password = Column(String(255))
    contact_email = Column(String(255))
    contact_phone = Column(String(50))
    student_number = Column(String(255))
    selected_person_id = Column(Integer)
    device_id = Column(String(255))
    fcm_token = Column(String(255))
    session_version = Column(Integer, default=1)
    face_image = Column(Text)
    face_template = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="parent_users")

class LeaveRequest(Base):
    __tablename__ = 'leave_requests'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    student_id = Column(Integer, ForeignKey('faces.id'))
    leave_type = Column(String(50))
    reason = Column(Text)
    start_date = Column(Date)
    end_date = Column(Date)
    start_time = Column(String(50))
    end_time = Column(String(50))
    parent_status = Column(String(50), default='pending')
    rector_status = Column(String(50), default='pending')
    hod_status = Column(String(50), default='pending')
    final_status = Column(String(50), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="leave_requests")
    student = relationship("Face", back_populates="leave_requests")

class StudentParent(Base):
    __tablename__ = 'student_parents'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer)
    person_id = Column(Integer)
    parent_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class ParentToken(Base):
    __tablename__ = 'parent_tokens'
    token = Column(String(255), primary_key=True)
    vendor_id = Column(Integer)
    student_number = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class PersonEmbedding(Base):
    __tablename__ = 'person_embeddings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer)
    person_id = Column(Integer, ForeignKey('faces.id'))
    class_year = Column(String(50))
    division = Column(String(50))
    branch = Column(String(255))
    vec = Column(LargeBinary)
    dim = Column(Integer)
    struct_vec = Column(LargeBinary)
    landmarks_3d = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    person = relationship("Face", back_populates="embeddings")

class ClassBatch(Base):
    __tablename__ = 'class_batches'
    id = Column(String(255), primary_key=True)
    vendor_id = Column(Integer)
    class_year = Column(String(50))
    division = Column(String(50))
    branch = Column(String(255))
    status = Column(String(50), default='active')
    created_at = Column(DateTime, default=datetime.utcnow)

class ClassBatchItem(Base):
    __tablename__ = 'class_batch_items'
    id = Column(String(255), primary_key=True)
    batch_id = Column(String(255))
    seq = Column(Integer)
    image_b64 = Column(Text)
    annotated_b64 = Column(Text)
    faces_json = Column(Text)
    status = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

class LeaveStaff(Base):
    __tablename__ = 'leave_staff'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey('vendors.id'))
    name = Column(String(255))
    role = Column(String(50))
    pin = Column(String(50))
    department = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="leave_staff")
