from __future__ import annotations

import contextvars
from decimal import Decimal
from datetime import date, datetime, time
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User

# Set by middleware so audit entries can record where an action came from
# without threading the request through every service signature.
request_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "request_context", default={}
)


class Actions:
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    CREATE_USER = "CREATE_USER"
    EDIT_USER = "EDIT_USER"
    CHANGE_PERMISSIONS = "CHANGE_PERMISSIONS"
    CREATE_SHOP = "CREATE_SHOP"
    EDIT_SHOP = "EDIT_SHOP"
    CREATE_BANK = "CREATE_BANK"
    EDIT_BANK = "EDIT_BANK"
    CREATE_ACCOUNTING = "CREATE_ACCOUNTING"
    EDIT_ACCOUNTING = "EDIT_ACCOUNTING"
    DELETE_ACCOUNTING = "DELETE_ACCOUNTING"
    LOCK_ACCOUNTING = "LOCK_ACCOUNTING"
    CREATE_PAYMENT = "CREATE_PAYMENT"
    EDIT_PAYMENT = "EDIT_PAYMENT"
    DELETE_PAYMENT = "DELETE_PAYMENT"
    UPLOAD_STATEMENT = "UPLOAD_STATEMENT"
    PROCESS_STATEMENT = "PROCESS_STATEMENT"
    DELETE_STATEMENT = "DELETE_STATEMENT"
    AUTO_MATCH = "AUTO_MATCH"
    MATCH_TRANSACTION = "MATCH_TRANSACTION"
    MANUAL_MATCH = "MANUAL_MATCH"
    UNMATCH_TRANSACTION = "UNMATCH_TRANSACTION"
    IGNORE_ITEM = "IGNORE_ITEM"
    EXPORT_REPORT = "EXPORT_REPORT"
    EDIT_SETTINGS = "EDIT_SETTINGS"
    SET_EXCHANGE_RATE = "SET_EXCHANGE_RATE"


def jsonable(value: Any) -> Any:
    """Audit payloads go into JSONB, so Decimals and dates must be plain."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def diff(old: dict | None, new: dict | None) -> tuple[dict | None, dict | None]:
    """Keep only the fields that actually changed, so the log stays readable."""
    if old is None or new is None:
        return jsonable(old), jsonable(new)
    changed = [k for k in set(old) | set(new) if old.get(k) != new.get(k)]
    if not changed:
        return None, None
    return (
        jsonable({k: old.get(k) for k in changed}),
        jsonable({k: new.get(k) for k in changed}),
    )


def record(
    db: Session,
    *,
    action: str,
    module: str,
    user: User | None = None,
    record_type: str | None = None,
    record_id: Any = None,
    summary: str | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
) -> AuditLog:
    ctx = request_context.get() or {}
    entry = AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else ctx.get("email"),
        action=action,
        module=module,
        record_type=record_type,
        record_id=str(record_id) if record_id is not None else None,
        summary=summary[:400] if summary else None,
        old_values=jsonable(old_values) if old_values else None,
        new_values=jsonable(new_values) if new_values else None,
        ip_address=ctx.get("ip"),
        user_agent=(ctx.get("user_agent") or "")[:300] or None,
    )
    db.add(entry)
    return entry
