from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.deps import assert_shop_access, require
from app.core.errors import (
    Forbidden, NotFound, PayloadTooLarge, UnsupportedFile, ValidationFailed,
)
from app.db.session import get_db
from app.models import SheetPhoto, User
from app.schemas.accounting import PhotoOut
from app.services import monthly, sheet_reader
from app.services.storage import get_storage, safe_filename

router = APIRouter(tags=["accounting"])

IMAGE_TYPES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


def _sniff(data: bytes) -> str | None:
    for magic, kind in IMAGE_TYPES.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _is_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc")


def _read_into(db: Session, photo: SheetPhoto, data: bytes, on: date | None) -> dict | None:
    """Run the reader and keep what it said on the photo. Returns the draft."""
    if not sheet_reader.available():
        return None
    try:
        raw = sheet_reader.read(data)
    except sheet_reader.ReaderFailed as exc:
        photo.extraction_error = str(exc)
        photo.extracted_at = datetime.now(UTC)
        return None
    photo.extraction = raw
    photo.extraction_model = env.sheet_reader_model
    photo.extraction_error = None
    photo.extracted_at = datetime.now(UTC)
    rate_day = on
    if raw.get("date"):
        try:
            rate_day = date.fromisoformat(str(raw["date"])[:10])
        except ValueError:
            pass
    rate_row = monthly.get_rate(db, rate_day or date.today())
    return sheet_reader.to_draft(db, raw, rate=rate_row.nio_per_usd if rate_row else None)


@router.get("/accounting/reader")
def reader_status(user: User = Depends(require("accounting.read"))) -> dict:
    return {"available": sheet_reader.available(),
            "model": env.sheet_reader_model if sheet_reader.available() else None}


@router.post("/accounting/photos", status_code=201)
async def upload_photo(
    file: UploadFile = File(...),
    read: bool = Query(True, description="Read the amounts into a draft of the form"),
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.create")),
) -> dict:
    data = await file.read()
    if not data:
        raise UnsupportedFile("The photo is empty.")
    if len(data) > env.max_photo_bytes:
        raise PayloadTooLarge(
            f"The photo is {len(data) // 1024 // 1024} MB; the limit is "
            f"{env.max_photo_bytes // 1024 // 1024} MB."
        )
    if _is_heic(data):
        raise UnsupportedFile(
            "This is an iPhone HEIC photo. Send it as JPG instead (WhatsApp does this "
            "automatically), or set the camera to 'Most Compatible'."
        )
    kind = _sniff(data)
    if kind is None:
        raise UnsupportedFile("Only JPG, PNG or WebP photos of the sheet can be uploaded.")

    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[kind]
    key = f"sheets/{date.today():%Y/%m}/{uuid.uuid4().hex}.{extension}"
    get_storage().save(key, data)
    photo = SheetPhoto(
        stored_key=key, original_filename=safe_filename(file.filename or f"sheet.{extension}"),
        content_type=kind, file_size=len(data), uploaded_by_id=user.id,
    )
    db.add(photo)
    db.flush()

    result = _read_into(db, photo, data, None) if read else None
    db.commit()
    db.refresh(photo)
    return {
        "photo": PhotoOut.model_validate(photo).model_dump(mode="json"),
        "reader_available": sheet_reader.available(),
        **(result or {"draft": None, "checks": [], "unclear": []}),
    }


def _get_photo(db: Session, user: User, photo_id: int) -> SheetPhoto:
    photo = db.get(SheetPhoto, photo_id)
    if photo is None:
        raise NotFound("That photo does not exist.")
    if photo.daily_record is not None:
        assert_shop_access(user, photo.daily_record.shop_id)
    elif photo.uploaded_by_id != user.id and not user.has_permission("dashboard.view"):
        raise Forbidden("That photo was uploaded by someone else.")
    return photo


@router.get("/accounting/photos/{photo_id}/file")
def photo_file(
    photo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.read")),
) -> Response:
    photo = _get_photo(db, user, photo_id)
    return Response(
        content=get_storage().load(photo.stored_key),
        media_type=photo.content_type,
        headers={"cache-control": "private, max-age=86400", "x-content-type-options": "nosniff"},
    )


@router.post("/accounting/photos/{photo_id}/read")
def reread_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.create")),
) -> dict:
    photo = _get_photo(db, user, photo_id)
    if not sheet_reader.available():
        raise ValidationFailed(
            "Reading photos is not set up on this server (no ANTHROPIC_API_KEY)."
        )
    data = get_storage().load(photo.stored_key)
    on = photo.daily_record.business_date if photo.daily_record else None
    result = _read_into(db, photo, data, on)
    db.commit()
    db.refresh(photo)
    return {
        "photo": PhotoOut.model_validate(photo).model_dump(mode="json"),
        "reader_available": True,
        **(result or {"draft": None, "checks": [], "unclear": []}),
    }
