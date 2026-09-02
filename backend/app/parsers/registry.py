"""The set of statement parsers this build ships with.

Adding a bank means adding a parser class here and pointing the bank's
parser_key at it. Nothing else in the system needs to change."""
from __future__ import annotations

import logging

from app.parsers.bac import BacParser
from app.parsers.banpro import BanproParser
from app.parsers.base import BaseParser, ParserError
from app.parsers.document import PdfDocument
from app.parsers.fichosa import FichosaParser
from app.parsers.lafise import LafiseParser

log = logging.getLogger(__name__)

_PARSER_CLASSES: list[type[BaseParser]] = [
    BacParser,
    LafiseParser,
    BanproParser,
    FichosaParser,
]

PARSERS: dict[str, BaseParser] = {cls.key: cls() for cls in _PARSER_CLASSES}


def parser_keys() -> list[str]:
    return sorted(PARSERS)


def implemented_parser_keys() -> list[str]:
    return sorted(k for k, p in PARSERS.items() if p.implemented)


def has_parser(key: str | None) -> bool:
    parser = PARSERS.get(key or "")
    return bool(parser and parser.implemented)


def get_parser(key: str | None) -> BaseParser:
    parser = PARSERS.get((key or "").upper())
    if parser is None:
        raise ParserError(
            f"No statement parser named '{key}' exists. Set the bank's parser in "
            f"Settings → Banks to one of: {', '.join(parser_keys())}."
        )
    return parser


def detect_parser(doc: PdfDocument) -> BaseParser | None:
    """Used when a bank has no parser configured: ask each parser whether it
    recognises the file. Returns None rather than guessing."""
    for parser in PARSERS.values():
        if not parser.implemented:
            continue
        try:
            if parser.can_parse(doc):
                return parser
        except Exception:  # a detector must never take the upload down
            log.exception("parser %s failed during detection", parser.key)
    return None
