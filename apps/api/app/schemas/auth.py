from pydantic import BaseModel, EmailStr, Field

from app.schemas.student import MAX_CLASS, MIN_CLASS


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    class_level: int = Field(ge=MIN_CLASS, le=MAX_CLASS)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str

    model_config = {"from_attributes": True}
