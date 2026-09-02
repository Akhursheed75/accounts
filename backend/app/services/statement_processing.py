"""Turning an uploaded PDF into bank transactions.

Two promises govern this file. Nothing is ever silently lost: a row the parser
cannot read leaves the statement PARTIALLY_PROCESSED with the reason attached.
And nothing is ever double-counted: every extracted line carries a fingerprint,
so re-uploading an overlapping period adds only what is genuinely new."""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bank, BankStatement, BankTransaction, MatchSetting, User
from app.parsers.base import NormalizedTransaction, ParserError
from app.parsers.document import PdfDocument
from app.parsers.registry import detect_parser, get_parser
from app.services import audit
from app.services import reconciliation as recon
from app.services.settings_store import match_settings
from app.services.storage import get_storage

log = logging.getLogger(__name__)


def dedupe_hash(account_id: int, txn: NormalizedTransaction) -> str:
    """Identifies a bank line independently of which file it arrived in.

    Reference is included when the bank gives one, because two genuine deposits
    of the same amount on the same day are ordinary — merging them would delete
    real money. The row index is the last resort when there is no reference."""
    parts = [
        str(account_id),
        txn.txn_date.isoformat(),
        f"{txn.amount:.2f}",
        txn.direction,
        txn.currency_code,
        (txn.external_id or txn.reference or "").strip().upper()
        or f"{txn.description.strip().upper()[:60]}#{txn.row_index}",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def process_statement(db: Session, statement_id: int, *, auto_match: bool = True) -> dict:
    statement = db.get(BankStatement, statement_id)
    if statement is None:
        raise ValueError(f"statement {statement_id} no longer exists")

    account = statement.account
    bank = account.bank
    statement.status = "PROCESSING"
    statement.error_message = None
    db.commit()

    try:
        data = get_storage().load(statement.stored_key)
    except Exception as exc:
        return _fail(db, statement, "The stored PDF could not be read back from disk.", exc)

    doc = PdfDocument(data, statement.original_filename)
    try:
        statement.page_count = doc.page_count

        if bank.parser_key:
            parser = get_parser(bank.parser_key)
        else:
            parser = detect_parser(doc)
            if parser is None:
                return _fail(
                    db, statement,
                    f"{bank.name} has no statement parser configured, and this file's "
                    f"layout did not match any of the parsers installed. Set the bank's "
                    f"parser in Settings → Banks, or send a sample so one can be built.",
                )
            # Detection recognised a layout, but it belongs to a different bank
            # that is already set up. Importing it here would file another bank's
            # money under this account, which no later correction fully undoes.
            owner = db.scalar(select(Bank).where(Bank.parser_key == parser.key))
            if owner is not None and owner.id != bank.id:
                return _fail(
                    db, statement,
                    f"This file is laid out like a {owner.name} statement, but the "
                    f"account you chose belongs to {bank.name}. Upload it to a "
                    f"{owner.name} account, or set {bank.name}'s parser explicitly if "
                    f"the two banks really do use the same format.",
                )

        statement.parser_key = parser.key
        if not parser.implemented:
            result_error = None
            try:
                parser.parse(doc, currency_code=account.currency_code)
            except ParserError as exc:
                result_error = str(exc)
            return _fail(db, statement, result_error or "This bank's parser is not built yet.")

        try:
            result = parser.parse(doc, currency_code=account.currency_code)
        except ParserError as exc:
            return _fail(db, statement, str(exc))
        except Exception as exc:  # a parser bug must not look like a bank problem
            log.exception("parser %s crashed on statement %s", parser.key, statement.id)
            return _fail(
                db, statement,
                "The statement could not be read. The technical details have been logged "
                "for the administrator.",
                exc,
            )

        inserted, duplicates = _persist(db, statement, result.transactions)

        statement.extraction_method = result.extraction_method
        statement.transaction_count = inserted
        statement.duplicate_count = duplicates
        statement.warnings = result.warnings or None
        statement.statement_closing_balance = result.closing_balance
        statement.period_start = statement.period_start or result.period_start
        statement.period_end = statement.period_end or result.period_end
        statement.processed_at = datetime.now(UTC)
        statement.status = "PARTIALLY_PROCESSED" if result.partial else "PROCESSED"
        if inserted == 0 and duplicates == 0:
            statement.status = "PARTIALLY_PROCESSED"
            statement.error_message = (
                "The layout was recognised but no transactions were extracted."
            )

        audit.record(
            db, action=audit.Actions.PROCESS_STATEMENT, module="statements",
            record_type="bank_statement", record_id=statement.id,
            summary=(f"Processed {statement.original_filename} with {parser.key} "
                     f"({result.extraction_method}): {inserted} new, {duplicates} already known"),
            new_values={"status": statement.status, "transactions": inserted,
                        "duplicates": duplicates, "warnings": result.warnings},
        )
        db.commit()

        matched = 0
        if auto_match and inserted:
            settings = match_settings(db)
            matched = _rematch_open_transfers(db, settings)
            db.commit()

        return {
            "statement_id": statement.id,
            "status": statement.status,
            "parser": parser.key,
            "extraction_method": result.extraction_method,
            "inserted": inserted,
            "duplicates": duplicates,
            "warnings": result.warnings,
            "auto_matched": matched,
        }
    finally:
        doc.close()


def _persist(
    db: Session, statement: BankStatement, transactions: list[NormalizedTransaction]
) -> tuple[int, int]:
    account_id = statement.bank_account_id
    existing = set(
        db.scalars(
            select(BankTransaction.dedupe_hash).where(
                BankTransaction.bank_account_id == account_id
            )
        )
    )
    inserted = duplicates = 0
    seen_in_file: set[str] = set()
    for txn in transactions:
        fingerprint = dedupe_hash(account_id, txn)
        if fingerprint in existing or fingerprint in seen_in_file:
            duplicates += 1
            continue
        seen_in_file.add(fingerprint)
        db.add(
            BankTransaction(
                statement_id=statement.id,
                bank_account_id=account_id,
                bank_id=statement.account.bank_id,
                txn_date=txn.txn_date,
                value_date=txn.value_date,
                description=txn.description,
                reference=txn.reference,
                external_id=txn.external_id,
                movement_type=txn.movement_type,
                debit=txn.debit,
                credit=txn.credit,
                amount=txn.amount,
                direction=txn.direction,
                currency_code=txn.currency_code,
                running_balance=txn.running_balance,
                row_index=txn.row_index,
                page_number=txn.page_number,
                raw_text=txn.raw_text,
                extraction_confidence=txn.confidence,
                dedupe_hash=fingerprint,
                is_demo=statement.is_demo,
            )
        )
        inserted += 1
    db.flush()
    return inserted, duplicates


def _rematch_open_transfers(db: Session, settings: MatchSetting) -> int:
    """New bank rows can complete matches for payments entered days ago."""
    from app.models import ShopDailyRecord, ShopTransfer

    stmt = (
        select(ShopTransfer)
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .where(
            ShopTransfer.deleted_at.is_(None),
            ShopTransfer.is_ignored.is_(False),
            ShopDailyRecord.deleted_at.is_(None),
        )
    )
    matched = 0
    for transfer in db.scalars(stmt):
        outcome = recon.run_for_transfer(db, transfer, settings)
        if outcome["outcome"] == "matched":
            matched += 1
    return matched


def _fail(
    db: Session, statement: BankStatement, message: str, exc: Exception | None = None
) -> dict:
    if exc is not None:
        log.exception("statement %s failed: %s", statement.id, message)
    statement.status = "FAILED"
    statement.error_message = message
    statement.processed_at = datetime.now(UTC)
    audit.record(
        db, action=audit.Actions.PROCESS_STATEMENT, module="statements",
        record_type="bank_statement", record_id=statement.id,
        summary=f"Processing failed for {statement.original_filename}",
        new_values={"status": "FAILED", "error": message},
    )
    db.commit()
    return {"statement_id": statement.id, "status": "FAILED", "error": message}
