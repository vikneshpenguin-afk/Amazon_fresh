import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core settings
    AMAZON_BASE_URL: str = "https://www.amazon.in"
    REQUEST_TIMEOUT: int = 35
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_FACTOR: float = 1.5

    # Application settings
    APP_NAME: str = "amazon-fresh-scraper"
    SCRAPER_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Logging and Debugging
    LOG_LEVEL: str = "INFO"
    DEBUG_MODE: bool = False
    SAVE_HTML: bool = False
    DEBUG_DIR: str = "debug"
    LOGS_DIR: str = "logs"

    # Network / Proxy
    PROXY_URL: Optional[str] = "http://scraperapi.country_code=ind:c5c0632e2085b50a6858e2aecad14cc2@proxy-server.scraperapi.com:8001"
    VERIFY_SSL: bool = False
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )

    # Scraper behavior
    STRICT_FRESH_CHECK: bool = True
    STRICT_PINCODE_VERIFY: bool = True


settings = Settings()
