from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.deps import get_current_user, require
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.session import get_db
from app.models import Permission, Role, Shop, User, UserShop
from app.schemas.common import Message
from app.schemas.users import (
    PermissionOut, RoleIn, RoleOut, RolePermissionsIn, UserCreate, UserRow, UserUpdate,
)
from app.services import audit

router = APIRouter(tags=["users"])


def _user_row(user: User) -> UserRow:
    return UserRow(
        id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active,
        role_id=user.role_id, role_name=user.role.name if user.role else "",
        shop_ids=user.shop_ids,
    )


def _role_out(db: Session, role: Role) -> RoleOut:
    count = db.scalar(select(func.count(User.id)).where(User.role_id == role.id)) or 0
    return RoleOut(
        id=role.id, code=role.code, name=role.name, description=role.description,
        is_system=role.is_system, permissions=sorted(role.permission_codes()), user_count=count,
    )


def _apply_shops(db: Session, user: User, shop_ids: list[int]) -> None:
    wanted = set(shop_ids)
    for sid in wanted:
        if not db.get(Shop, sid):
            raise NotFound(f"Shop {sid} does not exist.")
    current = {link.shop_id: link for link in user.shop_links}
    for sid, link in current.items():
        if sid not in wanted:
            db.delete(link)
    for sid in wanted - set(current):
        db.add(UserShop(user_id=user.id, shop_id=sid))


@router.get("/users", response_model=list[UserRow])
def list_users(
    db: Session = Depends(get_db), me: User = Depends(require("user.manage"))
) -> list[UserRow]:
    return [_user_row(u) for u in db.scalars(select(User).order_by(User.full_name))]


@router.post("/users", response_model=UserRow, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require("user.manage")),
) -> UserRow:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("A user with that email already exists.")
    role = db.get(Role, payload.role_id)
    if not role:
        raise NotFound("That role does not exist.")
    user = User(
        email=email, full_name=payload.full_name, role_id=role.id,
        is_active=payload.is_active, password_hash=security.hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    _apply_shops(db, user, payload.shop_ids)
    audit.record(db, action=audit.Actions.CREATE_USER, module="users", user=me,
                 record_type="user", record_id=user.id,
                 summary=f"Created user {email} with role {role.code}",
                 new_values={"email": email, "role": role.code, "shop_ids": payload.shop_ids})
    db.commit()
    db.refresh(user)
    return _user_row(user)


@router.patch("/users/{user_id}", response_model=UserRow)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(require("user.manage")),
) -> UserRow:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("That user does not exist.")
    changes = payload.model_dump(exclude_unset=True)

    if changes.get("is_active") is False and user.id == me.id:
        raise ValidationFailed("You cannot deactivate your own account.")

    before = {"full_name": user.full_name, "role_id": user.role_id,
              "is_active": user.is_active, "shop_ids": sorted(user.shop_ids)}

    if "password" in changes and changes["password"]:
        user.password_hash = security.hash_password(changes.pop("password"))
        user.token_version += 1
    changes.pop("password", None)

    if "role_id" in changes:
        role = db.get(Role, changes["role_id"])
        if not role:
            raise NotFound("That role does not exist.")
        if user.id == me.id and role.id != user.role_id:
            raise ValidationFailed("You cannot change your own role.")
        user.role_id = role.id
    if "shop_ids" in changes and changes["shop_ids"] is not None:
        _apply_shops(db, user, changes["shop_ids"])
    for key in ("full_name", "is_active"):
        if key in changes and changes[key] is not None:
            setattr(user, key, changes[key])

    db.flush()
    db.refresh(user)
    after = {"full_name": user.full_name, "role_id": user.role_id,
             "is_active": user.is_active, "shop_ids": sorted(user.shop_ids)}
    old, new = audit.diff(before, after)
    audit.record(db, action=audit.Actions.EDIT_USER, module="users", user=me,
                 record_type="user", record_id=user.id,
                 summary=f"Edited user {user.email}", old_values=old, new_values=new)
    db.commit()
    db.refresh(user)
    return _user_row(user)


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db), me: User = Depends(get_current_user)
) -> list[RoleOut]:
    return [_role_out(db, r) for r in db.scalars(select(Role).order_by(Role.id))]


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(
    db: Session = Depends(get_db), me: User = Depends(require("user.manage"))
) -> list[PermissionOut]:
    return list(db.scalars(select(Permission).order_by(Permission.code)))


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(
    payload: RoleIn,
    db: Session = Depends(get_db),
    me: User = Depends(require("user.manage")),
) -> RoleOut:
    code = payload.code.upper()
    if db.scalar(select(Role).where(Role.code == code)):
        raise Conflict(f"A role with the code '{code}' already exists.")
    role = Role(code=code, name=payload.name, description=payload.description, is_system=False)
    perms = list(db.scalars(select(Permission).where(Permission.code.in_(payload.permissions))))
    unknown = set(payload.permissions) - {p.code for p in perms}
    if unknown:
        raise ValidationFailed(f"Unknown permissions: {', '.join(sorted(unknown))}")
    role.permissions = perms
    db.add(role)
    db.flush()
    audit.record(db, action=audit.Actions.CHANGE_PERMISSIONS, module="users", user=me,
                 record_type="role", record_id=role.id,
                 summary=f"Created role {code}", new_values={"permissions": payload.permissions})
    db.commit()
    db.refresh(role)
    return _role_out(db, role)


@router.put("/roles/{role_id}/permissions", response_model=RoleOut)
def set_role_permissions(
    role_id: int,
    payload: RolePermissionsIn,
    db: Session = Depends(get_db),
    me: User = Depends(require("user.manage")),
) -> RoleOut:
    role = db.get(Role, role_id)
    if not role:
        raise NotFound("That role does not exist.")
    perms = list(db.scalars(select(Permission).where(Permission.code.in_(payload.permissions))))
    unknown = set(payload.permissions) - {p.code for p in perms}
    if unknown:
        raise ValidationFailed(f"Unknown permissions: {', '.join(sorted(unknown))}")
    if role.id == me.role_id and "user.manage" not in payload.permissions:
        raise ValidationFailed(
            "You cannot remove user management from your own role — you would lock yourself out."
        )
    before = sorted(role.permission_codes())
    role.permissions = perms
    audit.record(db, action=audit.Actions.CHANGE_PERMISSIONS, module="users", user=me,
                 record_type="role", record_id=role.id,
                 summary=f"Changed permissions for role {role.code}",
                 old_values={"permissions": before},
                 new_values={"permissions": sorted(payload.permissions)})
    db.commit()
    db.refresh(role)
    return _role_out(db, role)


@router.delete("/roles/{role_id}", response_model=Message)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(require("user.manage")),
) -> Message:
    role = db.get(Role, role_id)
    if not role:
        raise NotFound("That role does not exist.")
    if role.is_system:
        raise Conflict("Built-in roles cannot be deleted.")
    if db.scalar(select(func.count(User.id)).where(User.role_id == role.id)):
        raise Conflict("Users are still assigned to this role.")
    db.delete(role)
    audit.record(db, action=audit.Actions.CHANGE_PERMISSIONS, module="users", user=me,
                 record_type="role", record_id=role_id, summary=f"Deleted role {role.code}")
    db.commit()
    return Message(message="Role deleted.")
