from __future__ import annotations

from io import BytesIO

import pytest

from app.db.session import SessionLocal
from app.models import Job
from app.services import jobs
from app.worker import run_once
from tests.conftest import SAMPLES


def test_uploading_queues_the_work_and_the_worker_does_it(client, admin_headers, world):
    path = SAMPLES / "lafise cordoba Aug-11.pdf"
    if not path.exists():
        pytest.skip("sample missing")
    files = {"file": (path.name, BytesIO(path.read_bytes()), "application/pdf")}
    created = client.post(
        "/api/v1/statements/upload",
        data={
            "bank_account_id": str(world["accounts"]["LAFISE Cordobas"]),
            "process_now": "true",
        },
        files=files, headers=admin_headers,
    ).json()
    assert created["status"] == "UPLOADED"

    session = SessionLocal()
    try:
        queued = session.query(Job).filter(Job.status == "QUEUED").all()
        assert len(queued) == 1
        assert queued[0].payload["statement_id"] == created["id"]
    finally:
        session.close()

    assert run_once() is True
    assert run_once() is False          # the queue is empty again

    after = client.get(f"/api/v1/statements/{created['id']}", headers=admin_headers).json()
    assert after["status"] == "PROCESSED"
    assert after["transaction_count"] == 6


def test_a_job_with_no_handler_fails_loudly_rather_than_vanishing(client, world):
    session = SessionLocal()
    try:
        job = jobs.enqueue(session, "NOT_A_REAL_JOB", {}, max_attempts=1)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    assert run_once() is True

    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        assert job.status == "FAILED"
        assert "No handler" in job.error
    finally:
        session.close()


def test_a_job_left_running_by_a_dead_worker_is_requeued(client, world):
    from datetime import UTC, datetime, timedelta

    session = SessionLocal()
    try:
        job = jobs.enqueue(session, jobs.PROCESS_STATEMENT, {"statement_id": 1})
        job.status = "RUNNING"
        job.started_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()
        job_id = job.id

        assert jobs.reclaim_stuck(session) == 1
        session.commit()
        assert session.get(Job, job_id).status == "QUEUED"
    finally:
        session.close()
