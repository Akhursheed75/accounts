from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import accessible_shop_ids, assert_shop_access, require
from app.core.errors import Forbidden
from app.db.session import get_db
from app.models import User
from app.services import audit
from app.services import monthly
from app.services.monthly_export import build_workbook

router = APIRouter(tags=["monthly"])


class RateIn(BaseModel):
    # Cordobas for one dollar. Bounded so a slip of the finger (3662 for 36.62)
    # is refused rather than silently shrinking every USD figure a hundredfold.
    nio_per_usd: Decimal = Field(gt=Decimal("1"), le=Decimal("1000"), max_digits=12, decimal_places=4)


@router.get("/monthly")
def list_months(
    db: Session = Depends(get_db), user: User = Depends(require("report.read"))
) -> dict:
    return {
        "previous_months": monthly.PREVIOUS_MONTHS,
        "months": monthly.month_summaries(db, allowed=accessible_shop_ids(user)),
    }


@router.get("/monthly/rate")
def rate_on(
    on: date,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.read")),
) -> dict:
    """The rate that applies to one day — used by the daily sheet to show its
    payments in USD as they are typed. Works for any month, not only the four
    offered on the Monthly Records page."""
    row = monthly.get_rate(db, on)
    return {
        "month": monthly.month_key(on.replace(day=1)),
        "nio_per_usd": str(row.nio_per_usd) if row else None,
    }


@router.get("/monthly/{month}")
def month_detail(
    month: str,
    shop_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("report.read")),
) -> dict:
    start = monthly.parse_month(month)
    if shop_id:
        assert_shop_access(user, shop_id)
    data = monthly.collect(db, start, allowed=accessible_shop_ids(user), shop_id=shop_id)
    return monthly.as_json(data)


@router.get("/monthly/{month}/export")
def month_export(
    month: str,
    shop_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("report.read")),
):
    if not user.has_permission("report.export"):
        raise Forbidden("Your role can view monthly records but not download them.")
    start = monthly.parse_month(month)
    if shop_id:
        assert_shop_access(user, shop_id)
    data = monthly.collect(db, start, allowed=accessible_shop_ids(user), shop_id=shop_id)
    payload = build_workbook(data)

    scope = f" ({data.shop.name})" if data.shop else ""
    audit.record(
        db, action=audit.Actions.EXPORT_REPORT, module="monthly", user=user,
        record_type="monthly_record", record_id=monthly.month_key(start),
        summary=f"Downloaded the monthly record for {monthly.month_label(start)}{scope}",
        new_values={"month": monthly.month_key(start), "shop_id": shop_id,
                    "rate": str(data.rate.nio_per_usd) if data.rate else None},
    )
    db.commit()

    suffix = f"-{data.shop.code}" if data.shop else ""
    name = f"reconcilia-{monthly.month_key(start)}{suffix}-{datetime.now():%Y%m%d}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "content-disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "x-content-type-options": "nosniff",
        },
    )


@router.put("/monthly/{month}/rate")
def set_month_rate(
    month: str,
    payload: RateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
) -> dict:
    start = monthly.parse_month(month)
    before = monthly.get_rate(db, start)
    old = str(before.nio_per_usd) if before else None
    row = monthly.set_rate(db, start, payload.nio_per_usd, user)
    audit.record(
        db, action=audit.Actions.SET_EXCHANGE_RATE, module="monthly", user=user,
        record_type="exchange_rate", record_id=monthly.month_key(start),
        summary=(f"Set the {monthly.month_label(start)} rate to C$ {row.nio_per_usd} per $1"
                 + (f" (was {old})" if old else "")),
        old_values={"nio_per_usd": old},
        new_values={"nio_per_usd": str(row.nio_per_usd)},
    )
    db.commit()
    return {"month": monthly.month_key(start), "nio_per_usd": str(row.nio_per_usd)}
