from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.models import ErrorDetail, ErrorResponse
from app.protected_routes import router as protected_router
from app.routes import router


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details)
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def create_app(settings_factory: Callable[[], Settings] = get_settings) -> FastAPI:
    settings = settings_factory()
    app = FastAPI(
        title="StockBrief API",
        version=settings.service_version,
        openapi_url=f"{settings.api_base_path}/openapi.json",
        docs_url=f"{settings.api_base_path}/docs",
        redoc_url=f"{settings.api_base_path}/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        _ = request
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = str(exc.detail) if exc.detail else "HTTP error occurred."
        return _error_response(status_code=exc.status_code, code=code, message=message)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        _ = request
        return _error_response(
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details={"errors": exc.errors()},
        )

    app.include_router(router, prefix=settings.api_base_path)
    app.include_router(protected_router, prefix=settings.api_base_path)
    return app


app = create_app()
