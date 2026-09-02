from __future__ import annotations

from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.deps import ACCESS_COOKIE, REFRESH_COOKIE, get_current_user, has_global_scope
from app.core.errors import Unauthorized
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, PasswordChange, TokenPair, UserOut
from app.schemas.common import Message
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        role={"id": user.role.id, "code": user.role.code, "name": user.role.name},
        permissions=sorted(user.permissions),
        shop_ids=user.shop_ids,
        has_global_scope=has_global_scope(user),
    )


def _set_cookies(response: Response, access: str, refresh: str) -> None:
    common = {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "domain": settings.cookie_domain,
        "path": "/",
    }
    response.set_cookie(
        ACCESS_COOKIE, access, max_age=settings.access_token_minutes * 60, **common
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh, max_age=settings.refresh_token_days * 86400, **common
    )


@router.post("/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPair:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    # The same message for "no such user" and "wrong password": a login form
    # should not tell an attacker which addresses exist.
    if user is None or not security.verify_password(payload.password, user.password_hash):
        audit.record(
            db,
            action=audit.Actions.LOGIN_FAILED,
            module="auth",
            summary=f"Failed sign-in for {payload.email}",
        )
        db.commit()
        raise Unauthorized("Email or password is incorrect.")
    if not user.is_active:
        raise Unauthorized("This account has been deactivated.")

    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(payload.password)

    user.last_login_at = datetime.now(UTC)
    access = security.create_access_token(user.id, user.token_version)
    refresh = security.create_refresh_token(user.id, user.token_version)
    audit.record(db, action=audit.Actions.LOGIN, module="auth", user=user,
                 summary=f"{user.email} signed in")
    db.commit()
    db.refresh(user)

    _set_cookies(response, access, refresh)
    return TokenPair(access_token=access, refresh_token=refresh, user=serialize_user(user))


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> TokenPair:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        body_token = request.headers.get("x-refresh-token")
        token = body_token
    if not token:
        raise Unauthorized("No refresh token was supplied.")
    try:
        payload = security.decode_token(token, security.REFRESH)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Your session has expired. Please sign in again.") from exc

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or int(payload.get("ver", 0)) != user.token_version:
        raise Unauthorized("Your session is no longer valid.")

    access = security.create_access_token(user.id, user.token_version)
    new_refresh = security.create_refresh_token(user.id, user.token_version)
    _set_cookies(response, access, new_refresh)
    return TokenPair(access_token=access, refresh_token=new_refresh, user=serialize_user(user))


@router.post("/logout", response_model=Message)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Message:
    audit.record(db, action=audit.Actions.LOGOUT, module="auth", user=user,
                 summary=f"{user.email} signed out")
    db.commit()
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, path="/", domain=settings.cookie_domain)
    return Message(message="Signed out.")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return serialize_user(user)


@router.post("/change-password", response_model=Message)
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Message:
    if not security.verify_password(payload.current_password, user.password_hash):
        raise Unauthorized("Your current password is incorrect.")
    user.password_hash = security.hash_password(payload.new_password)
    # Invalidates every token already issued for this account.
    user.token_version += 1
    audit.record(db, action=audit.Actions.EDIT_USER, module="auth", user=user,
                 record_type="user", record_id=user.id,
                 summary="Changed own password")
    db.commit()
    return Message(message="Password changed. Please sign in again.")
