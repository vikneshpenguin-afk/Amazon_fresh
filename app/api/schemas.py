from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class ScrapeOptions(BaseModel):
    proxy: Optional[str] = Field(None, description="HTTP/HTTPS proxy to route requests through")
    debug: Optional[bool] = Field(False, description="Enable debug directory capture")
    save_html: Optional[bool] = Field(False, description="Persist raw response HTML")
    timeout: Optional[int] = Field(20, description="HTTP request timeout in seconds")


class ScrapeProductRequest(BaseModel):
    request_type: Literal["product"] = Field("product", description="Scraper operation type: product")
    url: str = Field(..., description="Full Amazon Fresh product page URL")
    pincode: str = Field(..., description="6-digit Indian delivery pincode (e.g. 600002)")
    apikey: Optional[str] = Field(None, description="API authentication key")
    options: Optional[ScrapeOptions] = Field(default_factory=ScrapeOptions, description="Optional scraper configuration")

    @model_validator(mode="before")
    @classmethod
    def resolve_api_key_alias(cls, values):
        if isinstance(values, dict):
            if "apikey" not in values and "api_key" in values:
                values["apikey"] = values.get("api_key")
        return values

    model_config = {
        "json_schema_extra": {
            "example": {
                "request_type": "product",
                "url": "https://www.amazon.in/Mr-Gold-Groundnut-Oil-Pouch-offer/dp/B07PGD845T?fpw=alm&almBrandId=ctnow",
                "pincode": "600002",
                "apikey": "fresh-api-key-2026-secure"
            }
        }
    }


class ScrapeSearchRequest(BaseModel):
    request_type: Literal["search"] = Field("search", description="Scraper operation type: search")
    keyword: str = Field(..., description="Search keyword (e.g. 'maggi', 'groundnut oil', 'milk')")
    pincode: str = Field(..., description="6-digit Indian delivery pincode (e.g. 600002)")
    apikey: Optional[str] = Field(None, description="API authentication key")
    page: Optional[Any] = Field(
        None,
        description="Optional page limit: scrape pages 1 through page. If omitted or empty, scrapes until end page."
    )
    max_pages: Optional[int] = Field(
        None,
        description="Legacy/optional maximum pages to scrape."
    )
    options: Optional[ScrapeOptions] = Field(default_factory=ScrapeOptions)

    @model_validator(mode="before")
    @classmethod
    def resolve_api_key_alias(cls, values):
        if isinstance(values, dict):
            if "apikey" not in values and "api_key" in values:
                values["apikey"] = values.get("api_key")
        return values

    @field_validator("page", mode="before")
    @classmethod
    def validate_page_param(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                return None
            if not v_str.isdigit():
                raise ValueError("page parameter must be a positive integer or numeric string")
            val = int(v_str)
            if val < 1:
                raise ValueError("page parameter must be greater than or equal to 1")
            return val
        if isinstance(v, int):
            if v < 1:
                raise ValueError("page parameter must be greater than or equal to 1")
            return v
        raise ValueError("page parameter must be a positive integer or numeric string")

    model_config = {
        "json_schema_extra": {
            "example": {
                "request_type": "search",
                "keyword": "maggi",
                "pincode": "600002",
                "apikey": "fresh-api-key-2026-secure",
                "page": 2
            }
        }
    }


class ScrapeCategoryRequest(BaseModel):
    request_type: Literal["category"] = Field("category", description="Scraper operation type: category")
    url: str = Field(..., description="Amazon Fresh category page URL (e.g. 'https://www.amazon.in/nowstore/category/dairy')")
    pincode: str = Field(..., description="6-digit Indian delivery pincode (e.g. 600002)")
    apikey: Optional[str] = Field(None, description="API authentication key")
    page: Optional[Any] = Field(
        None,
        description="Optional page limit: scrape pages 1 through page. If omitted or empty, scrapes until end page."
    )
    max_pages: Optional[int] = Field(
        None,
        description="Legacy/optional maximum pages to scrape."
    )
    options: Optional[ScrapeOptions] = Field(default_factory=ScrapeOptions)

    @model_validator(mode="before")
    @classmethod
    def resolve_api_key_alias(cls, values):
        if isinstance(values, dict):
            if "apikey" not in values and "api_key" in values:
                values["apikey"] = values.get("api_key")
        return values

    @field_validator("page", mode="before")
    @classmethod
    def validate_page_param(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                return None
            if not v_str.isdigit():
                raise ValueError("page parameter must be a positive integer or numeric string")
            val = int(v_str)
            if val < 1:
                raise ValueError("page parameter must be greater than or equal to 1")
            return val
        if isinstance(v, int):
            if v < 1:
                raise ValueError("page parameter must be greater than or equal to 1")
            return v
        raise ValueError("page parameter must be a positive integer or numeric string")

    model_config = {
        "json_schema_extra": {
            "example": {
                "request_type": "category",
                "url": "https://www.amazon.in/nowstore/category/dairy",
                "pincode": "600002",
                "apikey": "fresh-api-key-2026-secure",
                "page": 2
            }
        }
    }


# Backwards compatibility aliases
FutureSearchRequest = ScrapeSearchRequest
FutureCategoryRequest = ScrapeCategoryRequest


# Response Models
class PincodeInfo(BaseModel):
    requested: str = Field(..., description="The requested delivery pincode")
    actual: Optional[str] = Field(None, description="The actual pincode Amazon reflected")
    verified: bool = Field(..., description="Whether requested and actual pincodes match")
    pincode_status: Optional[str] = Field(None, description="'verified', 'failed', or 'pending_product_check'")


class ProductData(BaseModel):
    # Identification
    url: str
    final_url: str
    asin: str
    product_id: str

    # Product info
    title: Optional[str] = None
    brand: Optional[str] = None
    store: Optional[str] = None
    product_type: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    breadcrumbs: List[str] = Field(default_factory=list)

    # Pricing
    price: Optional[float] = None
    price_display: Optional[str] = None
    mrp: Optional[float] = None
    mrp_display: Optional[str] = None
    discount: Optional[float] = None
    discount_percent: Optional[float] = None
    unit_price: Optional[str] = None

    # Availability
    availability: Optional[str] = None
    in_stock: Optional[bool] = None
    stock_status: Optional[str] = None

    # Delivery
    requested_pincode: str
    actual_pincode: Optional[str] = None
    delivery_location: Optional[str] = None
    delivery_info: Optional[str] = None
    delivery_date: Optional[str] = None
    delivery_time: Optional[str] = None

    # Seller
    seller: Optional[str] = None
    ships_from: Optional[str] = None

    # Amazon Services
    prime: Optional[bool] = None
    fresh: Optional[bool] = None
    amazon_fresh: Optional[bool] = None

    # Promotions
    coupon: Optional[str] = None
    offers: List[str] = Field(default_factory=list)
    deal: Optional[str] = None
    promotion: Optional[str] = None

    # Product details
    bullets: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    product_details: Dict[str, str] = Field(default_factory=dict)
    manufacturer: Optional[str] = None
    country_of_origin: Optional[str] = None
    manufacturer_part_number: Optional[str] = None
    model: Optional[str] = None

    # Ratings
    rating: Optional[float] = None
    ratings_count: Optional[int] = None
    reviews_count: Optional[int] = None

    # Media
    images: List[str] = Field(default_factory=list)
    videos: List[str] = Field(default_factory=list)

    # Category / Ranking
    bestsellers_rank: Optional[str] = None


class ProductListingItem(BaseModel):
    asin: str
    title: str
    url: str
    brand: Optional[str] = None
    price: Optional[float] = None
    price_display: Optional[str] = None
    mrp: Optional[float] = None
    mrp_display: Optional[str] = None
    discount_percent: Optional[float] = None
    unit_price: Optional[str] = None
    rating: Optional[float] = None
    ratings_count: Optional[int] = None
    image_url: Optional[str] = None
    is_in_stock: bool = True
    badge: Optional[str] = None
    is_sponsored: bool = False
    is_fresh: bool = True


class CategoryAisle(BaseModel):
    title: str
    url: Optional[str] = None
    node_id: Optional[str] = None
    image_url: Optional[str] = None


class CategoryInfo(BaseModel):
    category_name: Optional[str] = None
    node_id: Optional[str] = None
    alm_brand_id: Optional[str] = None
    aisles: List[CategoryAisle] = Field(default_factory=list)


class PaginationInfo(BaseModel):
    current_page: int
    total_pages_detected: Optional[int] = None
    pages_scraped: int
    has_next_page: bool
    next_page_url: Optional[str] = None
    total_products_scraped: int


class ScrapeMetadata(BaseModel):
    scraped_at: str
    processing_time: float
    scraper_version: str


class ScrapeProductResponse(BaseModel):
    request_id: str
    status: str
    request_type: str = "product"
    source: str = "amazon.in"
    amazon_fresh: bool
    pincode: PincodeInfo
    product: Optional[ProductData] = None
    metadata: ScrapeMetadata


class ScrapeListingResponse(BaseModel):
    request_id: str
    status: str
    request_type: str  # "search" or "category"
    query_or_url: str
    source: str = "amazon.in"
    amazon_fresh: bool = True
    pincode: PincodeInfo
    category_info: Optional[CategoryInfo] = None
    pagination: PaginationInfo
    products: List[ProductListingItem] = Field(default_factory=list)
    metadata: ScrapeMetadata


class ErrorDetail(BaseModel):
    code: str
    message: str
    requested_pincode: Optional[str] = None
    actual_pincode: Optional[str] = None
    field: Optional[str] = None
    reason: Optional[str] = None


class ErrorResponse(BaseModel):
    request_id: str
    status: str
    error: ErrorDetail
    reason: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
