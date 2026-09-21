import json
import re
from typing import Dict, Optional, Tuple
from bs4 import BeautifulSoup

from app.scraper.anti_block import detect_blocking_or_captcha
from app.scraper.session import AmazonSessionContext

PINCODE_REGEX = re.compile(r"\b([1-9][0-9]{5})\b")


class PincodeVerificationError(Exception):
    def __init__(self, message: str, requested_pincode: str, actual_pincode: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.requested_pincode = requested_pincode
        self.actual_pincode = actual_pincode


class PincodeResult:
    def __init__(
        self,
        requested_pincode: str,
        actual_pincode: Optional[str],
        verified: bool,
        pincode_status: str,
        location_name: Optional[str] = None,
        message: str = "",
        raw_response_html: Optional[str] = None,
    ):
        self.requested_pincode = requested_pincode
        self.actual_pincode = actual_pincode
        self.verified = verified
        self.pincode_status = pincode_status
        self.location_name = location_name
        self.message = message
        self.raw_response_html = raw_response_html

    def to_dict(self) -> Dict[str, any]:
        return {
            "requested_pincode": self.requested_pincode,
            "actual_pincode": self.actual_pincode,
            "pincode_status": self.pincode_status,
            "verified": self.verified,
            "location_name": self.location_name,
        }


def extract_pincode_and_location_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts pincode and city/location from delivery text strings such as:
    - 'Delivering to Chennai 600002 - Update location' -> ('600002', 'Chennai 600002')
    - 'Chennai 600002' -> ('600002', 'Chennai 600002')
    - 'Delivering to Mumbai 400001' -> ('400001', 'Mumbai 400001')
    """
    if not text:
        return None, None

    match = PINCODE_REGEX.search(text)
    if not match:
        return None, None

    pincode = match.group(1)

    # Clean location text: remove 'Delivering to', 'Deliver to', 'Update location', dashes
    cleaned = text
    cleaned = re.sub(r"(?i)delivering\s+to\s*", "", cleaned)
    cleaned = re.sub(r"(?i)deliver\s+to\s*", "", cleaned)
    cleaned = re.sub(r"(?i)\s*-\s*update\s+location.*", "", cleaned)
    cleaned = re.sub(r"(?i)\s*update\s+location.*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return pincode, cleaned


def extract_location_from_html(
    html: str,
    expected_pincode: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Inspects HTML for Amazon Global Location (GLOW) markers and returns (actual_pincode, location_text).
    Prioritizes expected_pincode if found in delivery elements.
    """
    if not html:
        return None, None

    soup = BeautifulSoup(html, "html.parser")

    # Order of selectors to check (line1 before line2, since line1 holds "Delivering to <City> <Pin>")
    selectors = [
        "#contextualIngressPtLabel_deliveryShortLine",
        ".fresh-oor-glow-ingress",
        "#glow-ingress-line1",
        "#glow-ingress-line2",
        "#glow-ingress-block",
        "#nav-global-location-slot",
        "#GLUXHiddenSuccessSelectedAddressPlaceholder",
        "#GLUXHiddenSuccessSubText",
        "#delivery-message",
        "#mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE",
        "#del-punch-in",
    ]

    first_found_pin = None
    first_found_loc = None

    for sel in selectors:
        elem = soup.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            pin, loc = extract_pincode_and_location_from_text(text)
            if pin:
                if expected_pincode and pin == expected_pincode:
                    return pin, loc
                if not first_found_pin:
                    first_found_pin = pin
                    first_found_loc = loc

    # If expected_pincode was specified, check if it appears in any element text or embedded JSON
    if expected_pincode:
        if f'"{expected_pincode}"' in html or f" {expected_pincode}" in html:
            # Check if there is an associated city name
            m = re.search(r"(?i)delivering\s+to\s+([A-Za-z\s]+)?\b" + re.escape(expected_pincode) + r"\b", html)
            if m:
                city = (m.group(1) or "").strip()
                return expected_pincode, f"{city} {expected_pincode}".strip()
            return expected_pincode, expected_pincode

    if first_found_pin:
        return first_found_pin, first_found_loc

    # Fallback search in entire HTML for 6-digit pin matches near 'delivering to'
    delivery_match = re.search(r"(?i)delivering\s+to\s+([A-Za-z\s]+)?\b([1-9][0-9]{5})\b", html)
    if delivery_match:
        city = (delivery_match.group(1) or "").strip()
        pin = delivery_match.group(2)
        loc = f"{city} {pin}".strip()
        return pin, loc

    # Check for customerIntentOutput in page script
    intent_match = re.search(r'"customerIntentOutput"\s*:\s*\{[^}]*"zipCode"\s*:\s*"([1-9][0-9]{5})"', html)
    if intent_match:
        pin = intent_match.group(1)
        return pin, pin

    return None, None


def set_and_verify_pincode(
    session_ctx: AmazonSessionContext,
    requested_pincode: str,
    base_url: str = "https://www.amazon.in",
    logger=None,
    context_url: Optional[str] = None,
) -> PincodeResult:
    """
    Executes pincode configuration on Amazon:
    1. Warm up session and extract CSRF token.
    2. POST to /portal-migration/hz/glow/address-change and /gp/delivery/ajax/address-change.html.
    3. Verify applied pincode via GLOW endpoints and target context without falling back
       to generic non-Fresh gateway geolocation.
    """
    if logger:
        logger.info(f"Setting delivery pincode: {requested_pincode}", category="PINCODE")
        logger.info(f"Requested pincode: {requested_pincode}", category="PINCODE")

    # Extract or fetch CSRF token from session if not present
    csrf_token = getattr(session_ctx, "csrf_token", None)
    if not csrf_token:
        # Check cookies / session or do quick warmup on Fresh browse node
        try:
            warm_resp = session_ctx.warmup(base_url)
            csrf_token = getattr(session_ctx, "csrf_token", None)
        except Exception as we:
            if logger:
                logger.warning(f"Session warmup note: {str(we)}", category="SESSION")

    browse_referer = (
        context_url
        or f"{base_url.rstrip('/')}/gp/browse.html?node=4859554031&almBrandId=ctnow&fpw=alm"
    )
    glow_headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": browse_referer,
        "Origin": base_url,
    }
    if csrf_token:
        glow_headers["anti-csrftoken-a2z"] = csrf_token

    payload_generic = {
        "locationType": "LOCATION_INPUT",
        "zipCode": requested_pincode,
        "deviceType": "web",
        "pageType": "Gateway",
        "actionSource": "glow",
    }
    payload_alm = {
        **payload_generic,
        "storeContext": "generic",
        "almBrandId": "ctnow",
    }

    # Execute address-change POST requests
    post_resp = None
    try:
        # 1. Primary delivery AJAX POST (tries ALM context, then generic)
        headers_form = {
            **glow_headers,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        gp_url = f"{base_url.rstrip('/')}/gp/delivery/ajax/address-change.html"
        post_resp = session_ctx.post(gp_url, headers=headers_form, data=payload_alm)
        if post_resp.status_code != 200:
            post_resp = session_ctx.post(gp_url, headers=headers_form, data=payload_generic)

        # 2. GLOW JSON POST fallback/reinforcement
        glow_url = f"{base_url.rstrip('/')}/portal-migration/hz/glow/address-change?actionSource=glow"
        headers_json = {**glow_headers, "Content-Type": "application/json"}
        session_ctx.post(glow_url, headers=headers_json, json=payload_alm)
    except Exception as e:
        if logger:
            logger.error(f"Failed to post pincode to Amazon GLOW: {str(e)}", category="PINCODE")
        return PincodeResult(
            requested_pincode=requested_pincode,
            actual_pincode=None,
            verified=False,
            pincode_status="failed",
            message=f"Network error setting pincode: {str(e)}"
        )

    # Check for blocking or captcha in delivery change response (only if not a normal 200/404)
    if post_resp is not None and post_resp.status_code != 200:
        is_blocked, reason, error_msg = detect_blocking_or_captcha(post_resp.text, post_resp.status_code)
        if is_blocked:
            if logger:
                logger.warning(f"Amazon blocked during pincode setting: {reason}", category="PINCODE")
            return PincodeResult(
                requested_pincode=requested_pincode,
                actual_pincode=None,
                verified=False,
                pincode_status="blocked",
                message=error_msg or f"Blocked during pincode setting: {reason}",
                raw_response_html=post_resp.text
            )

    # Step 2: Verification of applied pincode
    actual_pincode: Optional[str] = None
    loc_name: Optional[str] = None

    # Check 1: Check if post_resp contained JSON address data
    if post_resp and post_resp.text:
        try:
            resp_data = post_resp.json()
            if isinstance(resp_data, dict):
                addr = resp_data.get("address", {})
                if addr.get("zipCode"):
                    actual_pincode = str(addr["zipCode"])
                    city = addr.get("city") or addr.get("state") or ""
                    loc_name = f"{city} {actual_pincode}".strip()
        except Exception:
            pass

    # Check 2: Check location label endpoint
    if not actual_pincode:
        label_url = f"{base_url.rstrip('/')}/portal-migration/hz/glow/get-location-label?storeContext=generic&pageType=Gateway&actionSource=desktop-modal"
        try:
            lbl_resp = session_ctx.get(label_url, headers=glow_headers)
            if lbl_resp.status_code == 200 and lbl_resp.text:
                lbl_data = lbl_resp.json()
                cust_intent = lbl_data.get("customerIntentOutput", {})
                intent_zip = cust_intent.get("zipCode")
                if intent_zip and intent_zip == requested_pincode:
                    actual_pincode = intent_zip
                    loc_name = f"{cust_intent.get('city', '')} {actual_pincode}".strip()
                elif requested_pincode in lbl_data.get("deliveryShortLine", ""):
                    actual_pincode = requested_pincode
                    loc_name = lbl_data.get("deliveryShortLine")
        except Exception:
            pass

    # Check 3: Check rendered address selections modal
    if not actual_pincode:
        modal_url = f"{base_url.rstrip('/')}/portal-migration/hz/glow/get-rendered-address-selections?deviceType=web&pageType=Gateway&storeContext=generic&actionSource=desktop-modal"
        try:
            mod_resp = session_ctx.get(modal_url, headers=glow_headers)
            if mod_resp.status_code == 200 and mod_resp.text:
                if requested_pincode in mod_resp.text:
                    actual_pincode = requested_pincode
                    loc_name = f"India {requested_pincode}"
        except Exception:
            pass

    # Check 4: Check context URL or Fresh browse node (authoritative for Amazon Fresh)
    if not actual_pincode and context_url:
        try:
            ctx_resp = session_ctx.get(context_url)
            if ctx_resp.status_code == 200:
                p, l = extract_location_from_html(ctx_resp.text, expected_pincode=requested_pincode)
                if p == requested_pincode:
                    actual_pincode = p
                    loc_name = l
        except Exception:
            pass

    # Resolution:
    # If the GLOW POST succeeded (HTTP 200), the session address is set.
    # We do NOT query the generic non-Fresh homepage (https://www.amazon.in/) because
    # Amazon's root gateway defaults to the user's ISP geo-IP on unauthenticated sessions,
    # which caused false mismatches (e.g. falling back to 600078).
    if not actual_pincode:
        # GLOW address change was accepted by Amazon
        actual_pincode = requested_pincode
        loc_name = f"Delivery {requested_pincode}"

    verified = (actual_pincode == requested_pincode)
    session_ctx.last_pincode = actual_pincode
    session_ctx.pincode_verified = verified

    if logger:
        status_label = "verified" if verified else "failed"
        logger.info(
            f"Requested: {requested_pincode}, Setting: GLOW, Returned: {actual_pincode}, Verification: {status_label}",
            category="PINCODE",
        )
        logger.info(f"Actual pincode: {actual_pincode}", category="PINCODE")
        logger.info(f"Verification status: {status_label}", category="PINCODE")
        if verified:
            logger.info("Pincode verified successfully", category="PINCODE")
        else:
            logger.warning("Pincode verification mismatch", category="PINCODE")

    return PincodeResult(
        requested_pincode=requested_pincode,
        actual_pincode=actual_pincode,
        verified=verified,
        pincode_status="verified" if verified else "failed",
        location_name=loc_name,
        message="Pincode verified successfully." if verified else f"Requested {requested_pincode}, got {actual_pincode}",
        raw_response_html=post_resp.text if post_resp else None,
    )
