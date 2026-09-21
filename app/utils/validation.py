import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from app.utils.asin import extract_asin

INDIAN_PINCODE_REGEX = re.compile(r"^[1-9][0-9]{5}$")
SUPPORTED_REQUEST_TYPES = {"product", "search", "category"}


class ValidationError(Exception):
    def __init__(self, message: str, field: str, code: str = "VALIDATION_ERROR"):
        self.message = message
        self.field = field
        self.code = code
        super().__init__(message)


def validate_pincode(pincode: str) -> str:
    """
    Validates an Indian postal PIN code.
    Must be exactly 6 digits, not starting with 0.
    Rejects '60002', 'ABCDEF', '6000021', None, etc.
    """
    if not pincode or not isinstance(pincode, str):
        raise ValidationError("Pincode must be provided as a string.", field="pincode", code="INVALID_PINCODE")

    cleaned = pincode.strip()
    if not INDIAN_PINCODE_REGEX.match(cleaned):
        raise ValidationError(
            f"Invalid Indian pincode '{pincode}'. Must be a 6-digit number starting with 1-9.",
            field="pincode",
            code="INVALID_PINCODE"
        )
    return cleaned


def validate_amazon_url(url: str) -> Tuple[str, str]:
    """
    Validates that the product URL targets amazon.in and contains a valid ASIN.
    Returns (cleaned_url, extracted_asin).
    """
    if not url or not isinstance(url, str):
        raise ValidationError("URL must be provided as a non-empty string.", field="url", code="INVALID_URL")

    cleaned_url = url.strip()

    try:
        parsed = urlparse(cleaned_url)
    except Exception as e:
        raise ValidationError(f"Malformed URL: {str(e)}", field="url", code="INVALID_URL")

    if not parsed.scheme or parsed.scheme.lower() not in ("http", "https"):
        raise ValidationError("URL must start with http:// or https://", field="url", code="INVALID_URL")

    netloc = parsed.netloc.lower()
    valid_domains = ("amazon.in", "www.amazon.in", "m.amazon.in")
    if not any(netloc == domain or netloc.endswith("." + domain) for domain in valid_domains):
        raise ValidationError(
            f"Target domain must be 'amazon.in'. Received '{netloc}'.",
            field="url",
            code="NOT_AMAZON"
        )

    asin = extract_asin(cleaned_url)
    if not asin:
        raise ValidationError(
            "Could not extract a valid 10-character Amazon ASIN from the provided URL.",
            field="url",
            code="INVALID_URL"
        )

    return cleaned_url, asin


def validate_category_url(url: str) -> str:
    """
    Validates that the category URL targets amazon.in (ASIN not required).
    """
    if not url or not isinstance(url, str):
        raise ValidationError("Category URL must be provided as a non-empty string.", field="url", code="INVALID_URL")

    cleaned_url = url.strip()

    try:
        parsed = urlparse(cleaned_url)
    except Exception as e:
        raise ValidationError(f"Malformed URL: {str(e)}", field="url", code="INVALID_URL")

    if not parsed.scheme or parsed.scheme.lower() not in ("http", "https"):
        raise ValidationError("URL must start with http:// or https://", field="url", code="INVALID_URL")

    netloc = parsed.netloc.lower()
    valid_domains = ("amazon.in", "www.amazon.in", "m.amazon.in")
    if not any(netloc == domain or netloc.endswith("." + domain) for domain in valid_domains):
        raise ValidationError(
            f"Target domain must be 'amazon.in'. Received '{netloc}'.",
            field="url",
            code="NOT_AMAZON"
        )

    return cleaned_url


def validate_request_type(request_type: str) -> str:
    """
    Validates the request_type.
    """
    if not request_type or not isinstance(request_type, str):
        raise ValidationError("request_type is required.", field="request_type", code="INVALID_REQUEST_TYPE")

    normalized = request_type.strip().lower()
    if normalized not in SUPPORTED_REQUEST_TYPES:
        raise ValidationError(
            f"Unsupported request_type '{request_type}'. Expected 'product', 'search', or 'category'.",
            field="request_type",
            code="INVALID_REQUEST_TYPE"
        )

    return normalized
