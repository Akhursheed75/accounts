from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.models import DEFAULT_BALANCE_COMPONENTS, MatchSetting, SystemSetting


def match_settings(db: Session) -> MatchSetting:
    row = db.get(MatchSetting, 1)
    if row is None:
        row = MatchSetting(
            id=1,
            date_window_days=env.default_date_window_days,
            auto_confirm_score=env.default_auto_confirm_score,
            suggest_score=env.default_suggest_score,
        )
        db.add(row)
        db.flush()
    return row


def system_settings(db: Session) -> SystemSetting:
    row = db.get(SystemSetting, 1)
    if row is None:
        row = SystemSetting(id=1, balance_components=DEFAULT_BALANCE_COMPONENTS)
        db.add(row)
        db.flush()
    return row
