import random
from typing import Dict, Optional, Tuple
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
]

COMMON_ACCEPT_LANGUAGES = [
    "en-IN,en-GB;q=0.9,en;q=0.8",
    "en-IN,en;q=0.9",
    "en-GB,en;q=0.8,en-US;q=0.6",
]


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def get_default_headers(user_agent: Optional[str] = None) -> Dict[str, str]:
    ua = user_agent or get_random_user_agent()
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": random.choice(COMMON_ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }


def detect_blocking_or_captcha(html: str, status_code: int) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Analyzes HTTP status and HTML text to detect Amazon anti-bot measures.
    Returns: (is_blocked, reason, error_message)
    Possible reasons: 'captcha', 'bot_detection', 'service_unavailable', 'waf_challenge'
    """
    if not html:
        if status_code in (403, 429, 503):
            return True, "service_unavailable", f"Amazon returned HTTP {status_code}"
        return False, None, None

    lower_html = html.lower()

    # 1. Image CAPTCHA or explicit validateCaptcha form
    if "validatecaptcha" in lower_html or "type the characters you see in this image" in lower_html:
        if "captcha" in lower_html or "characters you see" in lower_html:
            return True, "captcha", "Amazon presented an image CAPTCHA challenge."
        return True, "captcha", "Amazon presented a CAPTCHA verification page."

    # 2. Automated access warning (ignore on standard 404 pages)
    if "to discuss automated access to amazon data" in lower_html:
        # Check if there is an interactive challenge or 503
        if "click the button below to continue shopping" in lower_html:
            return True, "captcha", "Amazon presented an automated browser check challenge."
        if status_code != 404:
            return True, "bot_detection", "Amazon blocked automated access."

    # 3. AWS WAF 202 Challenge
    if status_code == 202 and ("awswafcookiedomainlist" in lower_html or "gokuprops" in lower_html):
        return True, "waf_challenge", "Amazon AWS WAF challenge presented."

    # 4. Robot check titles
    if "<title>robot check</title>" in lower_html or "robot check" in lower_html:
        return True, "captcha", "Amazon robot check detected."

    # 5. Akamai Bot Manager / Interstitial Challenge
    if "bm-verify" in lower_html or "triggerinterstitialchallenge" in lower_html or "provider=interstitial" in lower_html:
        return True, "captcha", "Amazon presented an Akamai interstitial bot challenge (bm-verify)."

    # 6. Service unavailable bot error page
    if status_code == 503 or "503 - service unavailable error" in lower_html:
        return True, "service_unavailable", "Amazon returned 503 Service Unavailable bot block."

    # 7. HTTP 403 / 429
    if status_code in (403, 429):
        return True, "bot_detection", f"Amazon rejected request with HTTP {status_code}"

    return False, None, None


def check_and_solve_silent_challenge(session, html: str, base_url: str = "https://www.amazon.in") -> bool:
    """
    If Amazon presents the zero-interaction 'Click the button below to continue shopping' form,
    attempt to submit it to retrieve clearance cookies (x-amz-captcha-1, x-amz-captcha-2).
    Returns True if solved and cookies obtained, False otherwise.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form", action="/errors_page/validateCaptcha")
        if not form:
            return False

        # Only attempt if it does not have an image captcha input
        has_image = bool(soup.find("img", src=lambda s: s and "captcha" in s.lower()))
        if has_image:
            return False  # Real image captcha requiring human/OCR solve

        inputs = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            val = inp.get("value", "")
            if name:
                inputs[name] = val

        if "amzn" in inputs and "field-keywords" in inputs:
            action = form.get("action", "/errors_page/validateCaptcha")
            target_url = f"{base_url.rstrip('/')}{action}"
            res = session.get(target_url, params=inputs, timeout=10)
            if res.status_code in (200, 202, 302):
                return True
    except Exception:
        pass
    return False
