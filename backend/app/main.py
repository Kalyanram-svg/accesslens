"""NovaTech Compliance Intelligence — FastAPI application."""
import logging
import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

from app.agents.llm import router as model_router
from app.api import admin, advanced, agent, audits, auth, controls, dashboard, findings
from app.config import get_settings

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("novatech")

app = FastAPI(title=settings.app_name, version="1.0.0-prototype",
              description="AI-powered continuous compliance & audit intelligence (Prototype / Demo environment).")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class RateLimit(BaseHTTPMiddleware):
    """Sliding-window limiter for expensive or sensitive endpoints (per client IP + route family)."""

    LIMITED = {"/api/agent/chat": 20, "/api/agent/run": 20, "/api/auth/login": 15, "/api/documents": 20}

    def __init__(self, app):
        super().__init__(app)
        self.hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        limit = self.LIMITED.get(request.url.path) if request.method == "POST" else None
        if limit:
            limit *= int(os.environ.get("RATE_LIMIT_SCALE", "1"))  # tests raise the ceiling; production keeps defaults
        if limit:
            key = f"{request.client.host if request.client else '?'}:{request.url.path}"
            q, now = self.hits[key], time.monotonic()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                return JSONResponse({"detail": {"code": "RATE_LIMITED", "message": "Too many requests. Please wait a moment."}},
                                    status_code=429, headers={"Retry-After": "30"})
            q.append(now)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp


app.add_middleware(RateLimit)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "message": str(exc.detail)}
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": {"code": "INVALID_INPUT", "message": "Some fields are missing or invalid.",
                                    "fields": [".".join(str(x) for x in e["loc"][1:]) for e in exc.errors()][:10]}}, status_code=422)


@app.exception_handler(OperationalError)
async def db_down(request: Request, exc: OperationalError):
    log.error("database unavailable: %s", type(exc).__name__)
    return JSONResponse({"detail": {"code": "SERVICE_UNAVAILABLE", "message": "The compliance database is temporarily unavailable."}}, status_code=503)


@app.exception_handler(SQLAlchemyError)
async def db_error(request: Request, exc: SQLAlchemyError):
    log.error("database error: %s", type(exc).__name__)
    return JSONResponse({"detail": {"code": "INTERNAL_ERROR", "message": "Something went wrong. No changes were recorded."}}, status_code=500)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": {"code": "INTERNAL_ERROR", "message": "Something went wrong. No changes were recorded."}}, status_code=500)


for r in (auth.router, dashboard.router, agent.router, controls.router, findings.router, audits.router, advanced.router, admin.router):
    app.include_router(r)


@app.on_event("startup")
def _start_scheduler():
    from app.services.scans import start_scheduler

    start_scheduler()


@app.get("/api/health")
def health():
    return {"status": "ok", "environment": "DEMO" if settings.demo_mode else settings.environment,
            "engine": model_router.describe()["engine"]}
