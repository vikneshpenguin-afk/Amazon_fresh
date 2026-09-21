import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup


class FreshDetectionResult:
    def __init__(
        self,
        is_fresh: bool,
        confidence: float,
        matched_signals: List[str],
        brand_id: Optional[str] = None,
        store_type: Optional[str] = None,
        details: Optional[Dict[str, any]] = None
    ):
        self.is_fresh = is_fresh
        self.confidence = confidence
        self.matched_signals = matched_signals
        self.brand_id = brand_id
        self.store_type = store_type
        self.details = details or {}

    def to_dict(self) -> Dict[str, any]:
        return {
            "is_fresh": self.is_fresh,
            "confidence": round(self.confidence, 2),
            "matched_signals": self.matched_signals,
            "brand_id": self.brand_id,
            "store_type": self.store_type,
            "details": self.details
        }


def detect_amazon_fresh(url: str, html: Optional[str] = None) -> FreshDetectionResult:
    """
    Detects whether the URL and/or HTML corresponds to an Amazon Fresh / Quick-Commerce product.
    Uses multiple weighted signals from URL structure, HTML elements, and inline scripts.
    """
    signals: List[str] = []
    brand_id: Optional[str] = None
    store_type: Optional[str] = None
    score = 0.0

    # 1. Inspect URL parameters and path
    if url:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        # Check fpw=alm (Amazon Local Market / Fresh indicator)
        if params.get("fpw") and "alm" in params["fpw"]:
            signals.append("URL: fpw=alm parameter")
            score += 0.40

        # Check almBrandId
        if params.get("almBrandId"):
            brand_id = params["almBrandId"][0]
            signals.append(f"URL: almBrandId={brand_id}")
            score += 0.40
            if "ctnow" in brand_id.lower() or "nowstore" in brand_id.lower() or "fresh" in brand_id.lower():
                store_type = "Amazon Fresh"

        # Check /nowstore/ path
        if "/nowstore" in parsed.path.lower():
            signals.append("URL: /nowstore in path")
            score += 0.45
            store_type = "Amazon Fresh (NowStore)"

    # 2. Inspect HTML if provided
    if html:
        soup = BeautifulSoup(html, "html.parser")

        # Check Fresh specific DIV elements / features
        fresh_elements = [
            ("fresh-oor-glow-ingress", 0.35, "HTML: fresh-oor-glow-ingress present"),
            ("freshAddToGroceryList_feature_div", 0.30, "HTML: freshAddToGroceryList feature present"),
            ("freshShipsFromSoldBy_feature_div", 0.30, "HTML: freshShipsFromSoldBy feature present"),
            ("fresh-merchant-info", 0.25, "HTML: fresh-merchant-info element present"),
            ("freshCenterColDivider", 0.20, "HTML: freshCenterColDivider present"),
            ("alm-badge-desktop", 0.35, "HTML: alm-badge-desktop present"),
            ("alm-brand-title", 0.35, "HTML: alm-brand-title present"),
        ]

        for ident, weight, label in fresh_elements:
            elem = soup.find(id=ident) or soup.find(class_=ident)
            if elem:
                signals.append(label)
                score += weight

        # Check for store brand badges
        alm_badges = soup.select(".alm-badge, .fresh-badge, [id*='alm-brand'], [class*='fresh-badge']")
        if alm_badges:
            signals.append("HTML: Fresh/ALM branding badge found")
            score += 0.25

        # Check text signals in key sections
        lower_html = html.lower()
        if "amazon fresh" in lower_html:
            # Check if it's not merely in the footer/header
            nav_or_body_fresh = soup.find(string=re.compile(r"amazon fresh", re.IGNORECASE))
            if nav_or_body_fresh:
                signals.append("HTML: 'Amazon Fresh' text in page content")
                score += 0.20

        # Check storeContext in inline JS
        if "'storecontext': 'nowstore'" in lower_html or '"storecontext":"nowstore"' in lower_html or "storecontext=nowstore" in lower_html:
            signals.append("JS: storeContext=nowstore")
            score += 0.35
            store_type = store_type or "Amazon Fresh"

        if not brand_id:
            m = re.search(r'almBrandId["\']?\s*[:=]\s*["\']([^"\']+)["\']', html)
            if m:
                brand_id = m.group(1)
                signals.append(f"JS: almBrandId={brand_id}")
                score += 0.30

    # Determine verdict
    # A single strong signal or combination of signals validates Fresh
    confidence = min(score, 1.0)
    is_fresh = confidence >= 0.35 or len(signals) >= 1 and any("alm" in s.lower() or "fresh" in s.lower() or "nowstore" in s.lower() for s in signals)

    return FreshDetectionResult(
        is_fresh=is_fresh,
        confidence=confidence,
        matched_signals=signals,
        brand_id=brand_id,
        store_type=store_type or ("Amazon Fresh" if is_fresh else None),
        details={"signals_count": len(signals)}
    )
