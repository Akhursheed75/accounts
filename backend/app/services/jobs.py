"""A work queue in Postgres.

PDF work (OCR especially) is far too slow to do inside a request, but adding a
broker to a four-bank accounting system is a service to run, monitor and
restart. SELECT ... FOR UPDATE SKIP LOCKED gives a queue with the same
at-least-once behaviour using the database already present."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Job

log = logging.getLogger(__name__)

PROCESS_STATEMENT = "PROCESS_STATEMENT"


def enqueue(db: Session, kind: str, payload: dict, *, max_attempts: int = 3) -> Job:
    job = Job(kind=kind, payload=payload, status="QUEUED", max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def claim(db: Session) -> Job | None:
    """Takes one queued job, invisible to any other worker doing the same."""
    row = db.execute(
        text(
            """
            SELECT id FROM jobs
             WHERE status = 'QUEUED'
               AND (run_after IS NULL OR run_after <= now())
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
            """
        )
    ).first()
    if row is None:
        return None
    job = db.get(Job, row[0])
    job.status = "RUNNING"
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    db.flush()
    return job


def finish(db: Session, job: Job) -> None:
    job.status = "DONE"
    job.finished_at = datetime.now(UTC)
    job.error = None


def fail(db: Session, job: Job, error: str) -> None:
    job.error = error[:4000]
    if job.attempts >= job.max_attempts:
        job.status = "FAILED"
        job.finished_at = datetime.now(UTC)
    else:
        job.status = "QUEUED"
        # Back off so a transient failure does not spin.
        job.run_after = datetime.now(UTC) + timedelta(seconds=30 * job.attempts)


def reclaim_stuck(db: Session, older_than_minutes: int = 30) -> int:
    """A worker killed mid-job leaves a RUNNING row that nothing will retry."""
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    stuck = list(
        db.scalars(select(Job).where(Job.status == "RUNNING", Job.started_at < cutoff))
    )
    for job in stuck:
        job.status = "QUEUED" if job.attempts < job.max_attempts else "FAILED"
        job.error = (job.error or "") + " | reclaimed after the worker stopped responding"
    return len(stuck)
