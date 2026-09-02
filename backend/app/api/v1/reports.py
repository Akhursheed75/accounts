from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import accessible_shop_ids, assert_shop_access, require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import User
from app.services import audit
from app.services.exporters import to_excel, to_pdf
from app.services.reports import REPORT_INDEX, REPORTS, Filters

router = APIRouter(tags=["reports"])


@router.get("/reports")
def list_reports(user: User = Depends(require("report.read"))) -> list[dict]:
    return REPORT_INDEX


@router.get("/reports/{report_key}")
def run_report(
    report_key: str,
    format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    shop_id: int | None = None,
    bank_id: int | None = None,
    currency_code: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("report.read")),
):
    builder = REPORTS.get(report_key)
    if builder is None:
        raise NotFound(
            f"There is no report called '{report_key}'. "
            f"Available: {', '.join(sorted(REPORTS))}."
        )
    if shop_id:
        assert_shop_access(user, shop_id)
    if format in {"xlsx", "pdf"} and not user.has_permission("report.export"):
        from app.core.errors import Forbidden

        raise Forbidden("Your role can view reports but not export them.")

    filters = Filters(
        date_from=date_from, date_to=date_to, shop_id=shop_id, bank_id=bank_id,
        currency_code=currency_code, shop_ids=accessible_shop_ids(user),
    )
    report = builder(db, filters)
    report.generated_at = datetime.now().isoformat(timespec="seconds")
    report.filters = {
        "From": date_from.isoformat() if date_from else None,
        "To": date_to.isoformat() if date_to else None,
        "Shop": shop_id, "Bank": bank_id, "Currency": currency_code,
    }

    if format == "json":
        return {
            "key": report.key, "title": report.title, "description": report.description,
            "generated_at": report.generated_at,
            "columns": [c.__dict__ for c in report.columns],
            "rows": report.rows, "totals": report.totals, "filters": report.filters,
        }

    audit.record(
        db, action=audit.Actions.EXPORT_REPORT, module="reports", user=user,
        record_type="report", record_id=report_key,
        summary=f"Exported '{report.title}' as {format.upper()} ({len(report.rows)} rows)",
        new_values=report.filters,
    )
    db.commit()

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if format == "xlsx":
        payload = to_excel(report)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        name = f"{report_key}-{stamp}.xlsx"
    else:
        payload = to_pdf(report)
        media = "application/pdf"
        name = f"{report_key}-{stamp}.pdf"

    return Response(
        content=payload,
        media_type=media,
        headers={
            "content-disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "x-content-type-options": "nosniff",
        },
    )
