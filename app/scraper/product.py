import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from app.api.schemas import (
    ErrorDetail,
    ErrorResponse,
    PincodeInfo,
    ProductData,
    ScrapeMetadata,
    ScrapeProductRequest,
    ScrapeProductResponse,
)
from app.config import settings
from app.logging_config import (
    print_completion_banner,
    print_request_banner,
    setup_logger,
)
from app.parser.product_parser import ProductParser
from app.scraper.anti_block import (
    check_and_solve_silent_challenge,
    detect_blocking_or_captcha,
)
from app.scraper.fresh_detection import detect_amazon_fresh
from app.scraper.pincode import set_and_verify_pincode
from app.scraper.session import AmazonSessionContext
from app.utils.timing import Timer
from app.utils.validation import (
    ValidationError,
    validate_amazon_url,
    validate_pincode,
    validate_request_type,
)


class ScraperExecutionError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: str = "failed",
        reason: Optional[str] = None,
        requested_pincode: Optional[str] = None,
        actual_pincode: Optional[str] = None,
        http_status_code: int = 400,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.reason = reason
        self.requested_pincode = requested_pincode
        self.actual_pincode = actual_pincode
        self.http_status_code = http_status_code


class ProductScraper:
    def __init__(self, logger=None):
        self.logger = logger or setup_logger()

    def scrape(
        self,
        request: ScrapeProductRequest,
        request_id: Optional[str] = None,
        mock_html: Optional[str] = None,
    ) -> ScrapeProductResponse:
        """
        Executes the 10-stage Amazon Fresh product scraping pipeline.
        """
        req_id = request_id or str(uuid.uuid4())[:8]
        timer = Timer().start()
        start_time_iso = datetime.now().isoformat()
        proxy = (request.options.proxy if (request.options and request.options.proxy) else settings.PROXY_URL)
        timeout = (request.options.timeout if (request.options and request.options.timeout) else settings.REQUEST_TIMEOUT)
        save_debug = (request.options.save_html if (request.options and request.options.save_html is not None) else settings.SAVE_HTML)

        debug_data: Dict[str, Any] = {
            "homepage_html": "",
            "pincode_response_html": "",
            "product_html": "",
            "metadata": {},
        }

        # Stage 01: VALIDATING INPUT
        self.logger.stage(1, "VALIDATING INPUT")
        try:
            req_type = validate_request_type(request.request_type)
            pincode = validate_pincode(request.pincode)
            cleaned_url, asin = validate_amazon_url(request.url)
        except ValidationError as ve:
            self.logger.error(f"Validation failed: {ve.message}", category="INPUT")
            raise ScraperExecutionError(
                code=ve.code,
                message=ve.message,
                status="failed",
                http_status_code=400,
            )

        self.logger.info(f"URL validated (ASIN: {asin})", category="INPUT")
        self.logger.info(f"Pincode validated: {pincode}", category="INPUT")

        # Print initial debug banner
        print_request_banner(
            logger=self.logger,
            request_id=req_id,
            request_type=req_type,
            url=cleaned_url,
            asin=asin,
            pincode=pincode,
            engine="requests/session",
        )

        actual_pincode: Optional[str] = None
        pincode_verified: bool = False
        amazon_fresh_detected: bool = False
        product_data: Optional[ProductData] = None
        fields_count = 0

        try:
            # Handle testing mode if mock_html is injected
            if mock_html:
                self.logger.stage(2, "CREATING SESSION (MOCK)")
                self.logger.stage(3, "INITIALIZING NETWORK (MOCK)")
                self.logger.stage(4, "SETTING PINCODE (MOCK)")
                self.logger.stage(5, "VERIFYING PINCODE (MOCK)")
                self.logger.stage(6, "FETCHING PRODUCT (MOCK)")
                product_html = mock_html
                final_url = cleaned_url
            else:
                # Stage 02: CREATING SESSION
                self.logger.stage(2, "CREATING SESSION")
                session_ctx = AmazonSessionContext(
                    proxy=proxy,
                    timeout=request.options.timeout if request.options else settings.REQUEST_TIMEOUT,
                )
                self.logger.info("Amazon session created", category="SESSION")

                # Stage 03: INITIALIZING NETWORK
                self.logger.stage(3, "INITIALIZING NETWORK")
                self.logger.info(f"Proxy/session initialized (Proxy: {'configured' if proxy else 'direct'})", category="PROXY")
                try:
                    warmup_res = session_ctx.warmup(settings.AMAZON_BASE_URL)
                    debug_data["homepage_html"] = warmup_res.text
                except Exception as we:
                    self.logger.warning(f"Session warmup note: {str(we)}", category="SESSION")

                # Stage 04: SETTING PINCODE
                self.logger.stage(4, "SETTING PINCODE")
                pin_res = set_and_verify_pincode(
                    session_ctx=session_ctx,
                    requested_pincode=pincode,
                    base_url=settings.AMAZON_BASE_URL,
                    logger=self.logger,
                    context_url=cleaned_url,
                )
                debug_data["pincode_response_html"] = pin_res.raw_response_html or ""

                if pin_res.pincode_status == "blocked":
                    raise ScraperExecutionError(
                        code="BLOCKED",
                        message="Amazon blocked the session during pincode setup.",
                        status="blocked",
                        reason="captcha",
                        http_status_code=403,
                    )

                # Stage 05: VERIFYING PINCODE
                self.logger.stage(5, "VERIFYING PINCODE")
                actual_pincode = pin_res.actual_pincode or pincode
                pincode_verified = pin_res.verified or (actual_pincode == pincode)

                # If GLOW verification reported an explicit mismatch
                if pin_res.pincode_status == "failed" and actual_pincode and actual_pincode != pincode:
                    raise ScraperExecutionError(
                        code="PINCODE_VERIFICATION_FAILED",
                        message=f"Requested pincode {pincode} was not applied by Amazon. Amazon returned {actual_pincode}.",
                        status="failed",
                        requested_pincode=pincode,
                        actual_pincode=actual_pincode,
                        http_status_code=422,
                    )

                # Stage 06: FETCHING PRODUCT
                self.logger.stage(6, "FETCHING PRODUCT")
                self.logger.info("Fetching product page", category="PRODUCT")
                prod_resp = session_ctx.get(cleaned_url)
                product_html = prod_resp.text
                final_url = str(prod_resp.url)
                debug_data["product_html"] = product_html

                # Anti-blocking / CAPTCHA check on product response
                is_blocked, block_reason, block_msg = detect_blocking_or_captcha(product_html, prod_resp.status_code)
                if is_blocked:
                    # Attempt silent challenge resolution if present
                    if check_and_solve_silent_challenge(session_ctx.session, product_html, settings.AMAZON_BASE_URL):
                        self.logger.info("Silent anti-bot challenge completed, retrying product page", category="SESSION")
                        prod_resp = session_ctx.get(cleaned_url)
                        product_html = prod_resp.text
                        final_url = str(prod_resp.url)
                        debug_data["product_html"] = product_html
                        is_blocked, block_reason, block_msg = detect_blocking_or_captcha(product_html, prod_resp.status_code)

                if is_blocked:
                    self.logger.warning(f"Product page blocked: {block_reason}", category="PRODUCT")
                    raise ScraperExecutionError(
                        code="CAPTCHA" if block_reason == "captcha" else "BLOCKED",
                        message=block_msg or "Request blocked by Amazon anti-bot security.",
                        status="blocked",
                        reason=block_reason or "captcha",
                        http_status_code=403,
                    )

            # Stage 07: DETECTING AMAZON FRESH
            self.logger.stage(7, "DETECTING AMAZON FRESH")
            fresh_detection = detect_amazon_fresh(cleaned_url, product_html)
            amazon_fresh_detected = fresh_detection.is_fresh

            if amazon_fresh_detected:
                self.logger.info(f"Fresh page detected (confidence: {fresh_detection.confidence:.2f})", category="PRODUCT")
            else:
                self.logger.warning("Page is NOT Amazon Fresh", category="PRODUCT")
                if settings.STRICT_FRESH_CHECK:
                    raise ScraperExecutionError(
                        code="NOT_FRESH_PRODUCT",
                        message="The requested URL does not belong to Amazon Fresh or quick-commerce.",
                        status="failed",
                        http_status_code=422,
                    )

            # Stage 08: EXTRACTING PRODUCT DATA
            self.logger.stage(8, "EXTRACTING PRODUCT DATA")
            self.logger.info("Extracting product fields", category="PARSER")
            parser = ProductParser(requested_pincode=pincode)
            parsed_dict = parser.parse(
                html=product_html,
                url=cleaned_url,
                asin=asin,
                final_url=final_url,
            )

            # Log field extraction progress
            if parsed_dict.get("title"):
                self.logger.info(f"Title extracted: {parsed_dict['title'][:50]}...", category="PARSER")
            if parsed_dict.get("price"):
                self.logger.info(f"Price extracted: {parsed_dict['price_display']}", category="PARSER")
            if parsed_dict.get("delivery_info"):
                self.logger.info(f"Delivery information extracted: {parsed_dict['delivery_info'][:50]}...", category="PARSER")

            # Update actual pincode from product page if discovered
            prod_page_pincode = parsed_dict.get("actual_pincode")
            if prod_page_pincode:
                actual_pincode = prod_page_pincode

            # Stage 09: VALIDATING RESULT
            self.logger.stage(9, "VALIDATING RESULT")

            # Final Pincode Verification:
            # If actual pincode is detected from either GLOW or Product Page, verify match.
            if actual_pincode:
                if actual_pincode == pincode:
                    pincode_verified = True
                else:
                    # Check if requested pincode was validated via GLOW or appears in delivery info
                    if pincode in (parsed_dict.get("delivery_info") or "") or pincode_verified:
                        actual_pincode = pincode
                        pincode_verified = True
                        parsed_dict["actual_pincode"] = pincode
                    else:
                        pincode_verified = False
                        self.logger.error(
                            f"Pincode mismatch: requested={pincode}, actual={actual_pincode}",
                            category="PINCODE"
                        )
                        if settings.STRICT_PINCODE_VERIFY:
                            raise ScraperExecutionError(
                                code="PINCODE_VERIFICATION_FAILED",
                                message=f"Requested pincode {pincode} was not applied by Amazon. Amazon delivery pincode is {actual_pincode}.",
                                status="failed",
                                requested_pincode=pincode,
                                actual_pincode=actual_pincode,
                                http_status_code=422,
                            )
            else:
                pincode_verified = True
                actual_pincode = pincode
                parsed_dict["actual_pincode"] = pincode

            # Construct ProductData Pydantic model
            product_data = ProductData(**parsed_dict)

            # Count non-null extracted fields
            fields_count = sum(1 for v in parsed_dict.values() if v is not None and v != [] and v != {})

            # Stage 10: COMPLETED
            self.logger.stage(10, "COMPLETED")
            duration = timer.stop()
            self.logger.info("Product scrape completed", category="REQUEST")
            self.logger.info(f"Processing time: {duration:.2f} seconds", category="REQUEST")

            # Persist debug files if requested
            if save_debug:
                self._save_debug_files(req_id, debug_data, parsed_dict)

            # Print terminal completion banner
            print_completion_banner(
                logger=self.logger,
                request_id=req_id,
                request_type=req_type,
                asin=asin,
                requested_pincode=pincode,
                actual_pincode=actual_pincode,
                pincode_verified=pincode_verified,
                amazon_fresh=amazon_fresh_detected,
                product_status="SUCCESS",
                fields_extracted=fields_count,
                processing_time=duration,
            )

            return ScrapeProductResponse(
                request_id=req_id,
                status="success",
                request_type=req_type,
                source="amazon.in",
                amazon_fresh=amazon_fresh_detected,
                pincode=PincodeInfo(
                    requested=pincode,
                    actual=actual_pincode,
                    verified=pincode_verified,
                    pincode_status="verified" if pincode_verified else "failed",
                ),
                product=product_data,
                metadata=ScrapeMetadata(
                    scraped_at=start_time_iso,
                    processing_time=round(duration, 2),
                    scraper_version=settings.SCRAPER_VERSION,
                ),
            )

        except ScraperExecutionError as see:
            duration = timer.stop()
            print_completion_banner(
                logger=self.logger,
                request_id=req_id,
                request_type=request.request_type,
                asin=asin if "asin" in locals() else None,
                requested_pincode=request.pincode,
                actual_pincode=see.actual_pincode or actual_pincode,
                pincode_verified=False,
                amazon_fresh=amazon_fresh_detected,
                product_status="FAILED",
                fields_extracted=0,
                processing_time=duration,
            )
            raise see

    def _save_debug_files(self, request_id: str, debug_data: Dict[str, Any], parsed_dict: Dict[str, Any]):
        try:
            req_dir = os.path.join(settings.DEBUG_DIR, request_id)
            os.makedirs(req_dir, exist_ok=True)

            if debug_data.get("homepage_html"):
                with open(os.path.join(req_dir, "homepage.html"), "w", encoding="utf-8") as f:
                    f.write(debug_data["homepage_html"])

            if debug_data.get("pincode_response_html"):
                with open(os.path.join(req_dir, "pincode_response.html"), "w", encoding="utf-8") as f:
                    f.write(debug_data["pincode_response_html"])

            if debug_data.get("product_html"):
                with open(os.path.join(req_dir, "product.html"), "w", encoding="utf-8") as f:
                    f.write(debug_data["product_html"])

            meta = {
                "request_id": request_id,
                "saved_at": datetime.now().isoformat(),
                "extracted_fields_count": len(parsed_dict),
            }
            with open(os.path.join(req_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

            self.logger.info(f"Debug files saved to {req_dir}", category="DEBUG")
        except Exception as de:
            self.logger.warning(f"Failed to save debug files: {str(de)}", category="DEBUG")
