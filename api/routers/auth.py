"""Authentication endpoints — register, login (email+password), Google OAuth."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
import bcrypt
from sqlalchemy import select

from api.dependencies import DbSession, create_access_token
from api.schemas import GoogleAuthRequest, LoginRequest, RegisterRequest
from db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")


@router.post("/register")
async def register(body: RegisterRequest, db: DbSession):
    """Create a new account with email and password."""
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email.lower(),
        password_hash=_hash_password(body.password),
        name=body.name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    logger.info("Registered user %s", user.email)
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(user)}


@router.post("/login")
async def login(body: LoginRequest, db: DbSession):
    """Authenticate with email and password."""
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token(subject=str(user.id))
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(user)}


@router.post("/google")
async def google_auth(body: GoogleAuthRequest, db: DbSession):
    """Exchange a Google ID token for a FinSight JWT.

    Creates the user on first login.
    """
    try:
        idinfo = google_id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_id = idinfo["sub"]
    email = idinfo.get("email", "").lower()
    name = idinfo.get("name", "")

    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    # Look up by google_id first, then by email
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            # Link existing email account to Google
            user.google_id = google_id
            if not user.name and name:
                user.name = name
        else:
            # New user
            user = User(email=email, name=name, google_id=google_id)
            db.add(user)

    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    logger.info("Google auth for %s", user.email)
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(user)}


def _user_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
    }
