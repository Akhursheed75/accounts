"""Matching a whole day of sheets against the day's statements.

A sheet tells the bank side in two ways, and both happen on real sheets:

- **Deposit by deposit** (Juigalpa, Jinotega): the detail lines list each slip.
  Each becomes a payment row and is matched one-to-one by the ordinary engine.
- **Only a total per bank** (Managua): forty customers paid by transfer and
  the sheet says "BAC C$ 28,567". There is no single bank line for that. The
  bank lines that make it up are found by looking for the combination of the
  day's still-unclaimed credits that adds up to it exactly — and it is only
  accepted when it is the *only* such combination. Two combinations means a
  person decides.

Because shops share bank accounts, the order matters: every shop's listed
deposits claim their lines first, and only then are totals solved from what
is left. So the whole day is re-solved together whenever a sheet or a
statement for it changes, and lines found for a total are re-found each time
rather than kept, so they can never go stale or block a deposit that a shop
lists later."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.models import (
    BankTransaction, MatchSetting, ReconciliationMatch, ShopBankTotal, ShopDailyRecord,
    ShopTransfer, User,
)
from app.services import audit
from app.services import reconciliation as recon

ZERO = Decimal("0.00")
SHEET, FOUND, PICKED = "SHEET", "FOUND", "PICKED"

# Search limits for the subset-sum. A day's credits on one account run to a
# few dozen; these bounds keep a pathological day from hanging a request, and
# hitting them is reported as "ambiguous", never as a match.
MAX_POOL = 60
MAX_NODES = 400_000


# ------------------------------------------------------------- subset search
def find_combinations(
    lines: list[tuple[int, Decimal]], target: Decimal, *, limit: int = 2
) -> list[list[int]] | None:
    """Up to `limit` distinct sets of line ids whose amounts add up to target
    exactly. None means the search was too large to finish — treat as unknown."""
    if target <= ZERO or not lines:
        return []
    if len(lines) > MAX_POOL:
        return None
    cents = sorted(((int(a * 100), i) for i, a in lines if a > ZERO), reverse=True)
    goal = int(target * 100)
    suffix = [0] * (len(cents) + 1)
    for k in range(len(cents) - 1, -1, -1):
        suffix[k] = suffix[k + 1] + cents[k][0]

    found: list[list[int]] = []
    nodes = 0

    def walk(k: int, remaining: int, chosen: list[int]) -> bool:
        """Depth-first, largest amounts first. Returns False to stop early."""
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES:
            return False
        if remaining == 0:
            # Two different lines of the same amount make two combinations:
            # that is ambiguity too — which customer's payment it was matters.
            found.append(list(chosen))
            return len(found) < limit
        if k == len(cents) or suffix[k] < remaining:
            return True
        amount, line_id = cents[k]
        if amount <= remaining:
            chosen.append(line_id)
            if not walk(k + 1, remaining - amount, chosen):
                return False
            chosen.pop()
        return walk(k + 1, remaining, chosen)

    completed = walk(0, goal, [])
    if not completed and len(found) < limit:
        return None
    return found


# ------------------------------------------------------------------- helpers
def _live(record: ShopDailyRecord) -> list[ShopTransfer]:
    return [t for t in record.transfers if t.deleted_at is None]


def _cell(transfer: ShopTransfer) -> tuple[int | None, str]:
    return (transfer.bank_id, transfer.currency_code)


def _confirmed_for(db: Session, transfer_ids: list[int]) -> dict[int, ReconciliationMatch]:
    if not transfer_ids:
        return {}
    return {
        m.shop_transfer_id: m
        for m in db.scalars(
            select(ReconciliationMatch).where(
                ReconciliationMatch.shop_transfer_id.in_(transfer_ids),
                ReconciliationMatch.status == "CONFIRMED",
                ReconciliationMatch.is_active.is_(True),
            )
        )
    }


def _claimed_txn_ids(db: Session) -> set[int]:
    """Lines already confirmed to someone, or suggested for a listed deposit —
    a total must not take a line a shop's own slip is probably pointing at."""
    rows = db.scalars(
        select(ReconciliationMatch.bank_transaction_id).where(
            ReconciliationMatch.is_active.is_(True),
            ReconciliationMatch.status.in_(["CONFIRMED", "SUGGESTED"]),
        )
    )
    return set(rows)


def day_pool(
    db: Session, business_date: date, bank_id: int, currency: str, *, exclude: set[int]
) -> list[BankTransaction]:
    return [
        t for t in db.scalars(
            select(BankTransaction).where(
                BankTransaction.bank_id == bank_id,
                BankTransaction.currency_code == currency,
                BankTransaction.txn_date == business_date,
                BankTransaction.direction == "CREDIT",
                BankTransaction.is_ignored.is_(False),
            ).order_by(BankTransaction.id)
        )
        if t.id not in exclude
    ]


def _attach_line(
    db: Session, record: ShopDailyRecord, txn: BankTransaction, *, source: str,
    user: User | None, total: ShopBankTotal,
) -> ShopTransfer:
    transfer = ShopTransfer(
        payment_method="BANK", bank_id=txn.bank_id, bank_account_id=txn.bank_account_id,
        currency_code=txn.currency_code, amount=txn.amount,
        reference=(txn.reference or txn.external_id or None),
        note=(txn.description or "")[:255], source=source,
    )
    record.transfers.append(transfer)
    db.flush()
    label = f"{total.bank.code if total.bank else total.bank_id} {total.currency_code} {total.amount}"
    db.add(
        ReconciliationMatch(
            shop_transfer_id=transfer.id, bank_transaction_id=txn.id, status="CONFIRMED",
            match_type="EXACT" if source == FOUND else "MANUAL",
            confidence=100 if source == FOUND else 0, amount_delta=ZERO, date_delta_days=0,
            score_breakdown=[{
                "signal": "total", "points": 0,
                "detail": (f"Part of the sheet's total {label} — the only combination of "
                           f"that day's bank lines that adds up to it")
                if source == FOUND else f"Picked by hand as part of the sheet's total {label}",
            }],
            matched_by_id=user.id if user else None, matched_at=datetime.now(UTC),
            note="Found from the bank total" if source == FOUND else "Picked for the bank total",
        )
    )
    db.flush()
    return transfer


def _release_found(db: Session, record: ShopDailyRecord) -> None:
    now = datetime.now(UTC)
    for transfer in _live(record):
        if transfer.source != FOUND:
            continue
        recon.release_matches(db, transfer, reason="Re-checked with the day's statements")
        transfer.deleted_at = now
    db.flush()


# --------------------------------------------------------------- the day
def rematch_day(
    db: Session, business_date: date, settings: MatchSetting, *, user: User | None = None
) -> dict:
    records = list(
        db.scalars(
            select(ShopDailyRecord).where(
                ShopDailyRecord.business_date == business_date,
                ShopDailyRecord.deleted_at.is_(None),
            ).order_by(ShopDailyRecord.id)
        )
    )
    for record in records:
        _release_found(db, record)

    # 1. Every listed deposit and every cash line claims its own line first.
    for record in records:
        for transfer in _live(record):
            if transfer.source == SHEET:
                recon.run_for_transfer(db, transfer, settings, user=user)
    db.flush()

    # 2. Then each bank total the sheet gave without deposits is solved from
    #    what is left of that bank's lines for the day.
    solved, open_cells = 0, 0
    for record in records:
        live = _live(record)
        listed = {_cell(t) for t in live if t.source == SHEET and not t.is_cash}
        for total in record.bank_totals:
            key = (total.bank_id, total.currency_code)
            if key in listed:
                continue  # its deposits are listed; they were matched one by one
            picked = sum(
                (t.amount for t in live
                 if t.source == PICKED and _cell(t) == key and t.deleted_at is None),
                ZERO,
            )
            remaining = total.amount - picked
            if remaining <= ZERO:
                continue
            pool = day_pool(
                db, business_date, total.bank_id, total.currency_code,
                exclude=_claimed_txn_ids(db),
            )
            combos = find_combinations([(t.id, t.amount) for t in pool], remaining)
            if combos and len(combos) == 1:
                by_id = {t.id: t for t in pool}
                for txn_id in combos[0]:
                    _attach_line(db, record, by_id[txn_id], source=FOUND, user=None, total=total)
                solved += 1
            else:
                open_cells += 1
    db.flush()
    return {"date": business_date.isoformat(), "sheets": len(records),
            "totals_solved": solved, "totals_open": open_cells}


def rematch_days(db: Session, dates: set[date], settings: MatchSetting) -> None:
    for day in sorted(dates):
        rematch_day(db, day, settings)


# ------------------------------------------------------------ cell status
@dataclass
class CellLine:
    transfer_id: int
    amount: Decimal
    source: str
    status: str
    bank_date: date | None
    bank_description: str | None


def cells(db: Session, record: ShopDailyRecord) -> list[dict]:
    """The TRANSFERS table of the sheet, one entry per bank and currency, each
    with a single status the screen can colour."""
    live = [t for t in _live(record) if not t.is_cash]
    statuses = recon.transfer_statuses(db, [t.id for t in live])
    confirmed = _confirmed_for(db, [t.id for t in live])
    txns = {
        t.id: t for t in db.scalars(
            select(BankTransaction).where(
                BankTransaction.id.in_([m.bank_transaction_id for m in confirmed.values()] or [-1])
            )
        )
    }
    declared = {(t.bank_id, t.currency_code): t for t in record.bank_totals}
    keys = set(declared) | {_cell(t) for t in live}

    out = []
    for key in sorted(keys, key=lambda k: (k[0] or 0, k[1])):
        bank_id, currency = key
        rows = [t for t in live if _cell(t) == key]
        listed = [t for t in rows if t.source == SHEET]
        lines = []
        for t in rows:
            state = recon.display_status(t, statuses.get(t.id))
            match = confirmed.get(t.id)
            txn = txns.get(match.bank_transaction_id) if match else None
            lines.append(CellLine(t.id, t.amount, t.source, state,
                                  txn.txn_date if txn else None, txn.description if txn else None))
        total = declared.get(key)
        listed_sum = sum((t.amount for t in listed), ZERO)
        matched_sum = sum((l.amount for l in lines if l.status == "MATCHED"), ZERO)
        target = total.amount if total else listed_sum

        has_lines = bool(
            db.scalar(
                select(BankTransaction.id).where(
                    BankTransaction.bank_id == bank_id,
                    BankTransaction.currency_code == currency,
                    BankTransaction.txn_date == record.business_date,
                ).limit(1)
            )
        )
        if total and listed and listed_sum != total.amount:
            status = "DIFFERENT"          # the sheet's own detail and total disagree
        elif lines and matched_sum == target and all(l.status == "MATCHED" for l in lines):
            status = "MATCHED"
        elif not has_lines:
            status = "WAITING"            # that day's statement is not uploaded yet
        elif any(l.status == "POSSIBLE" for l in lines):
            status = "POSSIBLE"
        else:
            status = "UNMATCHED"

        out.append({
            "total_id": total.id if total else None,
            "bank_id": bank_id,
            "bank_code": (total.bank.code if total and total.bank else
                          (rows[0].bank.code if rows and rows[0].bank else None)),
            "currency_code": currency,
            "declared": str(total.amount) if total else None,
            "listed_sum": str(listed_sum),
            "matched_sum": str(matched_sum),
            "remaining": str(target - matched_sum),
            "status": status,
            "lines": [
                {"transfer_id": l.transfer_id, "amount": str(l.amount), "source": l.source,
                 "status": l.status,
                 "bank_date": l.bank_date.isoformat() if l.bank_date else None,
                 "bank_description": l.bank_description}
                for l in lines
            ],
        })
    return out


# ------------------------------------------------------------ manual picks
def candidates(db: Session, record: ShopDailyRecord, total: ShopBankTotal) -> list[BankTransaction]:
    """Lines a person may tick for a total: that bank and currency, that day,
    not already confirmed to anything else."""
    taken = recon.confirmed_transaction_ids(db)
    mine = {
        m.bank_transaction_id for m in _confirmed_for(
            db, [t.id for t in _live(record)
                 if _cell(t) == (total.bank_id, total.currency_code)]
        ).values()
    }
    return day_pool(db, record.business_date, total.bank_id, total.currency_code,
                    exclude=taken - mine)


def pick(
    db: Session, record: ShopDailyRecord, total_id: int, transaction_ids: list[int], user: User
) -> None:
    total = next((t for t in record.bank_totals if t.id == total_id), None)
    if total is None:
        raise NotFound("That bank total is not on this sheet.")
    key = (total.bank_id, total.currency_code)
    if any(_cell(t) == key and t.source == SHEET for t in _live(record)):
        raise ValidationFailed(
            "This total already has its deposits listed on the sheet; match those instead."
        )
    available = {t.id: t for t in candidates(db, record, total)}
    missing = [i for i in transaction_ids if i not in available]
    if missing:
        raise ValidationFailed(
            "One of the chosen bank lines is no longer available — it may have been "
            "matched to another sheet. Reload and choose again."
        )
    chosen = [available[i] for i in transaction_ids]
    if sum((t.amount for t in chosen), ZERO) > total.amount:
        raise ValidationFailed(
            f"The chosen lines add up to more than the sheet's total of {total.amount}."
        )

    # Replace whatever currently stands for this total: found lines and earlier picks.
    now = datetime.now(UTC)
    for transfer in _live(record):
        if _cell(transfer) == key and transfer.source in (FOUND, PICKED):
            recon.release_matches(db, transfer, reason="Lines for the total chosen again")
            transfer.deleted_at = now
    db.flush()
    for txn in chosen:
        _attach_line(db, record, txn, source=PICKED, user=user, total=total)
    audit.record(
        db, action=audit.Actions.MANUAL_MATCH, module="reconciliation", user=user,
        record_type="shop_bank_total", record_id=total.id,
        summary=(f"Chose {len(chosen)} bank line(s) for {total.bank.code if total.bank else ''} "
                 f"{total.currency_code} {total.amount} on {record.business_date}"),
        new_values={"transactions": transaction_ids},
    )


# ------------------------------------------------- live check while typing
def _claimed_by_others(db: Session, record_id: int | None) -> set[int]:
    """Bank lines another sheet has already confirmed. Lines this sheet holds
    (from an earlier save) stay available to it."""
    query = (
        select(ReconciliationMatch.bank_transaction_id)
        .join(ShopTransfer, ShopTransfer.id == ReconciliationMatch.shop_transfer_id)
        .where(ReconciliationMatch.is_active.is_(True), ReconciliationMatch.status == "CONFIRMED")
    )
    if record_id is not None:
        query = query.where(ShopTransfer.daily_record_id != record_id)
    return set(db.scalars(query))


def preview(
    db: Session, business_date: date, *, record_id: int | None,
    details: list[tuple[int, str, Decimal]], totals: list[tuple[int, str, Decimal]],
    window_days: int,
) -> dict:
    """What would turn green if the sheet were saved now — nothing is written.

    Each listed deposit looks for a bank line of exactly its amount, in the same
    bank and currency, from the sheet's day up to `window_days` later, that no
    other sheet holds; two deposits never share a line. A total with no listed
    deposits is FOUND when exactly one combination of that day's free lines
    adds up to it."""
    from datetime import timedelta

    others = _claimed_by_others(db, record_id)
    last_day = business_date + timedelta(days=max(window_days, 0))
    cache: dict[tuple[int, str], list[BankTransaction]] = {}

    def lines(bank_id: int, currency: str) -> list[BankTransaction]:
        key = (bank_id, currency)
        if key not in cache:
            cache[key] = list(db.scalars(
                select(BankTransaction).where(
                    BankTransaction.bank_id == bank_id,
                    BankTransaction.currency_code == currency,
                    BankTransaction.txn_date >= business_date,
                    BankTransaction.txn_date <= last_day,
                    BankTransaction.direction == "CREDIT",
                    BankTransaction.is_ignored.is_(False),
                ).order_by(BankTransaction.txn_date, BankTransaction.id)
            ))
        return cache[key]

    used: set[int] = set()
    out_details = []
    for bank_id, currency, amount in details:
        pool = lines(bank_id, currency)
        same = [t for t in pool if t.amount == amount]
        free = [t for t in same if t.id not in others and t.id not in used]
        if free:
            hit = free[0]
            used.add(hit.id)
            # Two free lines of the same amount: the engine will ask a person.
            several = len(free) > 1 and not any(
                a == amount and (b, c) == (bank_id, currency)
                for b, c, a in details[len(out_details) + 1:]
            )
            out_details.append({"status": "SEVERAL" if several else "FOUND",
                                "bank_date": hit.txn_date.isoformat(),
                                "description": hit.description})
        elif any(t.id in others for t in same):
            out_details.append({"status": "TAKEN", "bank_date": None,
                                "description": "Already matched to another sheet"})
        elif not pool:
            out_details.append({"status": "NO_STATEMENT", "bank_date": None, "description": None})
        else:
            out_details.append({"status": "NOT_FOUND", "bank_date": None, "description": None})

    listed = {(b, c) for b, c, _ in details}
    out_totals = []
    for bank_id, currency, amount in totals:
        if (bank_id, currency) in listed:
            out_totals.append({"status": "LISTED"})
            continue
        day = [t for t in lines(bank_id, currency)
               if t.txn_date == business_date and t.id not in others and t.id not in used]
        if not lines(bank_id, currency):
            out_totals.append({"status": "NO_STATEMENT"})
            continue
        combos = find_combinations([(t.id, t.amount) for t in day], amount)
        if combos and len(combos) == 1:
            used.update(combos[0])
            out_totals.append({"status": "FOUND"})
        elif combos is None or (combos and len(combos) > 1):
            out_totals.append({"status": "AMBIGUOUS"})
        else:
            out_totals.append({"status": "NOT_FOUND"})
    return {"details": out_details, "totals": out_totals}
