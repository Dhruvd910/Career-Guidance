from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models.student import StudentProfile
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def require_local_or_authenticated(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> None:
    """For the voice endpoints the on-device app needs before any account exists (MAYA's
    first-boot greeting and "what's your name?"). Loopback callers are the kiosk app
    itself; anything arriving over the network still needs a valid token, so these can't
    be used to burn TTS/STT credits from the LAN. uvicorn only trusts X-Forwarded-For
    from 127.0.0.1 by default, so a LAN client can't spoof its way in via headers."""
    if request.client and request.client.host in LOOPBACK_HOSTS:
        return
    get_current_user(credentials, db)


def get_current_student_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StudentProfile:
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student profile not found")
    return profile
