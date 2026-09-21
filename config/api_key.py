"""
Centralized API Key Configuration and Validation.
"""
import os

# Centralized API key configuration
DEFAULT_API_KEY = "fresh-api-key-2026-secure"
API_KEY = os.environ.get("SCRAPER_API_KEY") or os.environ.get("API_KEY") or DEFAULT_API_KEY


def get_api_key() -> str:
    """Returns the centralized configured API key."""
    return os.environ.get("SCRAPER_API_KEY") or os.environ.get("API_KEY") or API_KEY


def validate_api_key(api_key: str | None) -> tuple[bool, str]:
    """
    Validates provided api_key against configured API key.
    Returns (is_valid, error_detail).
    If missing/empty -> (False, "API key is required")
    If mismatch -> (False, "Invalid API key")
    If matches -> (True, "")
    """
    if api_key is None or not str(api_key).strip():
        return False, "API key is required"

    if str(api_key).strip() != get_api_key().strip():
        return False, "Invalid API key"

    return True, ""
