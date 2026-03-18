from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from config import get_settings
from models.auth import LoginRequest, LoginResponse, RefreshRequest, RefreshResponse

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory user store. In production, replace with database lookup.
_users: dict[str, str] | None = None


def _ensure_users() -> dict[str, str]:
    global _users
    if _users is None:
        s = get_settings()
        _users = {s.admin_username: hash_password(s.admin_password)}
    return _users


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest) -> LoginResponse:
    """
    POST /auth/login
    Request:  { username: string, password: string }
    Response: { access_token: string, refresh_token: string, user: string }
    Rate limited: 5 attempts per minute per IP.
    """
    users = _ensure_users()
    hashed = users.get(body.username)

    if not hashed or not verify_password(body.password, hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    access = create_access_token(body.username)
    refresh = create_refresh_token(body.username)
    return LoginResponse(access_token=access, refresh_token=refresh, user=body.username)


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("10/minute")
async def refresh(request: Request, body: RefreshRequest) -> RefreshResponse:
    """
    POST /auth/refresh
    Request:  { refresh_token: string }
    Response: { access_token: string }
    Rate limited: 10 attempts per minute per IP.
    """
    username = decode_token(body.refresh_token, expected_type="refresh")
    access = create_access_token(username)
    return RefreshResponse(access_token=access)
