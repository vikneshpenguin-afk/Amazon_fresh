import re
from typing import Dict, Optional, Tuple
from bs4 import BeautifulSoup

from app.scraper.pincode import extract_pincode_and_location_from_text, extract_location_from_html

DATE_PATTERNS = [
    re.compile(r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.IGNORECASE),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b", re.IGNORECASE),
]

TIME_SLOT_PATTERNS = [
    re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s*(?:hours|hrs|mins|minutes)\b", re.IGNORECASE),
    re.compile(r"\b(?:morning|afternoon|evening)\b", re.IGNORECASE),
]


def extract_delivery_details(html: str, requested_pincode: str) -> Dict[str, Optional[any]]:
    """
    Parses delivery information, location, actual delivery pincode, date, and slot from product HTML.
    """
    result = {
        "requested_pincode": requested_pincode,
        "actual_pincode": None,
        "delivery_location": None,
        "delivery_info": None,
        "delivery_date": None,
        "delivery_time": None,
    }

    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract actual location and pincode
    actual_pin, loc_name = extract_location_from_html(html, expected_pincode=requested_pincode)
    result["actual_pincode"] = actual_pin or requested_pincode
    result["delivery_location"] = loc_name or f"Delivery {requested_pincode}"

    # 2. Extract delivery info text
    delivery_info_selectors = [
        "#mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE",
        "#delivery-message",
        "#del-punch-in",
        "#contextualIngressPtLabel_deliveryShortLine",
        ".fresh-oor-glow-ingress",
        "#fresh-delivery-promise",
        "#freshDeliveryPromise_feature_div",
        "#FREE_DELIVERY_feature_div",
    ]

    delivery_texts = []
    for sel in delivery_info_selectors:
        elem = soup.select_one(sel)
        if elem:
            txt = elem.get_text(separator=" ", strip=True)
            if txt and len(txt) > 3 and txt not in delivery_texts:
                delivery_texts.append(txt)

    if delivery_texts:
        result["delivery_info"] = " | ".join(delivery_texts)
    elif loc_name:
        result["delivery_info"] = f"Delivering to {loc_name}"

    # 3. Extract delivery date
    combined_text = result["delivery_info"] or ""
    for pat in DATE_PATTERNS:
        match = pat.search(combined_text)
        if match:
            # Grab full date phrase
            date_match = re.search(
                r"(?i)\b(?:tomorrow|today|(?:by\s+)?\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*)\b",
                combined_text
            )
            result["delivery_date"] = date_match.group(0).strip() if date_match else match.group(0).strip()
            break

    # 4. Extract delivery time slot
    for pat in TIME_SLOT_PATTERNS:
        match = pat.search(combined_text)
        if match:
            result["delivery_time"] = match.group(0).strip()
            break

    return result
