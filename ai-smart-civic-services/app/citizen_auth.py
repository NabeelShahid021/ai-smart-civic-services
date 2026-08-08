"""
Citizen Authentication Service for AI Smart Civic Services.
Handles CNIC normalization/validation, bcrypt password hashing, JWT token issuance, and FastAPI security dependencies.
"""
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Citizen

# Citizen-specific JWT configuration (completely independent from admin auth)
CITIZEN_JWT_SECRET = os.getenv("CITIZEN_JWT_SECRET", "civic_citizen_secret_jwt_2026_pk").strip()
CITIZEN_JWT_ALGORITHM = "HS256"
CITIZEN_JWT_EXPIRATION_DAYS = 30

# Citizen Bearer security scheme
citizen_bearer = HTTPBearer(auto_error=False)


def normalize_and_validate_cnic(cnic_raw: str) -> str:
    """
    Validates and normalizes a Pakistani CNIC string.
    Accepts formats like '12345-1234567-1' or '1234512345671'.
    Returns clean 13-digit string or raises HTTP 422 if invalid.
    """
    if not cnic_raw or not isinstance(cnic_raw, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CNIC is required and must be a valid string.",
        )
    # Strip spaces, dashes, and hyphens
    clean = re.sub(r"[-\s]", "", cnic_raw.strip())
    if not (len(clean) == 13 and clean.isdigit()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid CNIC format '{cnic_raw}'. Pakistani CNIC must contain exactly 13 digits (e.g. 12345-1234567-1 or 1234512345671).",
        )
    return clean


def hash_password(password: str) -> str:
    """Hash a plaintext password using native bcrypt."""
    if not password or len(password.strip()) < 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 4 characters long.",
        )
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def create_citizen_token(citizen_id: int, cnic: str) -> str:
    """Issue a signed JWT for citizen session management."""
    secret = os.getenv("CITIZEN_JWT_SECRET", CITIZEN_JWT_SECRET).strip()
    expire = datetime.utcnow() + timedelta(days=CITIZEN_JWT_EXPIRATION_DAYS)
    payload: Dict[str, Any] = {
        "sub": str(citizen_id),
        "citizen_id": citizen_id,
        "cnic": cnic,
        "role": "citizen",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm=CITIZEN_JWT_ALGORITHM)


def decode_citizen_token(token: str) -> Dict[str, Any]:
    """Decode and validate a citizen JWT token."""
    secret = os.getenv("CITIZEN_JWT_SECRET", CITIZEN_JWT_SECRET).strip()
    try:
        payload = jwt.decode(token, secret, algorithms=[CITIZEN_JWT_ALGORITHM])
        if payload.get("role") != "citizen" or "citizen_id" not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Invalid citizen token claims.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Citizen session token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or malformed citizen token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_citizen(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(citizen_bearer),
    db: Session = Depends(get_db),
) -> Citizen:
    """
    FastAPI dependency: verifies citizen Bearer token and returns the authenticated Citizen model.
    Raises 401 if missing, invalid, or citizen not found in DB.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Citizen authentication required. Please sign up or log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials.strip()
    payload = decode_citizen_token(token)
    citizen_id = payload.get("citizen_id")

    citizen = db.query(Citizen).filter(Citizen.citizen_id == citizen_id).first()
    if not citizen:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Citizen account not found or deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return citizen
