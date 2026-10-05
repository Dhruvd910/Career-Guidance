from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.models.student import StudentProfile
from app.models.user import User
from app.core.observability import audit
from app.schemas.auth import UserLogin, UserRegister


def register_user(db: Session, payload: UserRegister) -> tuple[User, str]:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    user = User(email=payload.email, password_hash=hash_password(payload.password), role="student")
    db.add(user)
    db.flush()

    profile = StudentProfile(user_id=user.id, name=payload.name, class_level=payload.class_level)
    db.add(profile)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return user, token


def authenticate_user(db: Session, payload: UserLogin) -> tuple[User, str]:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        audit("login_failed", user=user.id if user else "unknown")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    audit("login", user=user.id)
    token = create_access_token(subject=str(user.id))
    return user, token
