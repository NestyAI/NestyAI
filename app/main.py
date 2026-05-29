from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.models import router as models_router
from app.core.errors import APIError, build_error_response
from app.deps import get_settings
from app.utils.logging import get_logger


logger = get_logger("nesty.api")
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Personal AI Gateway Server",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "Personal AI Gateway Server",
    }


app.include_router(health_router)
app.include_router(models_router)
app.include_router(chat_router)


@app.exception_handler(APIError)
async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    payload = build_error_response(exc.code, exc.message, exc.details)
    return JSONResponse(status_code=exc.status_code, content=payload)


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
