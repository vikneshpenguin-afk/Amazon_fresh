import re
import time
from typing import Dict, Optional
import urllib3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import settings
from app.scraper.anti_block import get_default_headers, get_random_user_agent


def normalize_proxy_url(proxy_url: Optional[str]) -> Optional[str]:
    """
    Normalizes proxy URLs:
    - ScraperAPI requires 2-letter ISO 3166-1 alpha-2 country codes (e.g. 'in' for India, not 'ind').
      Automatically corrects 'country_code=ind' to 'country_code=in' so requests route properly without timeouts.
    """
    if not proxy_url:
        return proxy_url
    return re.sub(r"(country_code=)ind\b", r"\g<1>in", proxy_url, flags=re.IGNORECASE)


class AmazonSessionContext:
    """
    Manages a single Amazon session with proxy and cookie consistency.
    Guarantees that all operations (warmup, pincode setting, verification, product fetching)
    use the exact same network identity and HTTP session.
    """

    def __init__(
        self,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        verify_ssl: Optional[bool] = None,
    ):
        raw_proxy = proxy or settings.PROXY_URL
        self.proxy = normalize_proxy_url(raw_proxy)
        self.user_agent = user_agent or settings.USER_AGENT or get_random_user_agent()
        self.timeout = timeout or settings.REQUEST_TIMEOUT
        self.max_retries = max_retries or settings.MAX_RETRIES

        # If proxy is ScraperAPI or explicitly disabled, disable SSL verification
        if verify_ssl is not None:
            self.verify_ssl = verify_ssl
        elif self.proxy and "scraperapi.com" in self.proxy:
            self.verify_ssl = False
        else:
            self.verify_ssl = getattr(settings, "VERIFY_SSL", True)

        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.session = requests.Session()
        self._configure_session()

        self.created_at = time.time()
        self.last_pincode: Optional[str] = None
        self.pincode_verified: bool = False
        self.csrf_token: Optional[str] = None

    def _configure_session(self):
        """Sets up connection pooling, retries, headers, and proxy."""
        # Realistic default headers
        headers = get_default_headers(self.user_agent)
        self.session.headers.update(headers)

        # Connection pooling and transport retry
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=settings.RETRY_BACKOFF_FACTOR,
            status_forcelist=[500, 502, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Apply SSL verification policy
        self.session.verify = self.verify_ssl

        # Apply proxy consistently
        if self.proxy:
            self.session.proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }

    def warmup(self, base_url: str = "https://www.amazon.in") -> requests.Response:
        """
        Warms up the session by requesting the Fresh browse node or gateway page to obtain
        initial session cookies (session-id, sst-acbin, i18n-prefs) and CSRF token.
        """
        domain = ".amazon.in" if "amazon.in" in base_url else ".amazon.com"
        self.session.cookies.set("i18n-prefs", "INR", domain=domain)
        self.session.cookies.set("lc-acbin", "en_IN", domain=domain)

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }

        # Warm up on Fresh search/browse node (provides full session-id, sst-acbin, and anti-csrftoken quickly)
        fresh_warmup_url = f"{base_url.rstrip('/')}/gp/search?ie=UTF8&keywords=fresh&almBrandId=ctnow&fpw=alm"
        try:
            resp = self.session.get(fresh_warmup_url, headers=headers, timeout=min(self.timeout, 20))
            if resp.status_code == 200:
                self._extract_csrf(resp.text)
                return resp
        except Exception:
            pass

        # Secondary warmup on browse node
        secondary_url = f"{base_url.rstrip('/')}/gp/browse.html?node=4859554031&almBrandId=ctnow&fpw=alm"
        try:
            resp = self.session.get(secondary_url, headers=headers, timeout=min(self.timeout, 20))
            if resp.status_code == 200:
                self._extract_csrf(resp.text)
                return resp
        except Exception:
            pass

        # Fallback to root gateway
        resp = self.session.get(base_url, headers=headers, timeout=self.timeout)
        self._extract_csrf(resp.text)
        return resp

    def _extract_csrf(self, html_text: str):
        if not html_text:
            return
        m = re.search(r'anti-csrftoken-a2z(?:&quot;|\")\s*:\s*(?:&quot;|\")([^\"&]+)', html_text)
        if m:
            self.csrf_token = m.group(1)
            return
        m2 = re.search(r'name=["\']anti-csrftoken-a2z["\']\s+value=["\']([^"\']+)["\']', html_text)
        if m2:
            self.csrf_token = m2.group(1)
            return
        m3 = re.search(r'CSRF_TOKEN\s*:\s*["\']([^"\']+)["\']', html_text)
        if m3:
            self.csrf_token = m3.group(1)

    def get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self.session.post(url, **kwargs)

    @property
    def cookies(self) -> Dict[str, str]:
        return self.session.cookies.get_dict()

    def close(self):
        """Closes the underlying requests session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
