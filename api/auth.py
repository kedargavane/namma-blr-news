"""
api/auth.py — JWT authentication utilities.

Provides:
  - create_token(user_id, role) → JWT string
  - get_current_user(token) → User  (FastAPI dependency)
  - get_admin_user(user)    → User  (admin-only dependency)
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

ALGORITHM    = "HS256"
TOKEN_EXPIRY = 7  # days

bearer_scheme = HTTPBearer(auto_error=False)


def _secret() -> str:
    s = os.environ.get("JWT_SECRET", "")
    if not s:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    return s


def create_token(user_id: int, role: str, name: str, email: str) -> str:
    payload = {
        "sub":   str(user_id),
        "role":  role,
        "name":  name,
        "email": email,
        "exp":   datetime.utcnow() + timedelta(days=TOKEN_EXPIRY),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError as e:
        logger.warning("JWT decode error: %s", e)
        return None


# ── FastAPI dependencies ──────────────────────────────────────────────────────

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
):
    """Dependency: returns decoded token payload or raises 401."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> Optional[dict]:
    """Dependency: returns payload if token present, None otherwise."""
    if not credentials:
        return None
    return decode_token(credentials.credentials)


def get_admin_user(user: dict = Depends(get_current_user)) -> dict:
    """Dependency: ensures user is admin."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
