from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.deps import require
from app.core.errors import Conflict, NotFound, PayloadTooLarge, UnsupportedFile, ValidationFailed
from app.core.security import sha256_bytes
from app.db.session import get_db
from app.models import BankAccount, BankStatement, BankTransaction, User
from app.parsers.registry import has_parser
from app.schemas.banking import StatementOut
from app.schemas.common import Message, Page
from app.services import audit, jobs
from app.services.statement_processing import process_statement
from app.services.storage import get_storage, statement_key

router = APIRouter(tags=["statements"])

PDF_MAGIC = b"%PDF-"


def _out(statement: BankStatement) -> StatementOut:
    account = statement.account
    return StatementOut(
        id=statement.id,
        bank_account_id=statement.bank_account_id,
        bank_id=account.bank_id if account else None,
        bank_code=account.bank.code if account and account.bank else None,
        bank_name=account.bank.name if account and account.bank else None,
        account_label=account.label if account else None,
        currency_code=account.currency_code if account else None,
        period_start=statement.period_start, period_end=statement.period_end,
        original_filename=statement.original_filename, file_size=statement.file_size,
        page_count=statement.page_count, status=statement.status,
        parser_key=statement.parser_key, extraction_method=statement.extraction_method,
        error_message=statement.error_message, warnings=statement.warnings,
        transaction_count=statement.transaction_count,
        duplicate_count=statement.duplicate_count,
        statement_closing_balance=statement.statement_closing_balance,
        uploaded_by_id=statement.uploaded_by_id,
        created_at=statement.created_at, processed_at=statement.processed_at,
        is_demo=statement.is_demo,
    )


@router.get("/statements", response_model=Page[StatementOut])
def list_statements(
    bank_id: int | None = None,
    bank_account_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.read")),
) -> Page[StatementOut]:
    stmt = select(BankStatement).where(BankStatement.deleted_at.is_(None))
    if bank_account_id:
        stmt = stmt.where(BankStatement.bank_account_id == bank_account_id)
    if bank_id:
        stmt = stmt.join(BankAccount).where(BankAccount.bank_id == bank_id)
    if status:
        stmt = stmt.where(BankStatement.status == status.upper())
    if date_from:
        stmt = stmt.where(BankStatement.period_end >= date_from)
    if date_to:
        stmt = stmt.where(BankStatement.period_start <= date_to)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(BankStatement.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    return Page(items=[_out(s) for s in rows], total=total, page=page, page_size=page_size)


@router.get("/statements/{statement_id}", response_model=StatementOut)
def get_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.read")),
) -> StatementOut:
    statement = db.get(BankStatement, statement_id)
    if not statement or statement.deleted_at:
        raise NotFound("That statement does not exist.")
    return _out(statement)


@router.post("/statements/upload", response_model=StatementOut, status_code=201)
async def upload_statement(
    bank_account_id: int = Form(...),
    period_start: date | None = Form(None),
    period_end: date | None = Form(None),
    process_now: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.upload")),
) -> StatementOut:
    account = db.get(BankAccount, bank_account_id)
    if not account:
        raise NotFound("That bank account does not exist.")
    if not account.is_active:
        raise ValidationFailed("That bank account is inactive.")

    data = await file.read()
    if len(data) == 0:
        raise ValidationFailed("The uploaded file is empty.")
    if len(data) > env.max_upload_bytes:
        raise PayloadTooLarge(
            f"The file is {len(data) // 1024 // 1024} MB. The limit is "
            f"{env.max_upload_bytes // 1024 // 1024} MB."
        )
    # Content type is whatever the browser felt like sending, so check the bytes.
    if not data.startswith(PDF_MAGIC):
        raise UnsupportedFile(
            "Only PDF bank statements can be uploaded. This file is not a PDF."
        )
    if (file.content_type or "application/pdf") not in env.allowed_upload_type_list:
        raise UnsupportedFile(f"'{file.content_type}' files are not accepted.")

    file_hash = sha256_bytes(data)
    duplicate = db.scalar(
        select(BankStatement).where(
            BankStatement.bank_account_id == bank_account_id,
            BankStatement.file_hash == file_hash,
            BankStatement.deleted_at.is_(None),
        )
    )
    if duplicate:
        raise Conflict(
            f"This exact file was already uploaded for {account.label} on "
            f"{duplicate.created_at:%d %b %Y}. Open statement #{duplicate.id} instead."
        )

    key = statement_key(
        account.bank.code if account.bank else "BANK", period_start, file.filename or "statement.pdf"
    )
    get_storage().save(key, data)

    statement = BankStatement(
        bank_account_id=bank_account_id,
        period_start=period_start,
        period_end=period_end,
        original_filename=(file.filename or "statement.pdf")[:255],
        stored_key=key,
        file_hash=file_hash,
        file_size=len(data),
        content_type=file.content_type or "application/pdf",
        status="UPLOADED",
        uploaded_by_id=user.id,
    )
    db.add(statement)
    db.flush()
    audit.record(
        db, action=audit.Actions.UPLOAD_STATEMENT, module="statements", user=user,
        record_type="bank_statement", record_id=statement.id,
        summary=f"Uploaded {statement.original_filename} for {account.label}",
        new_values={"account": account.label, "size": len(data), "hash": file_hash[:12]},
    )
    db.commit()

    if process_now:
        # Queued rather than run inline: OCR on a long statement outlasts any
        # sensible HTTP timeout.
        db_job = jobs.enqueue(
            db, jobs.PROCESS_STATEMENT, {"statement_id": statement.id, "auto_match": True}
        )
        db.commit()
    db.refresh(statement)
    return _out(statement)


@router.post("/statements/{statement_id}/process", response_model=dict)
def process_now(
    statement_id: int,
    background: bool = Query(True, description="Queue it for the worker instead of waiting"),
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.upload")),
) -> dict:
    statement = db.get(BankStatement, statement_id)
    if not statement or statement.deleted_at:
        raise NotFound("That statement does not exist.")
    if statement.status == "PROCESSING":
        raise Conflict("This statement is already being processed.")
    if background:
        jobs.enqueue(
            db, jobs.PROCESS_STATEMENT, {"statement_id": statement.id, "auto_match": True}
        )
        db.commit()
        return {"statement_id": statement.id, "status": "QUEUED"}
    return process_statement(db, statement_id)


@router.get("/statements/{statement_id}/file")
def download_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.read")),
) -> Response:
    statement = db.get(BankStatement, statement_id)
    if not statement or statement.deleted_at:
        raise NotFound("That statement does not exist.")
    data = get_storage().load(statement.stored_key)
    # The stored key never reaches the client; the file is streamed by id only.
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "content-disposition": f'inline; filename="{statement.original_filename}"',
            "x-content-type-options": "nosniff",
        },
    )


@router.delete("/statements/{statement_id}", response_model=Message)
def delete_statement(
    statement_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.delete")),
) -> Message:
    statement = db.get(BankStatement, statement_id)
    if not statement or statement.deleted_at:
        raise NotFound("That statement does not exist.")
    matched = db.scalar(
        select(func.count(BankTransaction.id)).where(
            BankTransaction.statement_id == statement_id
        )
    )
    statement.deleted_at = datetime.now(UTC)
    audit.record(
        db, action=audit.Actions.DELETE_STATEMENT, module="statements", user=user,
        record_type="bank_statement", record_id=statement.id,
        summary=f"Archived {statement.original_filename} ({matched} transactions kept)",
    )
    db.commit()
    return Message(
        message="Statement archived. Its transactions and any matches are kept for the audit trail."
    )
