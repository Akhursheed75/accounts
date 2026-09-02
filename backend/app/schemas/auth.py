from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Email, ORMModel


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=200)


class ShopBrief(ORMModel):
    id: int
    code: str
    name: str
    city_name: str | None = None
    is_active: bool


class RoleBrief(ORMModel):
    id: int
    code: str
    name: str


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    last_login_at: datetime | None = None
    role: RoleBrief
    permissions: list[str] = []
    shop_ids: list[int] = []
    has_global_scope: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)
