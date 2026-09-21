import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from app.parser.pricing import clean_price_to_float, format_price_display


class ListingParser:
    """
    Parses Amazon Fresh search results and category listing pages.
    Extracts individual product cards, pricing, ratings, badges, and pagination metadata.
    """

    def __init__(self, base_url: str = "https://www.amazon.in"):
        self.base_url = base_url

    def parse(self, html: str, page_url: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Parses HTML and returns:
            (products_list, pagination_info_dict)
        """
        if not html:
            return [], {
                "current_page": 1,
                "total_pages": 1,
                "has_next_page": False,
                "next_page_url": None,
                "products_on_page": 0,
            }

        soup = BeautifulSoup(html, "html.parser")
        products = self._extract_products(soup, page_url)
        pagination = self._extract_pagination(soup, page_url)
        pagination["products_on_page"] = len(products)
        category_info = self.extract_category_info(soup, page_url)

        return products, pagination, category_info

    def extract_category_info(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        """
        Extracts ALM Fresh category metadata and available aisles / subcategories.
        Designed for URLs like:
        https://www.amazon.in/alm/category/fresh/Fruit-Juice?almBrandId=ctnow&node=4859554031
        """
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(page_url)
        qs = parse_qs(parsed.query)

        node_id = qs.get("node", [None])[0]
        alm_brand_id = qs.get("almBrandId", [None])[0]

        # Extract category name from path or title
        category_name = None
        cat_match = re.search(r"/alm/category/(?:fresh/)?([^/?]+)", parsed.path)
        if cat_match:
            category_name = cat_match.group(1).replace("-", " ")
        elif soup.find("title"):
            title_text = soup.find("title").get_text(strip=True)
            # Remove "Buy" and "online at best prices in India"
            cleaned_title = re.sub(r"(?i)^buy\s+", "", title_text)
            cleaned_title = re.sub(r"(?i)\s+online\s+at\s+best\s+prices.*", "", cleaned_title)
            category_name = cleaned_title.strip()

        # Extract Aisles / Subcategory links
        aisle_nodes = soup.select(
            "a[class*='aislesNode'], "
            "a[class*='categoryNode'], "
            "a[href*='/alm/category/'], "
            "a[data-node-link], "
            "._browse-bar-widget_style_aislesNode__3TBgp, "
            "._browse-bar-widget_style_categoryNodeDesktop__3kUmi"
        )

        aisles: List[Dict[str, Any]] = []
        seen_titles = set()

        for a in aisle_nodes:
            txt = a.get_text(strip=True)
            raw_href = a.get("data-node-link") or a.get("href")
            img = a.find("img")
            img_src = img.get("src") if img else None

            if txt and txt not in seen_titles and len(txt) > 1:
                seen_titles.add(txt)
                full_href = (
                    urljoin(self.base_url, raw_href)
                    if raw_href and not raw_href.startswith("javascript:") and not raw_href.startswith("#")
                    else None
                )
                sub_node = a.get("data-browse-node-id")
                if not sub_node and full_href:
                    m = re.search(r"node=(\d+)", full_href)
                    if m:
                        sub_node = m.group(1)

                aisles.append({
                    "title": txt,
                    "url": full_href,
                    "node_id": sub_node,
                    "image_url": img_src,
                })

        return {
            "category_name": category_name,
            "node_id": node_id,
            "alm_brand_id": alm_brand_id,
            "aisles": aisles,
        }

    def _extract_products(self, soup: BeautifulSoup, page_url: str) -> List[Dict[str, Any]]:
        products: List[Dict[str, Any]] = []

        # Find search result blocks, grid items, and ALM Fresh cards with ASIN
        item_nodes = soup.select(
            "div[data-asin]:not([data-asin='']), "
            "li[data-asin]:not([data-asin='']), "
            "div[data-component-type='s-search-result'], "
            ".s-result-item[data-asin]:not([data-asin='']), "
            "li.a-carousel-card[data-asin]:not([data-asin='']), "
            "li.a-carousel-card div[data-asin]:not([data-asin='']), "
            "div[class*='product-card'][data-asin]:not([data-asin='']), "
            "div[class*='grid-view-item'][data-asin]:not([data-asin='']), "
            "div[class*='productCard'][data-asin]:not([data-asin='']), "
            "div[class*='dealTile'][data-asin]:not([data-asin='']), "
            "div.octopus-pc-item[data-asin]:not([data-asin=''])"
        )

        seen_asins = set()

        for node in item_nodes:
            asin = node.get("data-asin", "").strip().upper()
            if not asin or len(asin) != 10 or asin in seen_asins:
                continue

            # 1. Title & URL
            title_elem = (
                node.select_one("h2 a span, h2.a-size-mini span, .s-title-instructions-style h2 span, h2 a, h2, span.a-text-normal")
                or node.select_one("span.a-truncate-cut")
                or node.select_one("div[class*='title'] a, div[class*='product-title'], a.a-link-normal span[class*='title']")
                or node.select_one("a.a-link-normal[title]")
            )
            title = title_elem.get_text(strip=True) if title_elem else None

            # Skip header or empty result rows
            if not title or len(title) < 2:
                continue

            seen_asins.add(asin)

            link_elem = node.select_one(
                "h2 a[href], "
                "a.a-link-normal.s-no-outline[href], "
                "a.a-link-normal[href*='/dp/'], "
                "a[href*='/dp/']"
            )
            href = link_elem.get("href") if link_elem else f"/dp/{asin}"
            full_url = urljoin(self.base_url, href)

            # 2. Brand
            brand_elem = node.select_one(
                "span.a-size-base-plus.a-color-base, "
                "h5.s-line-clamp-1, "
                ".s-line-clamp-1, "
                "span[class*='brand']"
            )
            brand = brand_elem.get_text(strip=True) if brand_elem else None
            if brand and title and brand.lower() in title.lower() and len(brand) > len(title):
                brand = None

            # 3. Pricing
            price = None
            price_display = None
            price_elem = node.select_one(
                ".priceToPay span.a-offscreen, "
                "span.a-price:not(.a-text-price) span.a-offscreen, "
                ".a-price span.a-offscreen, "
                ".a-color-price"
            )
            if price_elem:
                raw_p = price_elem.get_text(strip=True)
                amt = clean_price_to_float(raw_p)
                if amt is not None:
                    price = amt
                    price_display = format_price_display(amt, raw_p)

            # Alternate price extraction from whole + fraction
            if price is None:
                whole = node.select_one("span.a-price-whole")
                if whole:
                    w_str = whole.get_text(strip=True).replace(",", "").rstrip(".")
                    frac = node.select_one("span.a-price-fraction")
                    f_str = frac.get_text(strip=True) if frac else "00"
                    amt = clean_price_to_float(f"{w_str}.{f_str}")
                    if amt is not None:
                        price = amt
                        price_display = f"₹{amt:,.2f}"

            # MRP
            mrp = None
            mrp_display = None
            mrp_elem = node.select_one(
                "span.a-price.a-text-price span.a-offscreen, "
                "span.a-text-strike, "
                ".basisPrice span.a-offscreen"
            )
            if mrp_elem:
                raw_mrp = mrp_elem.get_text(strip=True)
                amt_mrp = clean_price_to_float(raw_mrp)
                if amt_mrp is not None:
                    mrp = amt_mrp
                    mrp_display = format_price_display(amt_mrp, raw_mrp)

            # Discount
            discount_percent = None
            savings_elem = node.select_one("span.savingsPercentage")
            if not savings_elem:
                for sp in node.select("span"):
                    if "% off" in sp.get_text():
                        savings_elem = sp
                        break
            if savings_elem:
                pct_m = re.search(r"(\d+(?:\.\d+)?)\s*%", savings_elem.get_text(strip=True))
                if pct_m:
                    discount_percent = float(pct_m.group(1))

            if discount_percent is None and price and mrp and mrp > price:
                discount_percent = round(((mrp - price) / mrp) * 100, 2)

            # Unit price
            unit_price = None
            unit_elem = node.select_one("span.pricePerUnit")
            if not unit_elem:
                for sp in node.select("span.a-size-small, span.a-color-secondary"):
                    if "/" in sp.get_text():
                        unit_elem = sp
                        break
            if unit_elem:
                u_text = unit_elem.get_text(strip=True)
                if "/" in u_text and ("₹" in u_text or "Rs" in u_text or "g" in u_text or "kg" in u_text or "l" in u_text or "ml" in u_text):
                    unit_price = u_text

            # 4. Rating & Reviews
            rating = None
            rating_elem = node.select_one("i.a-icon-star-small span.a-icon-alt, i.a-icon-star span.a-icon-alt, span[aria-label*='out of 5 stars']")
            if rating_elem:
                r_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:out of|\/)\s*5", rating_elem.get_text(strip=True), re.IGNORECASE)
                if r_m:
                    rating = float(r_m.group(1))

            ratings_count = None
            reviews_elem = node.select_one(
                "span.a-size-base.s-underline-text, "
                "a[href*='#customerReviews'] span, "
                "span.s-underline-text, "
                ".s-underline-text"
            )
            if reviews_elem:
                rc_m = re.search(r"([\d,]+)", reviews_elem.get_text(strip=True))
                if rc_m:
                    ratings_count = int(rc_m.group(1).replace(",", ""))

            # 5. Image
            image_url = None
            img_elem = node.select_one("img.s-image, img.product-image, img[data-src]")
            if img_elem:
                image_url = img_elem.get("src") or img_elem.get("data-src")

            # 6. Availability
            is_in_stock = True
            avail_elem = node.select_one(".a-color-price, .s-availability-message")
            if avail_elem and any(t in avail_elem.get_text().lower() for t in ["currently unavailable", "out of stock"]):
                is_in_stock = False

            # 7. Badges & Services
            badge = None
            badge_elem = node.select_one(".a-badge-text, .dealBadge, .s-coupon-unclipped")
            if badge_elem:
                badge = badge_elem.get_text(strip=True)

            is_sponsored = bool(node.select_one(".puis-sponsored-label-text, span:-soup-contains('Sponsored')"))
            is_fresh = bool(
                node.select_one("i.a-icon-fresh, [aria-label*='Fresh'], .alm-badge") or
                "fpw=alm" in full_url or
                "almBrandId" in full_url or
                "/nowstore" in full_url or
                "fresh" in (badge or "").lower()
            )

            products.append({
                "asin": asin,
                "title": title,
                "url": full_url,
                "brand": brand,
                "price": price,
                "price_display": price_display,
                "mrp": mrp,
                "mrp_display": mrp_display,
                "discount_percent": discount_percent,
                "unit_price": unit_price,
                "rating": rating,
                "ratings_count": ratings_count,
                "image_url": image_url,
                "is_in_stock": is_in_stock,
                "badge": badge,
                "is_sponsored": is_sponsored,
                "is_fresh": is_fresh,
            })

        return products

    def _extract_pagination(self, soup: BeautifulSoup, page_url: str) -> Dict[str, Any]:
        """
        Extracts current page number, total pages (if visible), and next page URL.
        """
        current_page = 1
        total_pages = 1
        has_next_page = False
        next_page_url = None

        # 1. Detect current page from active pagination indicator
        selected_elem = soup.select_one(
            "span.s-pagination-item.s-pagination-selected, "
            "li.a-selected a, "
            "li.a-selected"
        )
        if selected_elem:
            try:
                current_page = int(re.sub(r"[^\d]", "", selected_elem.get_text(strip=True)))
            except (ValueError, TypeError):
                pass
        else:
            # Check query param in current page_url
            m = re.search(r"[?&]page=(\d+)", page_url)
            if m:
                current_page = int(m.group(1))

        # 2. Detect total pages from pagination items
        page_numbers = []
        for p_elem in soup.select("span.s-pagination-item, li.a-normal a"):
            txt = p_elem.get_text(strip=True)
            if txt.isdigit():
                page_numbers.append(int(txt))

        if page_numbers:
            total_pages = max(page_numbers)
        else:
            total_pages = current_page

        # 3. Detect Next Page Button
        # Active next button exists when it is an anchor and NOT disabled
        next_btn = soup.select_one(
            "a.s-pagination-next:not(.s-pagination-disabled), "
            "li.a-last:not(.a-disabled) a, "
            "a[class*='pagination-next']:not([class*='disabled'])"
        )

        disabled_next = soup.select_one(
            "span.s-pagination-next.s-pagination-disabled, "
            "li.a-last.a-disabled"
        )

        if next_btn and not disabled_next:
            href = next_btn.get("href")
            if href:
                has_next_page = True
                next_page_url = urljoin(self.base_url, href)

        return {
            "current_page": current_page,
            "total_pages": max(total_pages, current_page),
            "has_next_page": has_next_page,
            "next_page_url": next_page_url,
        }
