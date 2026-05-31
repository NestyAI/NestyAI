from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.health import router as health_router
from app.api.internal_diagnostics import router as internal_diagnostics_router
from app.api.internal_embeddings import router as internal_embeddings_router
from app.api.internal_model_configs import router as internal_model_configs_router
from app.api.models import router as models_router
from app.config import Settings
from app.core.errors import APIError, build_error_response
from app.core.ephemeral_console_key import rotate_ephemeral_console_api_key_from_env
from app.core.http_client import close_shared_async_client
from app.deps import get_settings
from app.middleware.api_version import APIVersionHeaderMiddleware
from app.middleware.body_size import BodySizeLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.storage.db import init_db
from app.utils.logging import get_logger
from app.version import VERSION


logger = get_logger("nesty.api")
_initialized_db_paths: set[str] = set()


def parse_csv_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def validate_runtime_settings(settings: Settings) -> None:
    if not settings.cors_enabled:
        return
    origins = parse_csv_list(settings.cors_allow_origins)
    if (
        settings.app_env.strip().lower() == "production"
        and settings.require_api_key
        and "*" in origins
    ):
        raise RuntimeError(
            "unsafe_cors_configuration: wildcard CORS ('*') is not allowed in production when REQUIRE_API_KEY=true."
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    validate_runtime_settings(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db_path = app_settings.nesty_db_path
        if db_path not in _initialized_db_paths:
            init_db(db_path)
            _initialized_db_paths.add(db_path)
        try:
            rotate_ephemeral_console_api_key_from_env(settings=app_settings)
        except Exception:
            logger.exception("ephemeral_console_key_rotation_unhandled_error")
        try:
            yield
        finally:
            await close_shared_async_client()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="Personal AI Gateway Server",
        lifespan=lifespan,
    )

    app.add_middleware(BodySizeLimitMiddleware, max_request_body_bytes=app_settings.max_request_body_bytes)
    app.add_middleware(APIVersionHeaderMiddleware)

    if app_settings.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware, enable_hsts=app_settings.enable_hsts)

    trusted_hosts = parse_csv_list(app_settings.trusted_hosts)
    if trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

    if app_settings.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=parse_csv_list(app_settings.cors_allow_origins),
            allow_methods=parse_csv_list(app_settings.cors_allow_methods),
            allow_headers=parse_csv_list(app_settings.cors_allow_headers),
            allow_credentials=app_settings.cors_allow_credentials,
        )

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "name": app_settings.app_name,
            "version": VERSION,
            "description": "Personal AI Gateway Server",
            "api_version": "v1",
        }

    app.include_router(health_router)
    app.include_router(models_router)
    app.include_router(chat_router)
    app.include_router(conversations_router)
    app.include_router(internal_model_configs_router)
    app.include_router(internal_embeddings_router)
    app.include_router(internal_diagnostics_router)

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        payload = build_error_response(exc.code, exc.message, exc.details)
        return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        payload = build_error_response(
            code="invalid_request",
            message="Invalid request payload.",
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=400, content=payload)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server error")
        payload = build_error_response(
            code="provider_unavailable",
            message="Unexpected server error.",
            details={},
        )
        return JSONResponse(status_code=500, content=payload)

    return app


app = create_app()
