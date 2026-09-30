"""认证 API：登录 / 获取当前用户 / 切换 Profile。"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models import AdminAudit, AuthThrottle, User
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------- Signed session token ----------

_settings = get_settings()
_SECRET = _settings.auth_secret
if _settings.app_env.lower() == "production" and len(_SECRET) < 32:
    raise RuntimeError("生产环境必须配置至少 32 字符的 AUTH_SECRET")


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 310_000)
        return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))
    except ValueError:
        # Upgrade existing demo and registered users on their next successful login.
        return hmac.compare_digest(stored, hashlib.sha256(password.encode()).hexdigest())


def _create_token(user_id: str, username: str, role: str) -> str:
    import base64
    with SessionLocal() as db:
        user = db.get(User, user_id)
        token_version = user.token_version if user else 0
    payload = json.dumps({"uid": user_id, "u": username, "r": role, "v": token_version,
                          "exp": int(time.time()) + 86400 * 7})
    sig = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def _decode_token(token: str) -> dict | None:
    try:
        import base64
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        payload = base64.urlsafe_b64decode(parts[0]).decode()
        data = json.loads(payload)
        sig = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, parts[1]):
            return None
        if not isinstance(data.get("uid"), str) or not isinstance(data.get("exp"), int):
            return None
        if data["exp"] < time.time():
            return None
        return data
    except Exception:
        return None


def get_current_user(request: Request, authorization: str = Header(default="")) -> dict:
    """从 Authorization header 解析当前用户。返回 {"uid", "u", "r"}。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    token = authorization[7:]
    data = _decode_token(token)
    if not data:
        raise HTTPException(401, "token 无效或已过期")
    with SessionLocal() as db:
        user = db.get(User, data["uid"])
        if not user:
            raise HTTPException(401, "用户不存在")
        if not user.is_active:
            raise HTTPException(403, "账号已停用，请联系管理员")
        if data.get("v", 0) != user.token_version:
            raise HTTPException(401, "登录状态已失效，请重新登录")
        if user.must_change_password and request.url.path not in {"/api/auth/me", "/api/auth/change-password"}:
            raise HTTPException(403, "首次登录或密码重置后，请先修改密码")
        return {"uid": user.id, "u": user.username, "r": user.role}


# ---------- Schemas ----------

class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


class RegisterRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)
    display_name: str = Field(default="", max_length=64)


class LoginResponse(BaseModel):
    token: str
    user_id: str
    username: str
    display_name: str
    role: str
    current_profile: str
    must_change_password: bool = False


class ProfileUpdateRequest(BaseModel):
    profile_id: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=1024)


@router.put("/change-password")
def change_password(req: ChangePasswordRequest, current: dict = Depends(get_current_user)) -> dict:
    with SessionLocal() as db:
        user = db.get(User, current["uid"])
        if not user or not _verify_password(req.current_password, user.password_hash):
            raise HTTPException(400, "当前密码不正确")
        if req.current_password == req.new_password:
            raise HTTPException(400, "新密码不能与当前密码相同")
        user.password_hash = _hash_password(req.new_password)
        user.token_version += 1
        user.must_change_password = False
        if user.role == "manager":
            db.add(AdminAudit(actor_id=user.id, target_id=user.id, action="change_own_password"))
        db.commit()
        return {"ok": True, "sessions_revoked": True}


def _registration_enabled() -> bool:
    settings = get_settings()
    return settings.app_env.lower() != "production" or settings.public_registration


# ---------- 路由 ----------

def _throttle_key(username: str, peer: str) -> str:
    return hashlib.sha256(f"{username}\0{peer}".encode()).hexdigest()


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request):
    db = SessionLocal()
    try:
        now = time.time()
        key = _throttle_key(req.username, request.client.host if request.client else "unknown")
        throttle = db.get(AuthThrottle, key)
        if throttle and throttle.blocked_until > now:
            raise HTTPException(429, "登录尝试过多，请 15 分钟后重试")
        user = db.query(User).filter_by(username=req.username).first()
        if not user or not _verify_password(req.password, user.password_hash):
            if not throttle:
                throttle = AuthThrottle(key=key, failures=0, window_started=now, blocked_until=0.0)
                db.add(throttle)
            if now - throttle.window_started >= 900:
                throttle.failures = 0
                throttle.window_started = now
            throttle.failures += 1
            if throttle.failures >= 5:
                throttle.blocked_until = now + 900
            db.commit()
            if throttle.blocked_until > now:
                raise HTTPException(429, "登录尝试过多，请 15 分钟后重试")
            raise HTTPException(401, "用户名或密码错误")
        if not user.is_active:
            raise HTTPException(403, "账号已停用，请联系管理员")
        if throttle:
            db.delete(throttle)
        if "$" not in user.password_hash:
            user.password_hash = _hash_password(req.password)
        db.commit()
        token = _create_token(user.id, user.username, user.role)
        return LoginResponse(
            token=token,
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            current_profile=user.current_profile,
            must_change_password=user.must_change_password,
        )
    finally:
        db.close()


@router.post("/register", response_model=LoginResponse)
def register(req: RegisterRequest):
    """注册新用户，注册成功后自动登录返回 token。"""
    if not _registration_enabled():
        raise HTTPException(403, "当前环境由管理员创建账号")
    if not req.username or not req.password:
        raise HTTPException(400, "用户名和密码不能为空")
    if len(req.username) < 2 or len(req.username) > 32:
        raise HTTPException(400, "用户名长度需在 2-32 个字符之间")
    if len(req.password) < 6:
        raise HTTPException(400, "密码长度不能少于 6 位")

    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(username=req.username).first()
        if existing:
            raise HTTPException(409, "用户名已存在")
        display = req.display_name.strip() if req.display_name else req.username
        new_user = User(
            username=req.username,
            password_hash=_hash_password(req.password),
            display_name=display,
            role="member",
            current_profile="big_data",
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        token = _create_token(new_user.id, new_user.username, new_user.role)
        return LoginResponse(
            token=token,
            user_id=new_user.id,
            username=new_user.username,
            display_name=new_user.display_name,
            role=new_user.role,
            current_profile=new_user.current_profile,
            must_change_password=False,
        )
    finally:
        db.close()


@router.get("/config")
def public_auth_config() -> dict[str, bool]:
    return {"registration_enabled": _registration_enabled()}


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
            "must_change_password": user.must_change_password,
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
    {"id": "analytics", "name": "Analytics", "icon": "📈", "available": True},
    {"id": "deployment", "name": "Deployment", "icon": "🚀", "available": True},
    {"id": "database", "name": "Database", "icon": "🗄️", "available": True},
    {"id": "dms", "name": "DMS", "icon": "🔄", "available": True},
    {"id": "networking", "name": "Networking & Security", "icon": "🌐", "available": True},
    {"id": "scd", "name": "SCD", "icon": "🔒", "available": True},
    {"id": "linux", "name": "Linux", "icon": "🐧", "available": True},
    {"id": "windows", "name": "Windows", "icon": "🪟", "available": True},
]


@router.get("/profiles")
def list_profiles():
    """获取所有可选的 Profile 列表。"""
    return {"profiles": PROFILES}
