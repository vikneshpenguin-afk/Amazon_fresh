import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.schemas import ErrorDetail, ErrorResponse
from app.config import settings
from app.logging_config import setup_logger

logger = setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Amazon Fresh Scraper API service...", category="SYSTEM")
    yield
    logger.info("Shutting down Amazon Fresh Scraper API service...", category="SYSTEM")


app = FastAPI(
    title="Amazon Fresh Product Page Scraper",
    description=(
        "Production-quality FastAPI service to scrape Amazon Fresh / quick-commerce "
        "product pages with strict delivery pincode validation and verification."
    ),
    version=settings.SCRAPER_VERSION,
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Translates FastAPI/Pydantic validation errors into the professional ErrorResponse format (Requirement 7).
    """
    errors = exc.errors()
    field_name = "unknown"
    error_msg = "Invalid input request"
    code = "VALIDATION_ERROR"

    if errors:
        first_err = errors[0]
        loc = first_err.get("loc", [])
        field_name = str(loc[-1]) if loc else "unknown"
        error_msg = first_err.get("msg", "Invalid value provided.")

        if "url" in field_name:
            code = "INVALID_URL"
        elif "pincode" in field_name:
            code = "INVALID_PINCODE"
        elif "request_type" in field_name:
            code = "INVALID_REQUEST_TYPE"

    req_id = str(uuid.uuid4())[:8]
    error_response = ErrorResponse(
        request_id=req_id,
        status="failed",
        error=ErrorDetail(
            code=code,
            message=f"Validation failed for field '{field_name}': {error_msg}",
            field=field_name,
        )
    )
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY if field_name in ("page", "apikey") else status.HTTP_400_BAD_REQUEST
    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(),
    )


# Include API routes
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=settings.DEBUG_MODE)
