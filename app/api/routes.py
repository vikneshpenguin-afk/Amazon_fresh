import uuid
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.schemas import (
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    ScrapeCategoryRequest,
    ScrapeListingResponse,
    ScrapeProductRequest,
    ScrapeProductResponse,
    ScrapeSearchRequest,
)
from app.config import settings
from config.api_key import validate_api_key
from app.logging_config import setup_logger
from app.scraper.listing_scraper import ListingScraper
from app.scraper.product import ProductScraper, ScraperExecutionError
from app.utils.validation import ValidationError

router = APIRouter()
logger = setup_logger()


@router.get("/", tags=["General"])
async def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.SCRAPER_VERSION,
        "docs_url": "/docs",
        "health_url": "/health",
        "description": "Production Amazon Fresh & Quick-Commerce Scraper API (Product, Search & Category with Full Pagination)",
        "endpoints": {
            "product": "POST /api/v1/scrape/product",
            "search": "POST /api/v1/scrape/search",
            "category": "POST /api/v1/scrape/category",
        }
    }


@router.get("/health", response_model=HealthResponse, tags=["General"])
@router.get("/api/v1/health", response_model=HealthResponse, tags=["General"])
async def health_check():
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        version=settings.SCRAPER_VERSION,
    )


@router.post(
    "/api/v1/scrape/product",
    response_model=ScrapeProductResponse,
    responses={
        200: {"model": ScrapeProductResponse},
        400: {"model": ErrorResponse},
        401: {"description": "Invalid API key"},
        403: {"model": ErrorResponse},
        422: {"description": "Validation Error or Missing API key"},
        500: {"model": ErrorResponse},
    },
    tags=["Scraper"],
    summary="Scrape Amazon Fresh Product Page"
)
async def scrape_product(request: ScrapeProductRequest):
    req_id = str(uuid.uuid4())[:8]

    # 1. Enforce API key authentication before any scraping or session initialization
    is_valid, err_msg = validate_api_key(request.apikey)
    if not is_valid:
        if err_msg == "API key is required":
            logger.warning("Authentication failed: API key is required", category="AUTH")
            return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": "API key is required"})
        else:
            logger.warning("Authentication failed: Invalid API key", category="AUTH")
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid API key"})

    logger.info("API key validated successfully", category="AUTH")

    scraper = ProductScraper(logger=logger)

    try:
        response = scraper.scrape(request=request, request_id=req_id)
        return response
    except ScraperExecutionError as see:
        error_resp = ErrorResponse(
            request_id=req_id,
            status=see.status,
            reason=see.reason,
            error=ErrorDetail(
                code=see.code,
                message=see.message,
                requested_pincode=see.requested_pincode or request.pincode,
                actual_pincode=see.actual_pincode,
                reason=see.reason,
            )
        )
        return JSONResponse(status_code=see.http_status_code, content=error_resp.model_dump())
    except ValidationError as ve:
        error_resp = ErrorResponse(
            request_id=req_id,
            status="failed",
            error=ErrorDetail(
                code=ve.code,
                message=ve.message,
                field=ve.field,
                requested_pincode=request.pincode,
            )
        )
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_resp.model_dump())
    except Exception as exc:
        logger.exception(f"Unexpected error during scrape: {str(exc)}", category="REQUEST")
        error_resp = ErrorResponse(
            request_id=req_id,
            status="failed",
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message=f"An unexpected error occurred: {str(exc)}",
                requested_pincode=request.pincode,
            )
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_resp.model_dump())


@router.post(
    "/api/v1/scrape/search",
    response_model=ScrapeListingResponse,
    responses={
        200: {"model": ScrapeListingResponse},
        400: {"model": ErrorResponse},
        401: {"description": "Invalid API key"},
        403: {"model": ErrorResponse},
        422: {"description": "Validation Error or Missing API key"},
        500: {"model": ErrorResponse},
    },
    tags=["Scraper"],
    summary="Scrape Amazon Fresh Keyword Search (Pages 1 to N or Until End Page)",
    description=(
        "Scrapes Amazon Fresh search results for a keyword and pincode. "
        "Supports optional 'page' parameter: if specified as integer/string N, scrapes pages 1 through N. "
        "If omitted, automatically scrapes until the final end page."
    )
)
async def scrape_search(request: ScrapeSearchRequest):
    req_id = str(uuid.uuid4())[:8]

    # 1. Enforce API key authentication before any scraping or session initialization
    is_valid, err_msg = validate_api_key(request.apikey)
    if not is_valid:
        if err_msg == "API key is required":
            logger.warning("Authentication failed: API key is required", category="AUTH")
            return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": "API key is required"})
        else:
            logger.warning("Authentication failed: Invalid API key", category="AUTH")
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid API key"})

    logger.info("API key validated successfully", category="AUTH")

    # 2. Determine pagination limit
    if request.page is not None:
        page_limit = request.page
        logger.info(f"Page limit set to {page_limit}; scraping pages 1 through {page_limit}", category="PAGINATION")
    elif request.max_pages is not None:
        page_limit = request.max_pages
        logger.info(f"Page limit set to {page_limit}; scraping pages 1 through {page_limit}", category="PAGINATION")
    else:
        page_limit = None
        logger.info("No page limit specified; scraping until end of pagination", category="PAGINATION")

    scraper = ListingScraper(logger=logger)

    try:
        response = scraper.scrape_search(
            keyword=request.keyword,
            pincode=request.pincode,
            start_page=1,
            max_pages=page_limit,
            options=request.options,
            request_id=req_id,
        )
        return response
    except ScraperExecutionError as see:
        error_resp = ErrorResponse(
            request_id=req_id,
            status=see.status,
            reason=see.reason,
            error=ErrorDetail(
                code=see.code,
                message=see.message,
                requested_pincode=see.requested_pincode or request.pincode,
                actual_pincode=see.actual_pincode,
                reason=see.reason,
            )
        )
        return JSONResponse(status_code=see.http_status_code, content=error_resp.model_dump())
    except ValidationError as ve:
        error_resp = ErrorResponse(
            request_id=req_id,
            status="failed",
            error=ErrorDetail(
                code=ve.code,
                message=ve.message,
                field=ve.field,
                requested_pincode=request.pincode,
            )
        )
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_resp.model_dump())
    except Exception as exc:
        logger.exception(f"Unexpected error during search scrape: {str(exc)}", category="SEARCH")
        error_resp = ErrorResponse(
            request_id=req_id,
            status="failed",
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message=f"An unexpected error occurred: {str(exc)}",
                requested_pincode=request.pincode,
            )
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_resp.model_dump())


@router.post(
    "/api/v1/scrape/category",
    response_model=ScrapeListingResponse,
    responses={
        200: {"model": ScrapeListingResponse},
        400: {"model": ErrorResponse},
        401: {"description": "Invalid API key"},
        403: {"model": ErrorResponse},
        422: {"description": "Validation Error or Missing API key"},
        500: {"model": ErrorResponse},
    },
    tags=["Scraper"],
    summary="Scrape Amazon Fresh Category Page (Pages 1 to N or Until End Page)",
    description=(
        "Scrapes an Amazon Fresh category page for a category URL and pincode. "
        "Supports optional 'page' parameter: if specified as integer/string N, scrapes pages 1 through N. "
        "If omitted, automatically scrapes until the final end page."
    )
)
async def scrape_category(request: ScrapeCategoryRequest):
    req_id = str(uuid.uuid4())[:8]

    # 1. Enforce API key authentication before any scraping or session initialization
    is_valid, err_msg = validate_api_key(request.apikey)
    if not is_valid:
        if err_msg == "API key is required":
            logger.warning("Authentication failed: API key is required", category="AUTH")
            return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": "API key is required"})
        else:
            logger.warning("Authentication failed: Invalid API key", category="AUTH")
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid API key"})

    logger.info("API key validated successfully", category="AUTH")

    # 2. Determine pagination limit
    if request.page is not None:
        page_limit = request.page
        logger.info(f"Page limit set to {page_limit}; scraping pages 1 through {page_limit}", category="PAGINATION")
    elif request.max_pages is not None:
        page_limit = request.max_pages
        logger.info(f"Page limit set to {page_limit}; scraping pages 1 through {page_limit}", category="PAGINATION")
    else:
        page_limit = None
        logger.info("No page limit specified; scraping until end of pagination", category="PAGINATION")

    scraper = ListingScraper(logger=logger)

    try:
        response = scraper.scrape_category(
            category_url=request.url,
            pincode=request.pincode,
            start_page=1,
            max_pages=page_limit,
            options=request.options,
            request_id=req_id,
        )
        return response
    except ScraperExecutionError as see:
        error_resp = ErrorResponse(
            request_id=req_id,
            status=see.status,
            reason=see.reason,
            error=ErrorDetail(
                code=see.code,
                message=see.message,
                requested_pincode=see.requested_pincode or request.pincode,
                actual_pincode=see.actual_pincode,
                reason=see.reason,
            )
        )
        return JSONResponse(status_code=see.http_status_code, content=error_resp.model_dump())
    except ValidationError as ve:
        error_resp = ErrorResponse(
            request_id=req_id,
            status="failed",
            error=ErrorDetail(
                code=ve.code,
                message=ve.message,
                field=ve.field,
                requested_pincode=request.pincode,
            )
        )
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_resp.model_dump())
    except Exception as exc:
        logger.exception(f"Unexpected error during category scrape: {str(exc)}", category="CATEGORY")
        error_resp = ErrorResponse(
            request_id=req_id,
            status="failed",
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message=f"An unexpected error occurred: {str(exc)}",
                requested_pincode=request.pincode,
            )
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=error_resp.model_dump())
