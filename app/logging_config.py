import logging
import os
import sys
from datetime import datetime
from typing import Optional


class CustomFormatter(logging.Formatter):
    """
    Formats logs as:
    YYYY-MM-DD HH:MM:SS | LEVEL    | CATEGORY | Message
    """
    def format(self, record: logging.LogRecord) -> str:
        # Default category if not supplied
        category = getattr(record, "category", "GENERAL")
        # Format timestamp
        record_time = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        record.levelname_aligned = f"{record.levelname:<8}"
        record.category_aligned = f"{category:<8}"
        record.time_formatted = record_time

        formatted_msg = super().format(record)
        return f"{record.time_formatted} | {record.levelname_aligned} | {record.category_aligned} | {record.getMessage()}"


class ScraperLoggerAdapter(logging.LoggerAdapter):
    """
    Adapter allowing logger.info("message", category="CATEGORY")
    """
    def process(self, msg, kwargs):
        category = kwargs.pop("category", self.extra.get("category", "GENERAL") if self.extra else "GENERAL")
        extra = kwargs.setdefault("extra", {})
        extra["category"] = category
        return msg, kwargs

    def stage(self, stage_number: int, stage_name: str):
        self.info(f"[{stage_number:02d}] {stage_name}", category="STAGE")


def setup_logger(name: str = "amazon_fresh_scraper", log_level: str = "INFO", logs_dir: Optional[str] = None) -> ScraperLoggerAdapter:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.propagate = False

    # Prevent duplicate handlers
    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        console_handler.setFormatter(CustomFormatter())
        logger.addHandler(console_handler)

        if logs_dir:
            os.makedirs(logs_dir, exist_ok=True)
            log_file = os.path.join(logs_dir, "scraper.log")
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
            file_handler.setFormatter(CustomFormatter())
            logger.addHandler(file_handler)

    return ScraperLoggerAdapter(logger, {"category": "GENERAL"})


def print_request_banner(
    logger: ScraperLoggerAdapter,
    request_id: str,
    request_type: str,
    url: str,
    asin: Optional[str],
    pincode: str,
    engine: str = "requests/session",
    started_at: Optional[str] = None,
):
    if not started_at:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banner = f"""
============================================================
 AMAZON FRESH PRODUCT SCRAPER
============================================================
Request ID       : {request_id}
Request Type     : {request_type.upper()}
URL              : {url}
ASIN             : {asin or 'N/A'}
Pincode          : {pincode}
Engine           : {engine}
Started          : {started_at}
============================================================
""".strip()
    for line in banner.split("\n"):
        print(line, flush=True)


def print_completion_banner(
    logger: ScraperLoggerAdapter,
    request_id: str,
    request_type: str,
    asin: Optional[str],
    requested_pincode: str,
    actual_pincode: Optional[str],
    pincode_verified: bool,
    amazon_fresh: bool,
    product_status: str,
    fields_extracted: int,
    processing_time: float,
):
    banner = f"""
============================================================
 SCRAPE COMPLETED
============================================================
Request ID          : {request_id}
Request Type        : {request_type.upper()}
ASIN                : {asin or 'N/A'}
Requested Pincode   : {requested_pincode}
Actual Pincode      : {actual_pincode or 'N/A'}
Pincode Verified    : {'YES' if pincode_verified else 'NO'}
Amazon Fresh        : {'YES' if amazon_fresh else 'NO'}
Product Status      : {product_status.upper()}
Fields Extracted    : {fields_extracted}
Processing Time     : {processing_time:.2f} sec
============================================================
""".strip()
    for line in banner.split("\n"):
        print(line, flush=True)
