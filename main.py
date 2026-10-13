"""DataPulse AI - FastAPI application."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api import admin, analytics, assistant, auth, incidents, pipelines, reports, uploads
from app.config import get_settings
from app.database.connection import get_engine, init_db

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("datapulse.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("DataPulse AI started (env=%s, db=%s, llm=%s)", settings.app_env,
                get_engine().url.get_backend_name(), "configured" if settings.llm_configured else "fallback")
    yield


app = FastAPI(
    title="DataPulse AI API",
    version="1.0.0",
    description="Intelligent data pipeline monitoring, root-cause analysis and controlled recovery.",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    logger.debug("%s %s -> %s (%.1f ms)", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Request validation failed.", "errors": errors})


@app.exception_handler(OperationalError)
async def db_unavailable_handler(_: Request, exc: OperationalError):
    logger.error("Database unavailable: %s", type(exc.orig).__name__ if exc.orig else exc)
    return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Try again shortly."})


@app.exception_handler(SQLAlchemyError)
async def db_error_handler(_: Request, exc: SQLAlchemyError):
    logger.exception("Database error")
    return JSONResponse(status_code=500, content={"detail": "A database error occurred. The incident was logged."})


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred. The incident was logged."})


for router in (auth.router, uploads.router, pipelines.router, incidents.router, analytics.router,
               assistant.router, reports.router, admin.router):
    app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return JSONResponse(status_code=200 if db_ok else 503,
                        content={"status": "ok" if db_ok else "degraded", "database": db_ok,
                                 "llm_configured": settings.llm_configured, "version": app.version})
