import re
from typing import Optional

ASIN_REGEX_PATTERNS = [
    re.compile(r"/dp/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"/gp/product/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"/product/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"/ASIN/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"/product-reviews/([A-Z0-9]{10})", re.IGNORECASE),
    re.compile(r"[?&]asin=([A-Z0-9]{10})", re.IGNORECASE),
]

STANDALONE_ASIN_REGEX = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)


def is_valid_asin(asin: str) -> bool:
    """Checks if a string is a valid 10-character alphanumeric ASIN."""
    if not asin or not isinstance(asin, str):
        return False
    return bool(STANDALONE_ASIN_REGEX.match(asin.strip()))


def extract_asin(url_or_text: str) -> Optional[str]:
    """
    Extracts 10-character Amazon ASIN from a product URL or text.
    Returns uppercase ASIN or None if not found.
    """
    if not url_or_text or not isinstance(url_or_text, str):
        return None

    cleaned = url_or_text.strip()

    # Check if string itself is an ASIN
    if is_valid_asin(cleaned):
        return cleaned.upper()

    for pattern in ASIN_REGEX_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            return match.group(1).upper()

    return None


def build_canonical_url(asin: str, base_url: str = "https://www.amazon.in") -> str:
    """Constructs the canonical Amazon product URL for a given ASIN."""
    return f"{base_url.rstrip('/')}/dp/{asin}"
