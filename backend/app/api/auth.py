"""认证 API：登录 / 获取当前用户 / 切换 Profile。"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.db import SessionLocal
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------- 极简 JWT（Hackathon 用，不引入第三方库）----------

_SECRET = "sage-hackathon-secret-2026"  # 演示用，不要用于生产


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _create_token(user_id: str, username: str, role: str) -> str:
    import base64
    payload = json.dumps({"uid": user_id, "u": username, "r": role, "exp": int(time.time()) + 86400 * 7})
    sig = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def _decode_token(token: str) -> dict | None:
    try:
        import base64
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        payload = base64.urlsafe_b64decode(parts[0]).decode()
        data = json.loads(payload)
        sig = hmac.HMAC(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if sig != parts[1]:
            return None
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def get_current_user(authorization: str = Header(default="")) -> dict:
    """从 Authorization header 解析当前用户。返回 {"uid", "u", "r"}。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    token = authorization[7:]
    data = _decode_token(token)
    if not data:
        raise HTTPException(401, "token 无效或已过期")
    return data


# ---------- Schemas ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    username: str
    display_name: str
    role: str
    current_profile: str


class ProfileUpdateRequest(BaseModel):
    profile_id: str


# ---------- 预置账户（首次启动时自动创建）----------

PRESET_USERS = [
    {"username": "admin", "password": "admin123", "display_name": "管理员", "role": "manager", "current_profile": "big_data"},
    {"username": "demo", "password": "demo123", "display_name": "Demo SE", "role": "member", "current_profile": "big_data"},
    {"username": "alice", "password": "alice123", "display_name": "Alice", "role": "member", "current_profile": "big_data"},
    {"username": "bob", "password": "bob123", "display_name": "Bob", "role": "member", "current_profile": "big_data"},
    {"username": "carol", "password": "carol123", "display_name": "Carol", "role": "member", "current_profile": "big_data"},
]


def ensure_preset_users() -> None:
    """确保预置账户存在。启动时调用。"""
    db = SessionLocal()
    try:
        for u in PRESET_USERS:
            exists = db.query(User).filter_by(username=u["username"]).first()
            if not exists:
                db.add(User(
                    username=u["username"],
                    password_hash=_hash_password(u["password"]),
                    display_name=u["display_name"],
                    role=u["role"],
                    current_profile=u["current_profile"],
                ))
        db.commit()
    finally:
        db.close()


# ---------- 路由 ----------

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username=req.username).first()
        if not user or user.password_hash != _hash_password(req.password):
            raise HTTPException(401, "用户名或密码错误")
        token = _create_token(user.id, user.username, user.role)
        return LoginResponse(
            token=token,
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            current_profile=user.current_profile,
        )
    finally:
        db.close()


@router.get("/me")
def get_me(current: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=current["uid"]).first()
        if not user:
            raise HTTPException(404, "用户不存在")
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "current_profile": user.current_profile,
        }
    finally:
        db.close()


@router.post("/profile")
def switch_profile(req: ProfileUpdateRequest, current: dict = Depends(get_current_user)):
    """切换当前激活的 Profile。"""
    valid_profiles = [
        "big_data", "deployment", "database", "dms",
        "analytics", "networking", "scd", "linux", "windows",
    ]
    if req.profile_id not in valid_profiles:
        raise HTTPException(400, f"无效的 profile: {req.profile_id}")
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=current["uid"]).first()
        if not user:
            raise HTTPException(404)
        user.current_profile = req.profile_id
        db.commit()
        return {"ok": True, "current_profile": req.profile_id}
    finally:
        db.close()


# ---------- Profile 列表 ----------

PROFILES = [
    {"id": "big_data", "name": "Big Data", "icon": "📊", "available": True},
    {"id": "deployment", "name": "Deployment", "icon": "🚀", "available": False},
    {"id": "database", "name": "Database", "icon": "🗄️", "available": False},
    {"id": "dms", "name": "DMS", "icon": "🔄", "available": False},
    {"id": "analytics", "name": "Analytics", "icon": "📈", "available": True},
    {"id": "networking", "name": "Networking", "icon": "🌐", "available": False},
    {"id": "scd", "name": "SCD", "icon": "🔒", "available": False},
    {"id": "linux", "name": "Linux", "icon": "🐧", "available": False},
    {"id": "windows", "name": "Windows", "icon": "🪟", "available": False},
]


@router.get("/profiles")
def list_profiles():
    """获取所有可选的 Profile 列表。"""
    return {"profiles": PROFILES}
