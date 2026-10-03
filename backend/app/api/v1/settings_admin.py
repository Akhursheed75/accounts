from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.core.errors import ValidationFailed
from app.db.session import get_db
from app.models import BaleType, User
from app.schemas.common import ORMModel
from app.services import audit
from app.services.settings_store import match_settings, system_settings

router = APIRouter(tags=["settings"])


class MatchSettingsOut(ORMModel):
    date_window_days: int
    amount_tolerance: Decimal
    auto_confirm_score: int
    suggest_score: int
    auto_confirm_requires_unique: bool
    match_debit_transactions: bool
    cash_deposit_window_days: int


class MatchSettingsIn(BaseModel):
    date_window_days: int | None = Field(None, ge=0, le=30)
    amount_tolerance: Decimal | None = Field(None, ge=0, le=1000)
    auto_confirm_score: int | None = Field(None, ge=50, le=100)
    suggest_score: int | None = Field(None, ge=0, le=100)
    auto_confirm_requires_unique: bool | None = None
    match_debit_transactions: bool | None = None
    cash_deposit_window_days: int | None = Field(None, ge=0, le=31)


class BalanceComponent(BaseModel):
    key: str
    label: str
    sign: int = Field(ge=-1, le=1)
    enabled: bool


class SystemSettingsOut(ORMModel):
    company_name: str
    base_currency: str
    balance_components: list[BalanceComponent]
    allow_shop_edit_after_submit: bool
    lock_records_after_days: int


class SystemSettingsIn(BaseModel):
    company_name: str | None = Field(None, max_length=160)
    base_currency: str | None = Field(None, min_length=3, max_length=3)
    balance_components: list[BalanceComponent] | None = None
    allow_shop_edit_after_submit: bool | None = None
    lock_records_after_days: int | None = Field(None, ge=0, le=365)


class BaleTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=80)
    weight_lbs: Decimal | None = None
    sort_order: int = 0
    is_active: bool = True


@router.get("/settings/matching", response_model=MatchSettingsOut)
def get_match_settings(
    db: Session = Depends(get_db), user: User = Depends(require("reconciliation.read"))
) -> MatchSettingsOut:
    row = match_settings(db)
    db.commit()
    return MatchSettingsOut.model_validate(row)


@router.put("/settings/matching", response_model=MatchSettingsOut)
def update_match_settings(
    payload: MatchSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
) -> MatchSettingsOut:
    row = match_settings(db)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    merged = {**{k: getattr(row, k) for k in MatchSettingsIn.model_fields}, **changes}
    if merged["suggest_score"] > merged["auto_confirm_score"]:
        raise ValidationFailed(
            "The suggestion threshold cannot be higher than the automatic-match "
            "threshold, or nothing would ever be suggested."
        )
    before = {k: getattr(row, k) for k in changes}
    for key, value in changes.items():
        setattr(row, key, value)
    old, new = audit.diff(before, changes)
    audit.record(
        db, action=audit.Actions.EDIT_SETTINGS, module="settings", user=user,
        record_type="match_settings", record_id=1,
        summary="Changed the matching rules", old_values=old, new_values=new,
    )
    db.commit()
    db.refresh(row)
    return MatchSettingsOut.model_validate(row)


@router.get("/settings/system", response_model=SystemSettingsOut)
def get_system_settings(
    db: Session = Depends(get_db), user: User = Depends(require("accounting.read"))
) -> SystemSettingsOut:
    row = system_settings(db)
    db.commit()
    return SystemSettingsOut.model_validate(row)


@router.put("/settings/system", response_model=SystemSettingsOut)
def update_system_settings(
    payload: SystemSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
) -> SystemSettingsOut:
    row = system_settings(db)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "balance_components" in changes:
        changes["balance_components"] = [
            c if isinstance(c, dict) else c.model_dump() for c in changes["balance_components"]
        ]
    before = {k: getattr(row, k) for k in changes}
    for key, value in changes.items():
        setattr(row, key, value)
    old, new = audit.diff(before, changes)
    audit.record(
        db, action=audit.Actions.EDIT_SETTINGS, module="settings", user=user,
        record_type="system_settings", record_id=1,
        summary="Changed system settings", old_values=old, new_values=new,
    )
    db.commit()
    db.refresh(row)
    return SystemSettingsOut.model_validate(row)


@router.post("/settings/bale-types", status_code=201)
def create_bale_type(
    payload: BaleTypeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
) -> dict:
    if db.scalar(select(BaleType).where(BaleType.code == payload.code)):
        raise ValidationFailed(f"A bale type '{payload.code}' already exists.")
    bale_type = BaleType(**payload.model_dump())
    db.add(bale_type)
    db.flush()
    audit.record(
        db, action=audit.Actions.EDIT_SETTINGS, module="settings", user=user,
        record_type="bale_type", record_id=bale_type.id,
        summary=f"Added bale type {bale_type.code}",
    )
    db.commit()
    return {"id": bale_type.id, "code": bale_type.code, "name": bale_type.name}
