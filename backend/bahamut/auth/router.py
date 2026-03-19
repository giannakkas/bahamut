from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
import traceback

from bahamut.config import get_settings
from bahamut.database import get_db
from bahamut.models import User, Workspace, TradingProfile

router = APIRouter()
settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
logger = structlog.get_logger()

PROFILE_DEFAULTS = {
    "CONSERVATIVE": {
        "strong_signal_threshold": 0.82, "signal_threshold": 0.70,
        "weak_signal_threshold": 0.55, "min_agent_agreement": 7,
        "min_individual_confidence": 0.60, "challenge_rounds": 2,
        "max_daily_drawdown": 0.015, "max_weekly_drawdown": 0.030,
        "max_total_drawdown": 0.080, "max_concurrent_trades": 3,
        "max_leverage": 2.0, "max_single_position_pct": 0.02,
        "max_correlated_exposure": 0.03, "correlation_threshold": 0.60,
        "vix_freeze_threshold": 30, "event_freeze_hours": 4,
        "stop_loss_atr_multiple": 1.0, "take_profit_atr_multiple": 2.0,
        "entry_type": "LIMIT", "require_pullback": True,
        "allowed_regimes": ["RISK_ON", "LOW_VOL", "TREND_CONTINUATION"],
        "auto_downgrade_on_crisis": True,
        "streak_tighten_after": 2, "streak_loosen_after": 7,
        "weight_overrides": {"risk_agent": 1.20, "macro_agent": 1.20},
    },
    "BALANCED": {
        "strong_signal_threshold": 0.72, "signal_threshold": 0.58,
        "weak_signal_threshold": 0.45, "min_agent_agreement": 6,
        "min_individual_confidence": 0.50, "challenge_rounds": 1,
        "max_daily_drawdown": 0.030, "max_weekly_drawdown": 0.060,
        "max_total_drawdown": 0.150, "max_concurrent_trades": 6,
        "max_leverage": 5.0, "max_single_position_pct": 0.05,
        "max_correlated_exposure": 0.08, "correlation_threshold": 0.70,
        "vix_freeze_threshold": 35, "event_freeze_hours": 2,
        "stop_loss_atr_multiple": 1.5, "take_profit_atr_multiple": 2.25,
        "entry_type": "MARKET", "require_pullback": False,
        "allowed_regimes": ["RISK_ON", "LOW_VOL", "TREND_CONTINUATION",
                            "HIGH_VOL", "RISK_OFF", "EVENT_DRIVEN"],
        "auto_downgrade_on_crisis": False,
        "streak_tighten_after": 3, "streak_loosen_after": 5,
        "weight_overrides": {},
    },
    "AGGRESSIVE": {
        "strong_signal_threshold": 0.62, "signal_threshold": 0.48,
        "weak_signal_threshold": 0.35, "min_agent_agreement": 5,
        "min_individual_confidence": 0.40, "challenge_rounds": 1,
        "max_daily_drawdown": 0.050, "max_weekly_drawdown": 0.100,
        "max_total_drawdown": 0.250, "max_concurrent_trades": 10,
        "max_leverage": 10.0, "max_single_position_pct": 0.08,
        "max_correlated_exposure": 0.15, "correlation_threshold": 0.80,
        "vix_freeze_threshold": 45, "event_freeze_hours": 1,
        "stop_loss_atr_multiple": 2.0, "take_profit_atr_multiple": 3.0,
        "entry_type": "MARKET", "require_pullback": False,
        "allowed_regimes": ["ALL"],
        "auto_downgrade_on_crisis": False,
        "streak_tighten_after": 4, "streak_loosen_after": 5,
        "weight_overrides": {"technical_agent": 1.15, "flow_agent": 1.15},
    },
}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    workspace_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


def create_token(data: dict, secret: str, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(to_encode, secret, algorithm="HS256")


def create_access_token(user: User) -> str:
    return create_token(
        {"sub": str(user.id), "email": user.email, "role": user.role,
         "workspace_id": str(user.workspace_id)},
        settings.jwt_secret,
        timedelta(minutes=settings.jwt_access_expire_minutes),
    )


def create_refresh_token(user: User) -> str:
    return create_token(
        {"sub": str(user.id), "type": "refresh"},
        settings.jwt_refresh_secret,
        timedelta(days=settings.jwt_refresh_expire_days),
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        # Check existing
        existing = await db.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")

        # Create workspace
        slug = req.workspace_name.lower().replace(" ", "-")[:50]
        workspace = Workspace(name=req.workspace_name, slug=slug)
        db.add(workspace)
        await db.flush()

        # Create user
        user = User(
            email=req.email,
            password_hash=pwd_context.hash(req.password[:72]),
            full_name=req.full_name,
            role="admin",
            workspace_id=workspace.id,
        )
        db.add(user)
        await db.flush()

        # Create default trading profiles
        for name, defaults in PROFILE_DEFAULTS.items():
            profile = TradingProfile(
                user_id=user.id,
                name=name,
                is_active=(name == "BALANCED"),
                **defaults,
            )
            db.add(profile)

        await db.commit()

        return TokenResponse(
            access_token=create_access_token(user),
            refresh_token=create_refresh_token(user),
            user={"id": str(user.id), "email": user.email, "full_name": user.full_name,
                  "role": user.role, "workspace_id": str(workspace.id)},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("register_failed", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
        if not user or not pwd_context.verify(req.password[:72], user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()

        return TokenResponse(
            access_token=create_access_token(user),
            refresh_token=create_refresh_token(user),
            user={"id": str(user.id), "email": user.email, "full_name": user.full_name,
                  "role": user.role, "workspace_id": str(user.workspace_id)},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("login_failed", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "workspace_id": str(user.workspace_id),
    }


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "auth"}


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access token."""
    try:
        payload = jwt.decode(req.refresh_token, settings.jwt_refresh_secret, algorithms=["HS256"])
        # Verify token type
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Verify user still exists and is active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return RefreshResponse(access_token=create_access_token(user))
