from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models import AuditLog, User
from app.schemas.common import Page
from app.schemas.common import ORMModel

router = APIRouter(tags=["audit"])


class AuditRow(ORMModel):
    id: int
    user_id: int | None
    user_email: str | None
    user_name: str | None = None
    action: str
    module: str
    record_type: str | None
    record_id: str | None
    summary: str | None
    old_values: dict | None
    new_values: dict | None
    ip_address: str | None
    created_at: datetime


@router.get("/audit-logs", response_model=Page[AuditRow])
def list_audit_logs(
    action: str | None = None,
    module: str | None = None,
    user_id: int | None = None,
    record_type: str | None = None,
    record_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("audit.read")),
) -> Page[AuditRow]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action.upper())
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if record_type:
        stmt = stmt.where(AuditLog.record_type == record_type)
    if record_id:
        stmt = stmt.where(AuditLog.record_id == str(record_id))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max))
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(AuditLog.summary.ilike(needle), AuditLog.user_email.ilike(needle))
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        AuditRow(
            id=r.id, user_id=r.user_id, user_email=r.user_email,
            user_name=r.user.full_name if r.user else None,
            action=r.action, module=r.module, record_type=r.record_type,
            record_id=r.record_id, summary=r.summary, old_values=r.old_values,
            new_values=r.new_values, ip_address=r.ip_address, created_at=r.created_at,
        )
        for r in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/audit-logs/actions", response_model=list[str])
def distinct_actions(
    db: Session = Depends(get_db), user: User = Depends(require("audit.read"))
) -> list[str]:
    return sorted(db.scalars(select(AuditLog.action).distinct()))
