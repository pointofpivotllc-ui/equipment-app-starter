from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import os, shutil, json
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, JSON, UniqueConstraint, Index
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from passlib.hash import bcrypt
import jwt

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
FILES_DIR = os.environ.get("FILES_DIR", "./files")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

os.makedirs(FILES_DIR, exist_ok=True)

app = FastAPI(title="Equipment App Starter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGINS] if CORS_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# --- Models ---
class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=True)
    role = Column(String, default="employee")  # employee | supervisor | admin
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    company = relationship("Company")

class Equipment(Base):
    __tablename__ = "equipment"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    number = Column(String, nullable=False)
    description = Column(String, nullable=True)
    type = Column(String, nullable=True)
    current_job = Column(String, nullable=True)
    current_mileage = Column(Integer, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    updated_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_company_equipment_number"),
        Index("ix_equipment_company_number", "company_id", "number"),
    )

class TestingArea(Base):
    __tablename__ = "testing_areas"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False)  # e.g., DIELECTRIC
    applies_to_types = Column(JSON, nullable=True)  # list of types
    default_cadence_days = Column(Integer, default=365)
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_company_area_code"),)

class EquipmentTest(Base):
    __tablename__ = "equipment_tests"
    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False, index=True)
    area_id = Column(Integer, ForeignKey("testing_areas.id"), nullable=False, index=True)
    applies = Column(Boolean, default=True)
    last_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False, index=True)
    area_id = Column(Integer, ForeignKey("testing_areas.id"), nullable=True)
    file_url = Column(String, nullable=False)
    file_hash = Column(String, nullable=True)
    file_type = Column(String, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime, default=datetime.now(timezone.utc))

class EquipmentLock(Base):
    __tablename__ = "equipment_locks"
    equipment_id = Column(Integer, ForeignKey("equipment.id"), primary_key=True)
    locked_by = Column(Integer, ForeignKey("users.id"))
    locked_at = Column(DateTime, default=datetime.now(timezone.utc))
    status = Column(String, default="active")  # active | released | overridden | expired
    override_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    override_at = Column(DateTime, nullable=True)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String, nullable=False)  # create|update|lock|unlock|override|upload
    entity = Column(String, nullable=False)  # Equipment|EquipmentTest|Attachment|Lock
    entity_id = Column(String, nullable=False)
    before_json = Column(String, nullable=True)
    after_json = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))
    ip = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

# --- Utils / Auth ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "company_id": user.company_id,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=8)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def get_current_user(db: Session = Depends(get_db), authorization: str = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, int(data["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# --- Schemas ---
class LoginReq(BaseModel):
    email: str
    password: str

class LoginResp(BaseModel):
    token: str
    name: Optional[str]
    role: str

class EquipmentTestIn(BaseModel):
    area_code: str
    applies: bool
    last_date: Optional[datetime] = None
    notes: Optional[str] = None

class EquipmentUpsertReq(BaseModel):
    number: str
    description: Optional[str] = None
    type: Optional[str] = None
    job: Optional[str] = None
    mileage: Optional[int] = None
    tests: List[EquipmentTestIn] = []

# --- Seed route ---
@app.post("/seed")
def seed(db: Session = Depends(get_db)):
    company = db.query(Company).filter_by(name="Default Co").first()
    if not company:
        company = Company(name="Default Co")
        db.add(company); db.commit(); db.refresh(company)
    admin = db.query(User).filter_by(email="admin@example.com").first()
    if not admin:
        admin = User(email="admin@example.com", password_hash=bcrypt.hash("admin123"), name="Admin", role="admin", company_id=company.id)
        db.add(admin)
    areas = [
        ("Dielectric (Boom)", "DIELECTRIC", ["Bucket Truck", "Digger Derrick"], 365),
        ("Annual DOT Inspection", "DOT_ANNUAL", ["Bucket Truck", "Digger Derrick", "Truck"], 365),
        ("Chassis PM", "CHASSIS_PM", ["Truck", "Bucket Truck", "Digger Derrick"], 180),
        ("Hydraulics", "HYDRAULICS", ["Bucket Truck", "Digger Derrick"], 180),
        ("Fall Protection/Lanyards", "FALL_PROTECT", ["Bucket Truck", "Digger Derrick"], 365),
        ("Grounds/Hot Sticks", "GROUNDS_STICKS", ["Bucket Truck", "Digger Derrick"], 180),
    ]
    for name, code, types, cadence in areas:
        if not db.query(TestingArea).filter_by(company_id=company.id, code=code).first():
            db.add(TestingArea(company_id=company.id, name=name, code=code, applies_to_types=types, default_cadence_days=cadence))
    db.commit()
    return {"ok": True, "company_id": company.id, "admin_login": {"email": "admin@example.com", "password": "admin123"}}

# --- Auth ---
@app.post("/auth/login", response_model=LoginResp)
def login(payload: LoginReq, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email).first()
    if not user or not bcrypt.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(user), "name": user.name, "role": user.role}

# --- Locking ---
LOCK_TIMEOUT_MINUTES = 15

def get_equipment_by_number(db: Session, company_id: int, number: str):
    return db.query(Equipment).filter_by(company_id=company_id, number=number).first()

def is_lock_expired(lock: EquipmentLock) -> bool:
    if not lock: return True
    return (datetime.now(timezone.utc) - lock.locked_at) > timedelta(minutes=LOCK_TIMEOUT_MINUTES) or lock.status != "active"

@app.post("/equipment/lock")
def lock_equipment(number: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    eq = get_equipment_by_number(db, user.company_id, number)
    if not eq:
        eq = Equipment(company_id=user.company_id, number=number, created_by=user.id, updated_by=user.id)
        db.add(eq); db.commit(); db.refresh(eq)
    lock = db.get(EquipmentLock, eq.id)
    if lock and not is_lock_expired(lock):
        if lock.locked_by != user.id:
            return {"locked": True, "locked_by": lock.locked_by, "locked_at": lock.locked_at.isoformat(), "editable": False}
        else:
            return {"locked": True, "locked_by": user.id, "locked_at": lock.locked_at.isoformat(), "editable": True}
    if not lock:
        lock = EquipmentLock(equipment_id=eq.id, locked_by=user.id, locked_at=datetime.now(timezone.utc), status="active")
        db.add(lock)
    else:
        lock.locked_by = user.id; lock.locked_at = datetime.now(timezone.utc); lock.status = "active"; lock.override_by=None; lock.override_at=None
    db.add(AuditEvent(actor_id=user.id, action="lock", entity="Equipment", entity_id=str(eq.id), after_json=json.dumps({"number": number})))
    db.commit()
    return {"locked": True, "editable": True, "equipment_id": eq.id}

@app.post("/equipment/override-lock")
def override_lock(number: str = Form(...), reason: Optional[str] = Form(None), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    eq = get_equipment_by_number(db, user.company_id, number)
    if not eq: raise HTTPException(status_code=404, detail="Equipment not found")
    lock = db.get(EquipmentLock, eq.id)
    if lock and not is_lock_expired(lock) and lock.locked_by != user.id:
        if user.role not in ["supervisor","admin"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions to override")
        lock.status="overridden"; lock.override_by=user.id; lock.override_at=datetime.now(timezone.utc)
        lock.locked_by=user.id; lock.locked_at=datetime.now(timezone.utc); lock.status="active"
        db.add(AuditEvent(actor_id=user.id, action="override", entity="Lock", entity_id=str(eq.id), after_json=json.dumps({"reason": reason or ""})))
        db.commit()
        return {"ok": True, "editable": True}
    return {"ok": False, "message": "No active lock to override or you already hold the lock."}

@app.post("/equipment/release-lock")
def release_lock(number: str = Form(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    eq = get_equipment_by_number(db, user.company_id, number)
    if not eq: return {"ok": True}
    lock = db.get(EquipmentLock, eq.id)
    if lock and lock.locked_by == user.id and lock.status == "active":
        lock.status = "released"
        db.add(AuditEvent(actor_id=user.id, action="unlock", entity="Equipment", entity_id=str(eq.id)))
        db.commit()
    return {"ok": True}

# --- Upsert & Attachments ---
def compute_due(last_date: Optional[datetime], cadence_days: int) -> Optional[datetime]:
    if not last_date: return None
    return last_date + timedelta(days=cadence_days)

@app.post("/equipment/upsert")
def upsert_equipment(payload: EquipmentUpsertReq, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    eq = get_equipment_by_number(db, user.company_id, payload.number)
    creating = False
    if not eq:
        creating = True
        eq = Equipment(company_id=user.company_id, number=payload.number, created_by=user.id)
        db.add(eq); db.flush()
    lock = db.get(EquipmentLock, eq.id)
    if not lock or lock.locked_by != user.id or lock.status != "active":
        raise HTTPException(status_code=409, detail="This equipment is not locked by you. Acquire lock before saving.")
    before = {"description": eq.description, "type": eq.type, "current_job": eq.current_job, "current_mileage": eq.current_mileage}
    eq.description = payload.description
    eq.type = payload.type
    eq.current_job = payload.job
    eq.current_mileage = payload.mileage
    eq.updated_by = user.id
    db.add(eq)
    company_areas = {a.code: a for a in db.query(TestingArea).filter_by(company_id=user.company_id).all()}
    for t in payload.tests:
        area = company_areas.get(t.area_code)
        if not area: continue
        et = db.query(EquipmentTest).filter_by(equipment_id=eq.id, area_id=area.id).first()
        if not et: et = EquipmentTest(equipment_id=eq.id, area_id=area.id)
        et.applies = t.applies
        et.last_date = t.last_date
        et.due_date = compute_due(t.last_date, area.default_cadence_days) if t.applies else None
        et.created_by = user.id
        et.notes = t.notes
        db.add(et)
    db.add(AuditEvent(actor_id=user.id, action="update" if not creating else "create", entity="Equipment", entity_id=str(eq.id),
                      before_json=json.dumps(before), after_json=json.dumps({"description": eq.description, "type": eq.type, "job": eq.current_job, "mileage": eq.current_mileage})))
    lock.status = "released"
    db.commit()
    return {"ok": True, "equipment_id": eq.id}

@app.post("/attachments/upload")
def upload_attachment(number: str = Form(...), area_code: Optional[str] = Form(None), file: UploadFile = File(...),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    eq = get_equipment_by_number(db, user.company_id, number)
    if not eq: raise HTTPException(status_code=404, detail="Equipment not found")
    lock = db.get(EquipmentLock, eq.id)
    if not lock or lock.locked_by != user.id or lock.status != "active":
        raise HTTPException(status_code=409, detail="This equipment is not locked by you. Acquire lock before upload.")
    area = None
    if area_code:
        area = db.query(TestingArea).filter_by(company_id=user.company_id, code=area_code).first()
    safe_name = f"{eq.id}_{int(datetime.now(timezone.utc).timestamp())}_{file.filename}"
    dest = os.path.join(FILES_DIR, safe_name)
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    att = Attachment(equipment_id=eq.id, area_id=area.id if area else None, file_url=f"/files/{safe_name}", file_type=file.content_type, uploaded_by=user.id)
    db.add(att)
    db.add(AuditEvent(actor_id=user.id, action="upload", entity="Attachment", entity_id=str(eq.id),
                      after_json=json.dumps({"file": safe_name, "area_code": area_code})))
    db.commit()
    return {"ok": True, "file_url": f"/files/{safe_name}"}

@app.get("/files/{filename}")
def get_file(filename: str):
    path = os.path.join(FILES_DIR, filename)
    if not os.path.exists(path): raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)
