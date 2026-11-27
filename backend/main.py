from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, EmailStr
import os
from sqlalchemy import create_engine, Column, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import sessionmaker, declarative_base
from passlib.context import CryptContext
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
import random
from core import database as db_core
from sqlalchemy import inspect
from typing import Optional, List

app = FastAPI(title="Vehicle Diagnostics Backend", version="0.1.0")

frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = db_core.engine
SessionLocal = db_core.SessionLocal
Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserORM(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    role = Column(String(64), nullable=False, default="Car Owner")
    password_hash = Column(String(255), nullable=True)
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RegisterPayload(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "Car Owner"

class LoginPayload(BaseModel):
    email: EmailStr
    password: str

def make_token(subject: str):
    return f"token-{subject}"

def gen_code():
    return f"{random.randint(100000, 999999)}"

class User(BaseModel):
    name: str
    email: EmailStr
    provider: str
    role: str = "Car Owner"


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/auth/register")
def register(payload: RegisterPayload, db=Depends(get_db)):
    hashed = pwd_context.hash(payload.password)
    user = UserORM(
        name=payload.name,
        email=payload.email.lower(),
        role=payload.role,
        password_hash=hashed,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    token = make_token(str(user.id))
    resp = JSONResponse({"user": {"name": user.name, "email": user.email, "role": user.role}, "token": token})
    resp.set_cookie("vd_token", token, httponly=True, samesite="lax")
    return resp

@app.post("/auth/login")
def login(payload: LoginPayload, db=Depends(get_db)):
    user = db.query(UserORM).filter(UserORM.email == payload.email.lower()).first()
    if not user or not user.password_hash or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = make_token(str(user.id))
    resp = JSONResponse({"user": {"name": user.name, "email": user.email, "role": user.role}, "token": token})
    resp.set_cookie("vd_token", token, httponly=True, samesite="lax")
    return resp

class VerifyPayload(BaseModel):
    email: EmailStr
    code: str

class MessagePayload(BaseModel):
    session_id: str = "global"
    role: str
    sender_name: str
    recipient: str
    text: str

@app.get("/auth/{provider}/login")
def auth_login(provider: str):
    p = provider.lower()
    if p not in {"google", "github"}:
        raise HTTPException(status_code=404, detail="Unknown provider")
    return RedirectResponse(url=f"/auth/{p}/callback?code=demo-code&state=demo-state", status_code=307)


@app.get("/auth/{provider}/callback")
def auth_callback(provider: str, code: str | None = None, state: str | None = None):
    p = provider.lower()
    if p not in {"google", "github"}:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    user = User(name="Demo User", email="demo@example.com", provider=p)
    token = f"{p}-demo-token"
    resp = JSONResponse({"user": user.model_dump(), "token": token})
    resp.set_cookie("vd_token", token, httponly=True, samesite="lax")
    return resp


@app.get("/")
def root():
    return {"app": "vehicle-diagnostics-backend", "frontend": frontend_url}

@app.get("/users")
def list_users(db=Depends(get_db)):
    rows = db.query(UserORM).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in rows]

@app.post("/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("vd_token")
    return resp

@app.get("/db/status")
def db_status():
    conn = db_core.engine.connect()
    try:
        schema = db_core.DBNAME
        result = conn.execute(
            text(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=:schema AND TABLE_NAME IN ('users','chat_messages','conversations','vehicles','diagnostic_records')"
            ),
            {"schema": schema},
        )
        names = {row[0] for row in result.fetchall()}
        tables = {
            "users": "users" in names,
            "chat_messages": "chat_messages" in names,
            "conversations": "conversations" in names,
            "vehicles": "vehicles" in names,
            "diagnostic_records": "diagnostic_records" in names,
        }
        return {"connected": True, "schema": schema, "tables": tables}
    finally:
        conn.close()

@app.get("/messages")
def list_messages(session_id: str = "global", limit: int = 50):
    conn = db_core.engine.connect()
    try:
        rows = conn.execute(
            text("SELECT session_id, role, sender_name, recipient, text, timestamp FROM chat_messages WHERE session_id=:sid ORDER BY timestamp ASC LIMIT :lim"),
            {"sid": session_id, "lim": limit},
        ).fetchall()
        return [{"session_id": r[0], "role": r[1], "sender_name": r[2], "recipient": r[3], "text": r[4], "timestamp": str(r[5])} for r in rows]
    finally:
        conn.close()

@app.post("/messages")
def post_message(payload: MessagePayload):
    conn = db_core.engine.connect()
    try:
        conn.execute(
            text("INSERT INTO chat_messages(session_id, role, sender_name, recipient, text, user_type) VALUES(:sid, :role, :sender_name, :recipient, :text, 'user')"),
            {"sid": payload.session_id, "role": payload.role, "sender_name": payload.sender_name, "recipient": payload.recipient, "text": payload.text},
        )
        return {"ok": True}
    finally:
        conn.close()

