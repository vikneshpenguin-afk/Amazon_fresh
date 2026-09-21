import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from app.parser.delivery import extract_delivery_details
from app.parser.media import extract_media
from app.parser.pricing import extract_pricing
from app.parser.seller import extract_seller_info
from app.scraper.fresh_detection import detect_amazon_fresh


class ProductParser:
    """
    Comprehensive parser for Amazon Fresh product pages.
    Captures all available details across Identification, Product info, Pricing,
    Availability, Delivery, Seller, Services, Promotions, Ratings, Media, and Categories.
    """

    def __init__(self, requested_pincode: str):
        self.requested_pincode = requested_pincode

    def parse(self, html: str, url: str, asin: str, final_url: Optional[str] = None) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Identification
        product_id = asin

        # 2. Product Basic Info
        title = self._extract_title(soup)
        brand = self._extract_brand(soup)
        store = self._extract_store(soup, url)
        breadcrumbs = self._extract_breadcrumbs(soup)
        category = breadcrumbs[0] if breadcrumbs else None
        sub_category = breadcrumbs[1] if len(breadcrumbs) > 1 else None
        product_type = self._extract_product_type(soup, breadcrumbs)

        # 3. Pricing
        pricing = extract_pricing(html)

        # 4. Availability
        availability, in_stock, stock_status = self._extract_availability(soup)

        # 5. Delivery
        delivery = extract_delivery_details(html, self.requested_pincode)

        # 6. Seller
        seller_info = extract_seller_info(html)

        # 7. Amazon Services
        prime = self._extract_prime(soup)
        fresh_detection = detect_amazon_fresh(url, html)
        is_fresh = fresh_detection.is_fresh

        # 8. Promotions
        coupon = self._extract_coupon(soup)
        offers = self._extract_offers(soup)
        deal = self._extract_deal(soup)
        promotion = deal or (offers[0] if offers else None)

        # 9. Product Information / Specifications
        bullets = self._extract_bullets(soup)
        description = self._extract_description(soup)
        product_details = self._extract_product_details(soup)
        manufacturer = self._find_spec_field(product_details, ["manufacturer", "packer", "mfr"])
        country_of_origin = self._find_spec_field(product_details, ["country of origin", "origin"])
        manufacturer_part_number = self._find_spec_field(product_details, ["item part number", "part number", "manufacturer part number"])
        model = self._find_spec_field(product_details, ["model number", "model name", "model"])

        # 10. Ratings
        rating = self._extract_rating(soup)
        ratings_count = self._extract_ratings_count(soup)
        reviews_count = self._extract_reviews_count(soup)

        # 11. Media
        media = extract_media(html)

        # 12. Ranking
        bestsellers_rank = self._extract_bestsellers_rank(soup)

        return {
            # Identification
            "url": url,
            "final_url": final_url or url,
            "asin": asin,
            "product_id": product_id,

            # Product
            "title": title,
            "brand": brand,
            "store": store,
            "product_type": product_type,
            "category": category,
            "sub_category": sub_category,
            "breadcrumbs": breadcrumbs,

            # Pricing
            "price": pricing["price"],
            "price_display": pricing["price_display"],
            "mrp": pricing["mrp"],
            "mrp_display": pricing["mrp_display"],
            "discount": pricing["discount"],
            "discount_percent": pricing["discount_percent"],
            "unit_price": pricing["unit_price"],

            # Availability
            "availability": availability,
            "in_stock": in_stock,
            "stock_status": stock_status,

            # Delivery
            "requested_pincode": delivery["requested_pincode"],
            "actual_pincode": delivery["actual_pincode"],
            "delivery_location": delivery["delivery_location"],
            "delivery_info": delivery["delivery_info"],
            "delivery_date": delivery["delivery_date"],
            "delivery_time": delivery["delivery_time"],

            # Seller
            "seller": seller_info["seller"],
            "ships_from": seller_info["ships_from"],

            # Amazon Services
            "prime": prime,
            "fresh": is_fresh,
            "amazon_fresh": is_fresh,

            # Promotions
            "coupon": coupon,
            "offers": offers,
            "deal": deal,
            "promotion": promotion,

            # Product info
            "bullets": bullets,
            "description": description,
            "product_details": product_details,
            "manufacturer": manufacturer,
            "country_of_origin": country_of_origin,
            "manufacturer_part_number": manufacturer_part_number,
            "model": model,

            # Ratings
            "rating": rating,
            "ratings_count": ratings_count,
            "reviews_count": reviews_count,

            # Media
            "images": media["images"],
            "videos": media["videos"],

            # Category / Ranking
            "bestsellers_rank": bestsellers_rank,
        }

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        title_elem = soup.find(id="productTitle")
        if title_elem:
            return title_elem.get_text(strip=True)
        meta_title = soup.find("meta", property="og:title")
        if meta_title and meta_title.get("content"):
            return meta_title["content"].strip()
        return None

    def _extract_brand(self, soup: BeautifulSoup) -> Optional[str]:
        byline = soup.find(id="bylineInfo")
        if byline:
            text = byline.get_text(strip=True)
            cleaned = re.sub(r"(?i)^brand:\s*", "", text)
            cleaned = re.sub(r"(?i)^visit the\s+", "", cleaned)
            cleaned = re.sub(r"(?i)\s+store$", "", cleaned)
            return cleaned.strip() or text
        brand_row = soup.select_one("tr.po-brand td.a-span9, tr.po-brand span.po-break-word")
        if brand_row:
            return brand_row.get_text(strip=True)
        return None

    def _extract_store(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        if "fpw=alm" in url or "almBrandId" in url or "/nowstore" in url:
            return "Amazon Fresh"
        alm_brand = soup.find(id="alm-brand-title")
        if alm_brand:
            return alm_brand.get_text(strip=True)
        byline = soup.find(id="bylineInfo")
        if byline and "store" in byline.get_text(strip=True).lower():
            return byline.get_text(strip=True)
        return None

    def _extract_breadcrumbs(self, soup: BeautifulSoup) -> List[str]:
        bc_elements = soup.select("#wayfinding-breadcrumbs_feature_div ul li a")
        if bc_elements:
            return [b.get_text(strip=True) for b in bc_elements if b.get_text(strip=True)]
        return []

    def _extract_product_type(self, soup: BeautifulSoup, breadcrumbs: List[str]) -> Optional[str]:
        if breadcrumbs:
            return breadcrumbs[-1]
        pt_elem = soup.find("meta", property="og:type")
        if pt_elem and pt_elem.get("content"):
            return pt_elem["content"].strip()
        return None

    def _extract_availability(self, soup: BeautifulSoup) -> (Optional[str], Optional[bool], Optional[str]):
        avail_elem = soup.find(id="availability")
        if avail_elem:
            text = avail_elem.get_text(separator=" ", strip=True)
            lower = text.lower()
            if "in stock" in lower:
                return text, True, "IN_STOCK"
            elif "currently unavailable" in lower or "out of stock" in lower:
                return text, False, "OUT_OF_STOCK"
            elif "left in stock" in lower:
                return text, True, "LIMITED_STOCK"
            return text, None, "UNKNOWN"

        # Check out of region indicator
        oor = soup.find(class_="fresh-oor-glow-ingress")
        if oor:
            return "Out of delivery area", False, "OUT_OF_STOCK"

        # Check buybox add-to-cart
        atc = soup.find(id="add-to-cart-button") or soup.find(id="freshAddToCartButton")
        if atc:
            return "In Stock", True, "IN_STOCK"

        return None, None, None

    def _extract_prime(self, soup: BeautifulSoup) -> bool:
        prime_elem = soup.find(id="primeBadge") or soup.find(class_="a-icon-prime")
        return prime_elem is not None

    def _extract_coupon(self, soup: BeautifulSoup) -> Optional[str]:
        coupon_elem = soup.select_one(".couponLabel, #couponBadge, #vpcButton")
        if coupon_elem:
            return coupon_elem.get_text(strip=True)
        return None

    def _extract_offers(self, soup: BeautifulSoup) -> List[str]:
        offers = []
        offer_elems = soup.select(".offers-items li, #itembox-InstantBankDiscount, #vpf-accordion-header-content, #sopp_feature_div .a-box-inner")
        for o in offer_elems:
            txt = o.get_text(separator=" ", strip=True)
            if txt and txt not in offers:
                offers.append(txt)
        return offers

    def _extract_deal(self, soup: BeautifulSoup) -> Optional[str]:
        deal_elem = soup.select_one(".dealBadge, #dealBadgeSupportingText, .apexPriceToPay .a-badge-text")
        if deal_elem:
            return deal_elem.get_text(strip=True)
        return None

    def _extract_bullets(self, soup: BeautifulSoup) -> List[str]:
        bullets = []
        for li in soup.select("#feature-bullets li span.a-list-item, #featurebullets_feature_div li span.a-list-item"):
            txt = li.get_text(strip=True)
            if txt and not txt.startswith("About this item") and txt not in bullets:
                bullets.append(txt)
        return bullets

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        desc_elem = soup.find(id="productDescription") or soup.find(id="feature-bullets")
        if desc_elem:
            txt = desc_elem.get_text(separator=" ", strip=True)
            return txt if txt else None
        return None

    def _extract_product_details(self, soup: BeautifulSoup) -> Dict[str, str]:
        details: Dict[str, str] = {}

        # 1. Product details table
        rows = soup.select(
            "#productDetails_techSpec_section_1 tr, "
            "#technicalSpecifications_section_1 tr, "
            "#prodDetails table tr, "
            ".po-row"
        )
        for r in rows:
            th = r.find("th") or r.find("td", class_="a-span3") or r.find("span", class_="po-label")
            td = r.find("td") or r.find("td", class_="a-span9") or r.find("span", class_="po-break-word")
            if th and td and th != td:
                k = th.get_text(strip=True).rstrip(":")
                v = td.get_text(strip=True)
                if k and v:
                    details[k] = v

        # 2. Detail bullets list (ul li)
        bullet_rows = soup.select("#detailBullets_feature_div li")
        for li in bullet_rows:
            text = li.get_text(separator=" ", strip=True)
            if ":" in text:
                parts = text.split(":", 1)
                k = parts[0].replace("\u200e", "").replace("\u200f", "").strip()
                v = parts[1].replace("\u200e", "").replace("\u200f", "").strip()
                if k and v:
                    details[k] = v

        return details

    def _find_spec_field(self, details: Dict[str, str], aliases: List[str]) -> Optional[str]:
        for k, v in details.items():
            lower_k = k.lower()
            for alias in aliases:
                if alias in lower_k:
                    return v
        return None

    def _extract_rating(self, soup: BeautifulSoup) -> Optional[float]:
        elem = soup.select_one("#acrPopover .a-icon-alt, span[data-hook='rating-out-of-text']")
        if elem:
            txt = elem.get_text(strip=True)
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:out of|\/)\s*5", txt, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
        return None

    def _extract_ratings_count(self, soup: BeautifulSoup) -> Optional[int]:
        elem = soup.find(id="acrCustomerReviewText")
        if elem:
            txt = elem.get_text(strip=True)
            match = re.search(r"([\d,]+)", txt)
            if match:
                try:
                    return int(match.group(1).replace(",", ""))
                except ValueError:
                    pass
        return None

    def _extract_reviews_count(self, soup: BeautifulSoup) -> Optional[int]:
        elem = soup.select_one("#reviews-medley-footer .a-link-emphasis, [data-hook='total-review-count']")
        if elem:
            txt = elem.get_text(strip=True)
            match = re.search(r"([\d,]+)", txt)
            if match:
                try:
                    return int(match.group(1).replace(",", ""))
                except ValueError:
                    pass
        return None

    def _extract_bestsellers_rank(self, soup: BeautifulSoup) -> Optional[str]:
        elem = soup.select_one("#SalesRank, #detailBulletsWrapper_feature_div")
        if elem:
            txt = elem.get_text(separator=" ", strip=True)
            m = re.search(r"(#\d[\d,]*\s+in\s+[^.\n]+)", txt)
            if m:
                return m.group(1).strip()
        return None
