from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import Email, ORMModel


class UserCreate(BaseModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=10, max_length=200)
    role_id: int
    shop_ids: list[int] = []
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=160)
    role_id: int | None = None
    shop_ids: list[int] | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=10, max_length=200)


class PermissionOut(ORMModel):
    id: int
    code: str
    description: str


class RoleOut(ORMModel):
    id: int
    code: str
    name: str
    description: str
    is_system: bool
    permissions: list[str] = []
    user_count: int = 0


class RoleIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    permissions: list[str] = []


class RolePermissionsIn(BaseModel):
    permissions: list[str]


class UserRow(ORMModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    role_id: int
    role_name: str
    shop_ids: list[int] = []
