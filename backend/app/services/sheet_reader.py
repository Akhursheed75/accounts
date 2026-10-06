"""Reading a photo of the handwritten daily sheet.

The photo goes to a vision model with one instruction: copy what is written,
cell by cell, and say which cells were hard to read. Nothing it returns is
saved by itself — it becomes a *draft* of the form, the person checks it
against the photo shown beside it, and only their save writes anything.

The model is asked to fill a fixed structure (a tool call), not to write
prose, so the result can be mapped onto the form without guessing at its
wording. The mapping then runs the paper's own arithmetic and reports where
the sheet disagrees with itself — those are the cells worth a second look."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BaleType, Bank, Shop

log = logging.getLogger(__name__)

MAX_EDGE = 1568          # the model's standard input size; larger is downscaled anyway
JPEG_QUALITY = 88
ZERO = Decimal("0.00")
BANKS = ["BAC", "LAFISE", "BANPRO", "FICOHSA"]


class ReaderUnavailable(RuntimeError):
    pass


class ReaderFailed(RuntimeError):
    pass


def provider() -> str | None:
    """Claude when its key is set, otherwise Gemini's free tier, otherwise none."""
    if settings.anthropic_api_key:
        return "anthropic"
    if settings.gemini_api_key:
        return "gemini"
    return None


def available() -> bool:
    return provider() is not None


def model_name() -> str | None:
    return {"anthropic": settings.sheet_reader_model,
            "gemini": settings.gemini_model}.get(provider() or "")


# ----------------------------------------------------------------- the image
def prepare_image(data: bytes) -> tuple[bytes, str]:
    """Upright, at most MAX_EDGE on the long side, JPEG. Phone photos carry
    their rotation in EXIF; without applying it the sheet arrives sideways."""
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
    except Exception as exc:  # noqa: BLE001
        raise ReaderFailed("The photo could not be opened as an image.") from exc
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.thumbnail((MAX_EDGE, MAX_EDGE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue(), "image/jpeg"


# --------------------------------------------------------- what to extract
NUM = {"type": ["number", "null"]}
INT = {"type": ["integer", "null"]}

SHEET_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": ["string", "null"], "description": "The sheet's date as YYYY-MM-DD (written day/month/year)."},
        "shop": {"type": ["string", "null"], "description": "Shop or city written after CLOSING CASH, e.g. Juigalpa."},
        "bales_sold": {**INT, "description": "QUANTITY OF BALES box."},
        "total_sales_usd": {**NUM, "description": "TOTAL SALES $ box."},
        "other_balances_usd": {**NUM, "description": "OTHER BALANCES $ box (number only)."},
        "total_usd": {**NUM, "description": "TOTAL box in the header row, as written."},
        "invoices": {**INT, "description": "INVOICES box."},
        "cash_received": {
            "type": "object",
            "properties": {"nio": NUM, "usd": NUM, "total_usd": NUM},
            "description": "CASH RECEIVED: the C$ line, the $ line and the TOTAL$ written beside them.",
        },
        "commercial_invoice": {
            "type": "object", "properties": {"cash": NUM, "deposit": NUM, "total_usd": NUM},
        },
        "transfers": {
            "type": "array",
            "description": "The TRANSFERS table: one entry per bank row that has anything written.",
            "items": {
                "type": "object",
                "properties": {
                    "bank": {"type": "string", "enum": BANKS},
                    "usd": {**NUM, "description": "The $ column."},
                    "nio": {**NUM, "description": "The C$ column."},
                    "total_usd": {**NUM, "description": "The TOTAL$ column, as written."},
                },
                "required": ["bank"],
            },
        },
        "deposit_details": {
            "type": "array",
            "description": ("The BAC/LAFISE/BANPRO DETAIL $ and C$ rows near the bottom: every "
                            "separate amount written on each row, e.g. '18000-19030' is two "
                            "amounts 18000 and 19030. Omit rows that are blank."),
            "items": {
                "type": "object",
                "properties": {
                    "bank": {"type": "string", "enum": BANKS},
                    "currency": {"type": "string", "enum": ["USD", "NIO"]},
                    "amounts": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["bank", "currency", "amounts"],
            },
        },
        "expenses": {
            "type": "array",
            "description": ("TOTAL EXPENSES row: each amount, with the word written above or "
                            "below it as its description."),
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "currency": {"type": "string", "enum": ["USD", "NIO"]},
                    "amount": {"type": "number"},
                },
                "required": ["description", "currency", "amount"],
            },
        },
        "expenses_total_usd": {**NUM, "description": "The total written at the end of the expenses row."},
        "delivery": {"type": "object", "properties": {"cash": NUM, "transfers": NUM}},
        "credit_usd": {**NUM, "description": "An amount written in CREDIT / OBSERVATIONS, if any."},
        "observations": {"type": ["string", "null"], "description": "Any text in CREDIT / OBSERVATIONS, copied as written."},
        "bales": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["100LBS", "25LBS"]},
                    "quantity": {**INT, "description": "BALES QUANTITY. For '805+54' this is 805."},
                    "received": {**INT, "description": "For '805+54' this is 54; otherwise null."},
                    "after_closing": {**INT, "description": "AFTER CLOSING."},
                },
                "required": ["type"],
            },
        },
        "starting_balance_usd": NUM,
        "closing_balance_usd": NUM,
        "unclear": {
            "type": "array", "items": {"type": "string"},
            "description": "Names of any fields above whose handwriting you are not sure of.",
        },
    },
    "required": ["transfers", "deposit_details", "expenses", "bales", "unclear"],
}

PROMPT = """This is a photo of a handwritten daily cash sheet ("CLOSING CASH") from a \
clothing-bale shop in Nicaragua. Copy what is written into the record_sheet tool.

How these sheets are written:
- Money is US dollars ($) or Nicaraguan cordobas (C$). In the TRANSFERS table the \
"$" column is dollars, the "C$" column is cordobas, and "TOTAL$" is the shop's own \
dollar total for that bank (cordobas converted at about 37 per dollar).
- In TOTAL EXPENSES, an amount written with "$" is dollars; an amount without a \
symbol (or with C$) is cordobas. Check yourself against the written total: e.g. \
"$204 - $196 - 5000 - 100 = $537" is $204 + $196 + C$5,000 + C$100.
- In the expenses row, dashes separate the amounts; they are not minus signs.
- In the DETAIL rows, dashes separate separate deposits: "18000-19030" is two deposits.
- "805+54" under BALES QUANTITY means 805 bales plus 54 received.
- A line drawn through a cell, or "-0-", means zero / nothing.
- Commas are thousands separators: "17,822" is seventeen thousand eight hundred and twenty-two.

Rules: copy numbers exactly as written; never calculate a value that is not written; \
use null for a blank cell. If a digit is genuinely hard to read, give your best reading \
and add the field name to "unclear"."""


def _call_model(image: bytes, media_type: str) -> dict:
    if not available():
        raise ReaderUnavailable(
            "Reading photos is not set up on this server (no GEMINI_API_KEY or "
            "ANTHROPIC_API_KEY). The photo is kept with the sheet; type the amounts beside it."
        )
    if provider() == "gemini":
        return _call_gemini(image, media_type)
    body = {
        "model": settings.sheet_reader_model,
        "max_tokens": 4000,
        "tools": [{
            "name": "record_sheet",
            "description": "Record the values written on the daily cash sheet.",
            "input_schema": SHEET_SCHEMA,
        }],
        "tool_choice": {"type": "tool", "name": "record_sheet"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": base64.b64encode(image).decode()}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    }
    try:
        response = httpx.post(
            f"{settings.anthropic_base_url.rstrip('/')}/v1/messages",
            json=body,
            headers={
                "x-api-key": settings.anthropic_api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=settings.sheet_reader_timeout,
        )
    except httpx.HTTPError as exc:
        raise ReaderFailed(f"Could not reach the reading service: {exc.__class__.__name__}.") from exc
    if response.status_code != 200:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        log.warning("sheet reader returned %s: %s", response.status_code, detail)
        raise ReaderFailed(
            f"The reading service answered {response.status_code}"
            + (f": {detail[:200]}" if detail else ".")
        )
    for block in response.json().get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "record_sheet":
            return block.get("input") or {}
    raise ReaderFailed("The reading service did not return the sheet's values.")


GEMINI_PROMPT = PROMPT.replace(
    "Copy what is written into the record_sheet tool.",
    "Copy what is written into JSON that follows the schema at the end.",
) + "\n\nAnswer with JSON only, following this JSON schema:\n" + json.dumps(SHEET_SCHEMA)


def _json_from_text(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ReaderFailed("The reading service did not return the sheet's values.")
    try:
        value = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise ReaderFailed("The reading service returned something that is not the sheet's values.") from exc
    if not isinstance(value, dict):
        raise ReaderFailed("The reading service did not return the sheet's values.")
    for key in ("transfers", "deposit_details", "expenses", "bales", "unclear"):
        if not isinstance(value.get(key), list):
            value[key] = []
    return value


def _call_gemini(image: bytes, media_type: str) -> dict:
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": media_type, "data": base64.b64encode(image).decode()}},
                {"text": GEMINI_PROMPT},
            ],
        }],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    url = (f"{settings.gemini_base_url.rstrip('/')}/v1beta/models/"
           f"{settings.gemini_model}:generateContent")
    try:
        response = httpx.post(
            url, json=body,
            headers={"x-goog-api-key": settings.gemini_api_key or "",
                     "content-type": "application/json"},
            timeout=settings.sheet_reader_timeout,
        )
    except httpx.HTTPError as exc:
        raise ReaderFailed(f"Could not reach the reading service: {exc.__class__.__name__}.") from exc
    if response.status_code != 200:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        log.warning("gemini sheet reader returned %s: %s", response.status_code, detail)
        if response.status_code == 429:
            raise ReaderFailed("The free reading limit was reached for now. Try again in a "
                               "minute, or type the amounts.")
        raise ReaderFailed(
            f"The reading service answered {response.status_code}"
            + (f": {detail[:200]}" if detail else ".")
        )
    payload = response.json()
    candidates = payload.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
    text = "".join(p.get("text", "") for p in parts or [])
    if not text:
        reason = (candidates[0].get("finishReason") if candidates
                  else (payload.get("promptFeedback") or {}).get("blockReason"))
        raise ReaderFailed(f"The reading service returned no values ({reason or 'empty answer'}).")
    return _json_from_text(text)


def read(data: bytes) -> dict:
    image, media_type = prepare_image(data)
    return _call_model(image, media_type)


# ------------------------------------------------------- onto the form
def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)
    ).lower().strip()


def _find_shop(db: Session, name: str | None) -> Shop | None:
    if not name:
        return None
    wanted = _fold(name)
    for shop in db.scalars(select(Shop).where(Shop.is_active.is_(True))):
        candidates = [shop.name, shop.code, shop.city.name if getattr(shop, "city", None) else ""]
        if any(c and (_fold(c) == wanted or wanted in _fold(c) or _fold(c) in wanted)
               for c in candidates):
            return shop
    return None


def _bank_ids(db: Session) -> dict[str, int]:
    out = {}
    for bank in db.scalars(select(Bank)):
        out[bank.code.upper()] = bank.id
    # The seed spells FICOHSA's code "FICHOSA", as the paper sheet does.
    if "FICHOSA" in out:
        out.setdefault("FICOHSA", out["FICHOSA"])
    if "FICOHSA" in out:
        out.setdefault("FICHOSA", out["FICOHSA"])
    return out


def to_draft(db: Session, raw: dict, *, rate: Decimal | None = None) -> dict:
    """The form's payload, plus the places where the sheet disagrees with itself."""
    checks: list[str] = []
    banks = _bank_ids(db)

    draft: dict = {"transfers": [], "bank_totals": [], "expenses": [], "bale_records": []}
    parsed_date = None
    if raw.get("date"):
        try:
            parsed_date = date.fromisoformat(str(raw["date"])[:10])
        except ValueError:
            checks.append(f"The date '{raw['date']}' could not be read; choose it below.")
    draft["business_date"] = parsed_date.isoformat() if parsed_date else None

    shop = _find_shop(db, raw.get("shop"))
    draft["shop_id"] = shop.id if shop else None
    if raw.get("shop") and not shop:
        checks.append(f"No shop called '{raw['shop']}' was found; choose the shop below.")
    draft["shop_name_read"] = raw.get("shop")

    draft["bale_count"] = raw.get("bales_sold") or 0
    draft["invoice_count"] = raw.get("invoices") or 0
    sales = _dec(raw.get("total_sales_usd")) or ZERO
    other = _dec(raw.get("other_balances_usd"))
    start = _dec(raw.get("starting_balance_usd"))
    draft["total_sales_usd"] = str(sales)
    draft["opening_balance_usd"] = str(other if other is not None else (start or ZERO))
    written_total = _dec(raw.get("total_usd"))
    if written_total is not None and written_total != sales + (other or ZERO):
        checks.append(
            f"Header: {sales} + {other or 0} = {sales + (other or ZERO)}, but the sheet's "
            f"TOTAL says {written_total}."
        )

    cash = raw.get("cash_received") or {}
    for code, key in (("NIO", "nio"), ("USD", "usd")):
        amount = _dec(cash.get(key))
        if amount and amount > 0:
            draft["transfers"].append(
                {"payment_method": "CASH", "currency_code": code, "amount": str(amount)}
            )

    invoice = raw.get("commercial_invoice") or {}
    draft["commercial_invoice_cash_usd"] = str(_dec(invoice.get("cash")) or ZERO)
    draft["commercial_invoice_deposit_usd"] = str(_dec(invoice.get("deposit")) or ZERO)

    totals: dict[tuple[str, str], Decimal] = {}
    for row in raw.get("transfers") or []:
        bank = str(row.get("bank", "")).upper()
        if bank not in banks:
            continue
        for code, key in (("USD", "usd"), ("NIO", "nio")):
            amount = _dec(row.get(key))
            if amount and amount > 0:
                totals[(bank, code)] = amount
                draft["bank_totals"].append(
                    {"bank_id": banks[bank], "currency_code": code, "amount": str(amount)}
                )
        written = _dec(row.get("total_usd"))
        if rate and written is not None:
            usd = totals.get((bank, "USD"), ZERO)
            nio = totals.get((bank, "NIO"), ZERO)
            computed = (usd + nio / rate).quantize(Decimal("1"))
            if abs(computed - written) > 2:
                checks.append(
                    f"{bank}: ${usd} + C${nio} is about ${computed} at {rate}, but TOTAL$ says {written}."
                )

    for row in raw.get("deposit_details") or []:
        bank = str(row.get("bank", "")).upper()
        code = row.get("currency")
        if bank not in banks or code not in ("USD", "NIO"):
            continue
        amounts = [a for a in (_dec(x) for x in row.get("amounts") or []) if a and a > 0]
        for amount in amounts:
            draft["transfers"].append(
                {"payment_method": "BANK", "bank_id": banks[bank], "currency_code": code,
                 "amount": str(amount)}
            )
        declared = totals.get((bank, code))
        if declared is not None and amounts and sum(amounts) != declared:
            checks.append(
                f"{bank} {'$' if code == 'USD' else 'C$'}: the detail lines add up to "
                f"{sum(amounts)}, but the TRANSFERS table says {declared}."
            )

    expense_usd = ZERO
    expense_nio = ZERO
    for row in raw.get("expenses") or []:
        amount = _dec(row.get("amount"))
        code = row.get("currency") if row.get("currency") in ("USD", "NIO") else "NIO"
        if not amount or amount <= 0:
            continue
        draft["expenses"].append({
            "category": "GENERAL", "description": str(row.get("description") or "")[:255],
            "currency_code": code, "amount": str(amount),
        })
        if code == "USD":
            expense_usd += amount
        else:
            expense_nio += amount
    written_expenses = _dec(raw.get("expenses_total_usd"))
    if rate and written_expenses is not None and draft["expenses"]:
        computed = (expense_usd + expense_nio / rate).quantize(Decimal("1"))
        if abs(computed - written_expenses) > 2:
            checks.append(
                f"Expenses: the items come to about ${computed} at {rate}, but the sheet's "
                f"total is ${written_expenses}. Check which amounts are $ and which C$."
            )

    delivery = raw.get("delivery") or {}
    draft["delivery_cash_usd"] = str(_dec(delivery.get("cash")) or ZERO)
    draft["delivery_transfer_usd"] = str(_dec(delivery.get("transfers")) or ZERO)
    draft["credit_usd"] = str(_dec(raw.get("credit_usd")) or ZERO)
    draft["observations"] = raw.get("observations") or ""
    closing = _dec(raw.get("closing_balance_usd"))
    draft["declared_closing_usd"] = str(closing) if closing is not None else None

    types = {t.code.upper(): t for t in db.scalars(select(BaleType))}
    for row in raw.get("bales") or []:
        bale_type = types.get(str(row.get("type", "")).upper())
        if not bale_type:
            continue
        opening = int(row.get("quantity") or 0)
        received = int(row.get("received") or 0)
        closing_qty = int(row.get("after_closing") or 0)
        draft["bale_records"].append({
            "bale_type_id": bale_type.id, "opening_qty": opening, "received_qty": received,
            "closing_qty": closing_qty, "sold_qty": max(opening + received - closing_qty, 0),
        })
    sold = sum(b["sold_qty"] for b in draft["bale_records"])
    if draft["bale_records"] and raw.get("bales_sold") is not None and sold != raw.get("bales_sold"):
        checks.append(
            f"Bales: opening + received − after closing = {sold}, but QUANTITY OF BALES "
            f"says {raw.get('bales_sold')}."
        )

    return {"draft": draft, "checks": checks, "unclear": list(raw.get("unclear") or [])}
