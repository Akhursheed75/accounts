from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.errors import AppError
from app.services import audit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("reconcilia")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Shop accounting and bank reconciliation",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        forwarded = request.headers.get("x-forwarded-for", "")
        client_ip = forwarded.split(",")[0].strip() or (
            request.client.host if request.client else None
        )
        token = audit.request_context.set(
            {
                "ip": client_ip,
                "user_agent": request.headers.get("user-agent"),
                "request_id": request_id,
            }
        )
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            audit.request_context.reset(token)
        response.headers["x-request-id"] = request_id
        elapsed = (time.perf_counter() - started) * 1000
        if elapsed > 1500:
            log.warning("slow request %s %s took %.0fms", request.method, request.url.path, elapsed)
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query")]
            fields.append({"field": ".".join(loc) or "request", "message": err.get("msg", "")})
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "Some of the values sent are not valid.",
                    "details": fields,
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError):
        # Constraint names are how the database reports business rules; translate
        # the ones users can actually hit into plain language.
        text = str(getattr(exc, "orig", exc))
        mapping = {
            "uq_recon_active_bank_txn": "This bank transaction is already reconciled.",
            "uq_recon_active_transfer": "This shop payment is already reconciled.",
            "uq_bank_statements_account_file": "This statement file has already been uploaded for this account.",
            "uq_bank_transactions_account_dedupe": "That bank transaction already exists for this account.",
            "uq_shop_daily_records_shop_date_live": "A record for this shop and date already exists.",
        }
        for key, message in mapping.items():
            if key in text:
                return JSONResponse(
                    status_code=409, content={"error": {"code": "conflict", "message": message}}
                )
        log.exception("unhandled integrity error")
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "conflict",
                    "message": "That change conflicts with data already stored.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "server_error",
                    "message": "Something went wrong on our side. The error has been logged.",
                }
            },
        )

    from app.api.v1 import (
        accounting, audit_log, banks, dashboard, monthly, photos, reconciliation, reports,
        settings_admin, shops, statements, transactions, users,
    )
    from app.api.v1 import auth as auth_router

    for module in (
        auth_router, users, shops, banks, accounting, photos, statements,
        transactions, reconciliation, dashboard, reports, monthly, audit_log, settings_admin,
    ):
        app.include_router(module.router, prefix="/api/v1")

    @app.get("/api/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name, "environment": settings.environment}

    return app


app = create_app()
