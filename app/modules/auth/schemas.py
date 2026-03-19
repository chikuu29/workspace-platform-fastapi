from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    userName: str = Field(min_length=1)
    password: str = Field(min_length=6)
    email: EmailStr
    phone: str = Field(min_length=10)
    firstName: str = Field(min_length=2)
    lastName: str = Field(min_length=2)
    address: Optional[str] = None


class LoginRequest(BaseModel):
    loginId: str = Field(min_length=5)
    password: str = Field(min_length=5)


class OAuthExchangeRequest(BaseModel):
    code: str
    redirect_url: str
    device_id: str
    code_verifier: Optional[str] = None
