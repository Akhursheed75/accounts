from __future__ import annotations

from enum import StrEnum


class RecordStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class StatementStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    PARTIALLY_PROCESSED = "PARTIALLY_PROCESSED"
    FAILED = "FAILED"


class ExtractionMethod(StrEnum):
    TEXT = "TEXT"
    OCR = "OCR"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class Direction(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class MatchStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    SUGGESTED = "SUGGESTED"
    REJECTED = "REJECTED"


class MatchType(StrEnum):
    EXACT = "EXACT"
    POSSIBLE = "POSSIBLE"
    MANUAL = "MANUAL"


class ReconStatus(StrEnum):
    """Roll-up status shown in the UI for a transfer or a bank transaction."""

    MATCHED = "MATCHED"
    POSSIBLE = "POSSIBLE"
    UNMATCHED = "UNMATCHED"
    IGNORED = "IGNORED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
