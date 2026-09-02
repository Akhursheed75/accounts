"""Background worker.

Run one or more of these next to the API: `python -m app.worker`. Each claims
jobs the others cannot see, so scaling up is just running another one."""
from __future__ import annotations

import logging
import signal
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import jobs
from app.services.statement_processing import process_statement

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [worker] %(message)s")
log = logging.getLogger("worker")

_running = True


def _stop(signum, frame) -> None:
    global _running
    log.info("stopping after the current job")
    _running = False


HANDLERS = {
    jobs.PROCESS_STATEMENT: lambda db, payload: process_statement(
        db, payload["statement_id"], auto_match=payload.get("auto_match", True)
    ),
}


def run_once() -> bool:
    """Returns True when a job was handled."""
    db = SessionLocal()
    try:
        job = jobs.claim(db)
        if job is None:
            db.commit()
            return False
        kind, payload, job_id = job.kind, dict(job.payload), job.id
        db.commit()
    except Exception:
        db.rollback()
        log.exception("could not claim a job")
        db.close()
        return False

    handler = HANDLERS.get(kind)
    db = SessionLocal()
    try:
        from app.models import Job

        job = db.get(Job, job_id)
        if handler is None:
            jobs.fail(db, job, f"No handler is registered for job kind '{kind}'.")
            db.commit()
            return True
        log.info("running job %s (%s)", job_id, kind)
        handler(db, payload)
        job = db.get(Job, job_id)
        jobs.finish(db, job)
        db.commit()
        log.info("job %s done", job_id)
    except Exception as exc:
        db.rollback()
        try:
            from app.models import Job

            job = db.get(Job, job_id)
            jobs.fail(db, job, f"{type(exc).__name__}: {exc}")
            db.commit()
        except Exception:
            db.rollback()
            log.exception("could not record the failure of job %s", job_id)
        log.exception("job %s failed", job_id)
    finally:
        db.close()
    return True


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started, polling every %ss", settings.worker_poll_seconds)

    db = SessionLocal()
    try:
        reclaimed = jobs.reclaim_stuck(db)
        db.commit()
        if reclaimed:
            log.warning("re-queued %s job(s) left running by a previous worker", reclaimed)
    finally:
        db.close()

    idle_cycles = 0
    while _running:
        did_work = run_once()
        if did_work:
            idle_cycles = 0
            continue
        idle_cycles += 1
        if idle_cycles % 150 == 0:
            db = SessionLocal()
            try:
                jobs.reclaim_stuck(db)
                db.commit()
            finally:
                db.close()
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
