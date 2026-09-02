from __future__ import annotations

from collections.abc import Callable, Iterator

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core import security
from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import GLOBAL_SCOPE_PERMISSION
from app.db.session import get_db
from app.models import User

ACCESS_COOKIE = "recon_access"
REFRESH_COOKIE = "recon_refresh"


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(ACCESS_COOKIE)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from_request(request)
    if not token:
        raise Unauthorized("You are not signed in.")
    try:
        payload = security.decode_token(token, security.ACCESS)
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your session has expired. Please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Your session is not valid. Please sign in again.") from exc

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise Unauthorized("This account is no longer active.")
    if int(payload.get("ver", 0)) != user.token_version:
        raise Unauthorized("Your session was ended. Please sign in again.")
    return user


def require(*permission_codes: str) -> Callable[..., User]:
    """Dependency factory: the user must hold every listed permission."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        missing = [c for c in permission_codes if not user.has_permission(c)]
        if missing:
            raise Forbidden(
                "Your role does not allow this action.",
                details={"missing_permissions": missing},
            )
        return user

    return _dep


def has_global_scope(user: User) -> bool:
    """Admins and accountants see every shop; a shop user sees their own."""
    return user.has_permission(GLOBAL_SCOPE_PERMISSION)


def accessible_shop_ids(user: User) -> list[int] | None:
    """None means 'all shops'. A list means 'exactly these'."""
    return None if has_global_scope(user) else list(user.shop_ids)


def assert_shop_access(user: User, shop_id: int) -> None:
    allowed = accessible_shop_ids(user)
    if allowed is not None and shop_id not in allowed:
        raise Forbidden("You do not have access to this shop.")
