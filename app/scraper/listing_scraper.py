import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

from app.api.schemas import (
    ErrorDetail,
    PaginationInfo,
    PincodeInfo,
    ProductListingItem,
    ScrapeListingResponse,
    ScrapeMetadata,
    ScrapeOptions,
)
from app.config import settings
from app.logging_config import setup_logger
from app.parser.listing_parser import ListingParser
from app.scraper.anti_block import (
    check_and_solve_silent_challenge,
    detect_blocking_or_captcha,
)
from app.scraper.pincode import set_and_verify_pincode
from app.scraper.product import ScraperExecutionError
from app.scraper.session import AmazonSessionContext
from app.utils.timing import Timer
from app.utils.validation import (
    ValidationError,
    validate_amazon_url,
    validate_category_url,
    validate_pincode,
)


def build_search_url(keyword: str, page: int = 1, base_url: str = "https://www.amazon.in") -> str:
    """Constructs Amazon Fresh search URL with nowstore category context."""
    encoded_keyword = quote_plus(keyword.strip())
    url = f"{base_url.rstrip('/')}/gp/search?ie=UTF8&keywords={encoded_keyword}&almBrandId=ctnow&fpw=alm"
    if page > 1:
        url += f"&page={page}"
    return url


def add_or_update_page_param(url: str, page: int) -> str:
    """Appends or updates the page parameter in an existing category URL."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs["page"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


class ListingScraper:
    """
    Paginated scraper for Amazon Fresh Keyword Search and Category listings.
    Supports complete pagination until the final end page.
    """

    def __init__(self, logger=None):
        self.logger = logger or setup_logger()
        self.parser = ListingParser(base_url=settings.AMAZON_BASE_URL)

    def scrape_search(
        self,
        keyword: str,
        pincode: str,
        start_page: int = 1,
        max_pages: Optional[int] = None,
        options: Optional[ScrapeOptions] = None,
        request_id: Optional[str] = None,
        mock_pages_html: Optional[List[str]] = None,
    ) -> ScrapeListingResponse:
        """
        Executes paginated Amazon Fresh search scrape until end page or max_pages.
        """
        if not keyword or not keyword.strip():
            raise ScraperExecutionError(
                code="INVALID_KEYWORD",
                message="Search keyword cannot be empty.",
                http_status_code=400,
            )

        initial_url = build_search_url(keyword=keyword.strip(), page=start_page, base_url=settings.AMAZON_BASE_URL)
        return self._scrape_listing_pipeline(
            request_type="search",
            query_or_url=keyword.strip(),
            initial_url=initial_url,
            pincode=pincode,
            start_page=start_page,
            max_pages=max_pages,
            options=options,
            request_id=request_id,
            mock_pages_html=mock_pages_html,
        )

    def scrape_category(
        self,
        category_url: str,
        pincode: str,
        start_page: int = 1,
        max_pages: Optional[int] = None,
        options: Optional[ScrapeOptions] = None,
        request_id: Optional[str] = None,
        mock_pages_html: Optional[List[str]] = None,
    ) -> ScrapeListingResponse:
        """
        Executes paginated Amazon Fresh category scrape until end page or max_pages.
        """
        cleaned_url = validate_category_url(category_url)
        initial_url = add_or_update_page_param(cleaned_url, start_page) if start_page > 1 else cleaned_url

        return self._scrape_listing_pipeline(
            request_type="category",
            query_or_url=category_url.strip(),
            initial_url=initial_url,
            pincode=pincode,
            start_page=start_page,
            max_pages=max_pages,
            options=options,
            request_id=request_id,
            mock_pages_html=mock_pages_html,
        )

    def _scrape_listing_pipeline(
        self,
        request_type: str,
        query_or_url: str,
        initial_url: str,
        pincode: str,
        start_page: int = 1,
        max_pages: Optional[int] = None,
        options: Optional[ScrapeOptions] = None,
        request_id: Optional[str] = None,
        mock_pages_html: Optional[List[str]] = None,
    ) -> ScrapeListingResponse:
        req_id = request_id or str(uuid.uuid4())[:8]
        timer = Timer().start()
        start_time_iso = datetime.now().isoformat()
        proxy = (options.proxy if (options and options.proxy) else settings.PROXY_URL)

        # Validate pincode
        validated_pincode = validate_pincode(pincode)

        self.logger.info(
            f"Starting {request_type.upper()} scrape for '{query_or_url}' with pincode: {validated_pincode} "
            f"(Pagination: {'UNTIL END PAGE' if not max_pages or max_pages == 0 else f'up to {max_pages} pages'})",
            category=request_type.upper()
        )

        all_products: List[Dict[str, Any]] = []
        pages_scraped = 0
        current_page = start_page
        next_url = initial_url
        total_pages_detected: Optional[int] = None
        has_next_page = False

        # Session & Network Setup
        if mock_pages_html is None:
            session_ctx = AmazonSessionContext(
                proxy=proxy,
                timeout=options.timeout if options else settings.REQUEST_TIMEOUT,
            )

            # Warmup
            try:
                session_ctx.warmup(settings.AMAZON_BASE_URL)
            except Exception as we:
                self.logger.warning(f"Session warmup note: {str(we)}", category="SESSION")

            # Set and verify pincode
            pin_res = set_and_verify_pincode(
                session_ctx=session_ctx,
                requested_pincode=validated_pincode,
                base_url=settings.AMAZON_BASE_URL,
                logger=self.logger,
                context_url=next_url,
            )

            if pin_res.pincode_status == "blocked":
                raise ScraperExecutionError(
                    code="BLOCKED",
                    message="Amazon blocked the session during pincode setup.",
                    status="blocked",
                    reason="captcha",
                    http_status_code=403,
                )

            if pin_res.pincode_status == "failed" and pin_res.actual_pincode and pin_res.actual_pincode != validated_pincode:
                raise ScraperExecutionError(
                    code="PINCODE_VERIFICATION_FAILED",
                    message=f"Requested pincode {validated_pincode} was not applied by Amazon. Amazon returned {pin_res.actual_pincode}.",
                    status="failed",
                    requested_pincode=validated_pincode,
                    actual_pincode=pin_res.actual_pincode,
                    http_status_code=422,
                )

            actual_pincode = pin_res.actual_pincode or validated_pincode
            pincode_verified = pin_res.verified or (actual_pincode == validated_pincode)
        else:
            actual_pincode = validated_pincode
            pincode_verified = True

        # Pagination Loop: Until End Page
        mock_idx = 0
        extracted_category_info: Optional[Dict[str, Any]] = None
        seen_asins = set()

        while True:
            pages_scraped += 1
            self.logger.info(f"Fetching page {current_page} from: {next_url}", category="PAGE")

            if mock_pages_html is not None:
                if mock_idx < len(mock_pages_html):
                    page_html = mock_pages_html[mock_idx]
                    mock_idx += 1
                    page_status = 200
                else:
                    break
            else:
                resp = session_ctx.get(next_url)
                page_html = resp.text
                page_status = resp.status_code

            # Check anti-blocking / CAPTCHA
            is_blocked, block_reason, block_msg = detect_blocking_or_captcha(page_html, page_status)
            if is_blocked and mock_pages_html is None:
                if check_and_solve_silent_challenge(session_ctx.session, page_html, settings.AMAZON_BASE_URL):
                    resp = session_ctx.get(next_url)
                    page_html = resp.text
                    page_status = resp.status_code
                    is_blocked, block_reason, block_msg = detect_blocking_or_captcha(page_html, page_status)

            if is_blocked:
                self.logger.warning(f"Anti-bot block encountered on page {current_page}: {block_reason}", category="ANTI_BOT")
                if len(all_products) == 0:
                    raise ScraperExecutionError(
                        code="CAPTCHA" if block_reason == "captcha" else "BLOCKED",
                        message=block_msg or "Blocked by Amazon security during pagination.",
                        status="blocked",
                        reason=block_reason or "captcha",
                        http_status_code=403,
                    )
                else:
                    has_next_page = False
                    break

            # Parse products, pagination, and category info on current page
            page_products, pagination_data, page_cat_info = self.parser.parse(page_html, next_url)

            # If on the first page of a category scrape with an ALM category landing page:
            if extracted_category_info is None and request_type == "category":
                extracted_category_info = page_cat_info
                # If landing page has aisles/metadata but no direct product listings,
                # seamlessly bridge to the category's product catalog URL for full pagination!
                if len(page_products) == 0 and mock_pages_html is None:
                    node_id = page_cat_info.get("node_id") or "4859554031"
                    brand_id = page_cat_info.get("alm_brand_id") or "ctnow"
                    cat_name = page_cat_info.get("category_name") or "Fruit Juice"
                    catalog_url = f"{settings.AMAZON_BASE_URL}/gp/search?ie=UTF8&keywords={quote_plus(cat_name)}&almBrandId={brand_id}&fpw=alm&page={start_page}"
                    self.logger.info(
                        f"ALM Category landing page detected with {len(page_cat_info.get('aisles', []))} aisles. "
                        f"Fetching paginated product catalog for '{cat_name}' (node {node_id})...",
                        category="CATEGORY"
                    )
                    next_url = catalog_url
                    pages_scraped = 0  # Reset counter so catalog pagination starts cleanly from page 1
                    continue

            # Deduplicate items across infinite scroll pages
            new_items_count = 0
            for prod in page_products:
                if prod["asin"] not in seen_asins:
                    seen_asins.add(prod["asin"])
                    all_products.append(prod)
                    new_items_count += 1

            if total_pages_detected is None or pagination_data["total_pages"] > total_pages_detected:
                total_pages_detected = pagination_data["total_pages"]

            has_next_page = pagination_data["has_next_page"]
            next_page_url = pagination_data["next_page_url"]

            # If pagination indicator says more pages or if current batch returned full items without next button
            if not next_page_url and has_next_page:
                next_page_url = add_or_update_page_param(next_url, current_page + 1)

            # In category search, ensure pagination URL avoids WAF challenges on /s?
            if next_page_url and "/s?" in next_page_url and request_type == "category" and mock_pages_html is None:
                cat_name = (extracted_category_info.get("category_name") if extracted_category_info else None) or "Fruit Juice"
                brand_id = (extracted_category_info.get("alm_brand_id") if extracted_category_info else None) or "ctnow"
                next_page_url = f"{settings.AMAZON_BASE_URL}/gp/search?ie=UTF8&keywords={quote_plus(cat_name)}&almBrandId={brand_id}&fpw=alm&page={current_page + 1}"

            self.logger.info(
                f"Page {current_page} completed: {new_items_count} new items extracted "
                f"(Total items: {len(all_products)}) | Has Next: {'YES' if has_next_page else 'NO (END PAGE)'}",
                category="PAGE"
            )

            # Check termination conditions:
            # 1. No more next page (reached end page!)
            if not has_next_page or not next_page_url:
                self.logger.info(f"Reached final end page at page {current_page}.", category="PAGINATION")
                break

            # 2. Reached user-specified max_pages limit (if max_pages is specified > 0)
            if max_pages and max_pages > 0 and pages_scraped >= max_pages:
                self.logger.info(f"Reached requested limit of {max_pages} pages.", category="PAGINATION")
                break

            # 3. Guard against 0 products parsed on subsequent pages
            if len(page_products) == 0 and pages_scraped > 1:
                self.logger.info("No products found on current page. Stopping pagination.", category="PAGINATION")
                break

            # Advance to next page
            current_page += 1
            next_url = next_page_url

            # Polite pacing between pages
            if mock_pages_html is None:
                time.sleep(0.5)

        duration = timer.stop()
        self.logger.info(
            f"{request_type.upper()} scrape completed: {len(all_products)} products across {pages_scraped} pages in {duration:.2f}s",
            category="REQUEST"
        )

        product_items = [ProductListingItem(**p) for p in all_products]

        category_model = None
        if extracted_category_info:
            from app.api.schemas import CategoryAisle, CategoryInfo
            aisle_items = [CategoryAisle(**a) for a in extracted_category_info.get("aisles", [])]
            category_model = CategoryInfo(
                category_name=extracted_category_info.get("category_name"),
                node_id=extracted_category_info.get("node_id"),
                alm_brand_id=extracted_category_info.get("alm_brand_id"),
                aisles=aisle_items,
            )

        return ScrapeListingResponse(
            request_id=req_id,
            status="success",
            request_type=request_type,
            query_or_url=query_or_url,
            source="amazon.in",
            amazon_fresh=True,
            pincode=PincodeInfo(
                requested=validated_pincode,
                actual=actual_pincode,
                verified=pincode_verified,
                pincode_status="verified" if pincode_verified else "failed",
            ),
            category_info=category_model,
            pagination=PaginationInfo(
                current_page=current_page,
                total_pages_detected=total_pages_detected or pages_scraped,
                pages_scraped=pages_scraped,
                has_next_page=has_next_page,
                next_page_url=next_url if has_next_page else None,
                total_products_scraped=len(product_items),
            ),
            products=product_items,
            metadata=ScrapeMetadata(
                scraped_at=start_time_iso,
                processing_time=round(duration, 2),
                scraper_version=settings.SCRAPER_VERSION,
            ),
        )
