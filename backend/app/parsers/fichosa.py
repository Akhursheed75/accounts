"""FICHOSA — placeholder.

No FICHOSA statement has been supplied yet, and the columns, date format and
wording differ between Nicaraguan banks enough that writing this parser from
imagination would produce something that looks like it works and quietly
mis-reads real money. So it declines, and says exactly what it needs."""
from __future__ import annotations

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.parsers.document import PdfDocument


class FichosaParser(BaseParser):
    key = "FICHOSA"
    display_name = "FICHOSA (awaiting a sample statement)"
    implemented = False

    def can_parse(self, doc: PdfDocument) -> bool:
        return False

    def parse(self, doc: PdfDocument, *, currency_code: str) -> ParseResult:
        raise ParserError(
            "No parser has been built for FICHOSA yet, because no FICHOSA statement "
            "has been provided to build it from. The PDF has been stored and can be "
            "processed as soon as the parser is added — nothing is lost. Send one "
            "real FICHOSA statement (any month) to have it read automatically."
        )
