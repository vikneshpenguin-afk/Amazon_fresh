import re
from typing import Dict, Optional
from bs4 import BeautifulSoup

PRICE_REGEX = re.compile(r"₹\s*([0-9,]+(?:\.[0-9]{1,2})?)")
PERCENT_REGEX = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")


def clean_price_to_float(price_str: Optional[str]) -> Optional[float]:
    if not price_str:
        return None
    # Strip currency symbol, commas, and whitespace
    cleaned = re.sub(r"[^\d.]", "", price_str)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def format_price_display(amount: Optional[float], original_str: Optional[str] = None) -> Optional[str]:
    if amount is None:
        return None
    if original_str and "₹" in original_str:
        return original_str.strip()
    return f"₹{amount:,.2f}"


def extract_pricing(html: str) -> Dict[str, Optional[any]]:
    """
    Parses product pricing details from Amazon HTML.
    Returns:
        price: float
        price_display: str
        mrp: float
        mrp_display: str
        discount: float
        discount_percent: float
        unit_price: str
    """
    result = {
        "price": None,
        "price_display": None,
        "mrp": None,
        "mrp_display": None,
        "discount": None,
        "discount_percent": None,
        "unit_price": None,
    }

    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract Current Price
    price_selectors = [
        ".priceToPay span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-price:not(.a-text-price) span.a-offscreen",
        "#corePrice_feature_div span.a-price:not(.a-text-price) span.a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
        "span.apexPriceToPay span.a-offscreen",
        "#price_inside_buybox",
        "#fresh-price",
    ]

    for sel in price_selectors:
        elem = soup.select_one(sel)
        if elem and elem.get_text(strip=True):
            raw_text = elem.get_text(strip=True)
            amt = clean_price_to_float(raw_text)
            if amt is not None and amt > 0:
                result["price"] = amt
                result["price_display"] = format_price_display(amt, raw_text)
                break

    # Alternate: whole + fraction
    if result["price"] is None:
        whole = soup.select_one(".priceToPay span.a-price-whole, #corePriceDisplay_desktop_feature_div span.a-price-whole")
        fraction = soup.select_one(".priceToPay span.a-price-fraction, #corePriceDisplay_desktop_feature_div span.a-price-fraction")
        if whole:
            w_str = whole.get_text(strip=True).replace(",", "").rstrip(".")
            f_str = fraction.get_text(strip=True) if fraction else "00"
            amt = clean_price_to_float(f"{w_str}.{f_str}")
            if amt is not None and amt > 0:
                result["price"] = amt
                result["price_display"] = f"₹{amt:,.2f}"

    # 2. Extract MRP / List Price
    mrp_selectors = [
        ".basisPrice span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-price.a-text-price span.a-offscreen",
        "#corePrice_feature_div .a-price.a-text-price span.a-offscreen",
        "span[data-a-strike='true']",
        "#priceblock_strikePrice",
        ".priceBlockStrikePriceString",
    ]

    for sel in mrp_selectors:
        elem = soup.select_one(sel)
        if elem and elem.get_text(strip=True):
            raw_text = elem.get_text(strip=True)
            amt = clean_price_to_float(raw_text)
            if amt is not None and amt > 0:
                result["mrp"] = amt
                result["mrp_display"] = format_price_display(amt, raw_text)
                break

    # 3. Calculate or extract Discount and Discount Percentage
    savings_elem = soup.select_one(
        "span.savingsPercentage, #corePriceDisplay_desktop_feature_div .savingPriceOverride"
    )
    if savings_elem:
        pct_match = PERCENT_REGEX.search(savings_elem.get_text(strip=True))
        if pct_match:
            try:
                result["discount_percent"] = float(pct_match.group(1))
            except ValueError:
                pass

    if result["price"] is not None and result["mrp"] is not None:
        if result["mrp"] > result["price"]:
            result["discount"] = round(result["mrp"] - result["price"], 2)
            if result["discount_percent"] is None:
                result["discount_percent"] = round(((result["mrp"] - result["price"]) / result["mrp"]) * 100, 2)

    # 4. Extract Unit Price (e.g., ₹149.00 / 1L)
    unit_selectors = [
        "span.pricePerUnit",
        "span.unit-price",
        "#corePriceDisplay_desktop_feature_div .a-size-small",
        "#corePrice_feature_div .a-size-small",
    ]
    for sel in unit_selectors:
        elem = soup.select_one(sel)
        if elem:
            txt = elem.get_text(strip=True)
            if "/" in txt and ("₹" in txt or "Rs" in txt):
                result["unit_price"] = txt
                break

    return result
