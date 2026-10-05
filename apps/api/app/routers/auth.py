from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.ratelimit import limit
from app.schemas.auth import Token, UserLogin, UserRegister
from app.services.auth_service import authenticate_user, register_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=201, dependencies=[Depends(limit("register"))])
def register(payload: UserRegister, db: Session = Depends(get_db)) -> Token:
    _, token = register_user(db, payload)
    return Token(access_token=token)


@router.post("/login", response_model=Token, dependencies=[Depends(limit("login"))])
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    _, token = authenticate_user(db, payload)
    return Token(access_token=token)
