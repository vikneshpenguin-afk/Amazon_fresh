import re
from typing import Dict, Optional
from bs4 import BeautifulSoup


def extract_seller_info(html: str) -> Dict[str, Optional[str]]:
    """
    Parses seller and ships_from information from Amazon product HTML.
    """
    result = {
        "seller": None,
        "ships_from": None,
    }

    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")

    # 1. Check tabular buybox layout (modern layout)
    tabular = soup.select("#tabular-buybox tr, .tabular-buybox-container tr")
    for row in tabular:
        text = row.get_text(separator=" ", strip=True)
        if "Ships from" in text:
            # Get second column
            cols = row.find_all("td")
            if len(cols) >= 2:
                result["ships_from"] = cols[1].get_text(strip=True)
            else:
                val = re.sub(r"(?i)ships\s+from", "", text).strip()
                result["ships_from"] = val
        elif "Sold by" in text:
            cols = row.find_all("td")
            if len(cols) >= 2:
                result["seller"] = cols[1].get_text(strip=True)
            else:
                val = re.sub(r"(?i)sold\s+by", "", text).strip()
                result["seller"] = val

    # 2. Check fresh-merchant-info or merchant-info
    if not result["seller"] or not result["ships_from"]:
        merchant_elem = soup.find(id="fresh-merchant-info") or soup.find(id="merchant-info")
        if merchant_elem:
            m_text = merchant_elem.get_text(separator=" ", strip=True)
            if not result["seller"]:
                seller_match = re.search(r"(?i)sold\s+by\s+([^.\n]+)", m_text)
                if seller_match:
                    result["seller"] = seller_match.group(1).strip()
            if not result["ships_from"]:
                ships_match = re.search(r"(?i)(?:fulfilled|ships\s+from)\s+by\s+([^.\n]+)", m_text)
                if ships_match:
                    result["ships_from"] = ships_match.group(1).strip()

    # 3. Check sellerProfileTriggerId
    if not result["seller"]:
        seller_link = soup.find(id="sellerProfileTriggerId")
        if seller_link:
            result["seller"] = seller_link.get_text(strip=True)

    # 4. Check freshShipsFromSoldBy_feature_div
    if not result["seller"]:
        fresh_seller = soup.find(id="freshShipsFromSoldBy_feature_div")
        if fresh_seller:
            txt = fresh_seller.get_text(separator=" ", strip=True)
            if txt:
                s_m = re.search(r"(?i)sold\s+by\s+([^.\n]+)", txt)
                if s_m:
                    result["seller"] = s_m.group(1).strip()

    return result
