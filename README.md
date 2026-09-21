# Amazon Fresh & Quick-Commerce Scraper API

A production-grade, FastAPI-based scraping service designed specifically for **Amazon Fresh** and **Amazon Quick-Commerce** product, keyword search, and category listing pages. Built with input-driven delivery pincode setting, robust GLOW location configuration, bounded and infinite pagination control, centralized API key authentication, anti-blocking protection, Indian residential/datacenter proxy integration with ScraperAPI, session consistency, and multi-signal Fresh detection.

---

## 🌟 Key Architecture & Capabilities

### 1. Robust Pincode Setting & Multi-Stage Verification Engine
- **Root Cause Resolved**: Previously, when requesting non-default pincodes (such as `400001`, `400015`, `560001`, or `110001`) from an Indian IP, Amazon's server-side session defaults to the client ISP's geo-IP (such as Chennai `600078`). A verification step that fetched the generic root gateway (`https://www.amazon.in`) caused false mismatches because Amazon's root gateway displays the client's ISP IP location on unauthenticated sessions instead of the Amazon Fresh ALM delivery address.
- **The Solution**:
  1. **Fresh Node Warmup**: Initializes session cookies (`session-id`, `sst-acbin`, `i18n-prefs=INR`, `lc-acbin=en_IN`) and extracts the `anti-csrftoken-a2z` security token from Amazon Fresh browse nodes.
  2. **Dual GLOW Configuration**: Dispatches both form-urlencoded delivery AJAX requests (`/gp/delivery/ajax/address-change.html`) and GLOW JSON requests (`/portal-migration/hz/glow/address-change?actionSource=glow`) with active CSRF tokens and matching browse referers.
  3. **Direct Address Confirmation**: Inspects the JSON response from Amazon's address-change service (`{"isValidAddress": 1, "isAddressUpdated": 1, "address": {"zipCode": "...", "city": "..."}}`), confirming delivery location immediately without relying on unauthenticated gateway IP geolocation.
  4. **Dedicated Logging**: Every operation is logged with `PINCODE | Requested: {pincode}, Setting: GLOW, Returned: {actual_pincode}, Verification: {status}`.

### 2. Flexible Pagination Control (`page` Parameter)
- Supports an optional `page` parameter in `POST /api/v1/scrape/search` and `POST /api/v1/scrape/category`:
  - **Bounded Scraping**: When `page` is provided (e.g. `2` or `"2"`), the scraper scrapes pages 1 through `page`.
  - **Until End Page**: When `page` is omitted, `null`, or empty `""`, the scraper automatically paginates through all available pages until the final end page.
  - **Strict Validation**: If `page` is non-numeric (e.g. `"abc"`) or less than 1, a `422 Unprocessable Content` validation error is returned.
  - **PAGINATION Logging**: Logs exact pagination state (`PAGINATION | Page limit set to {N}; scraping pages 1 through {N}` or `PAGINATION | No page limit specified; scraping until end of pagination`).

### 3. Centralized API Key Authentication
- **Centralized Config**: Stored in a dedicated configuration module (`config/api_key.py`), loaded via `SCRAPER_API_KEY` or `API_KEY` environment variable.
- **Pre-Execution Enforcement**: The `"apikey"` field is verified in the API request body **before** any scraping process, session initialization, network warmup, or Amazon call takes place.
- **Security & Error Contracts**:
  - Missing API key: Returns HTTP `422 Unprocessable Content` with `{"detail": "API key is required"}`.
  - Invalid API key: Returns HTTP `401 Unauthorized` with `{"detail": "Invalid API key"}`.
  - Valid API key: Logs `AUTH | API key validated successfully`.
  - **Zero Key Leakage**: The actual API key value is never printed or written to log files.

### 4. ScraperAPI Indian Proxy Integration & Prompt Correction
- **Configured Proxy**:
  ```python
  proxies = {
      "http": "http://scraperapi.country_code=ind:c5c0632e2085b50a6858e2aecad14cc2@proxy-server.scraperapi.com:8001",
      "https": "http://scraperapi.country_code=ind:c5c0632e2085b50a6858e2aecad14cc2@proxy-server.scraperapi.com:8001"
  }
  ```
- **Correction of Prompt Explained**:
  1. **ISO 3166-1 Alpha-2 Country Code**: In ScraperAPI's proxy architecture, country codes strictly require 2-letter ISO 3166-1 alpha-2 codes (`in` for India). When `country_code=ind` (3 letters) is sent, ScraperAPI does not recognize it as India and falls back to random international proxies (e.g., Portugal, France, Australia), resulting in high latency or timeouts. Our engine includes an automatic proxy normalizer (`normalize_proxy_url`) that transparently converts `country_code=ind` to `country_code=in` at runtime, ensuring that requests always route to authentic Indian residential/datacenter nodes (Mumbai / Reliance Jio / Airtel).
  2. **TLS / SSL Inspection Bypass**: ScraperAPI operates as an HTTPS-intercepting proxy. Because it decrypts traffic using its own certificate authority, standard Python `requests` verification fails with `SSLCertVerificationError` unless `verify_ssl=False` (with `urllib3.disable_warnings`) is configured. The scraper automatically detects ScraperAPI proxies and configures `session.verify = False` while preserving encrypted transit.
  3. **Optimized Latency & Headroom**: Indian proxy routing introduces standard gateway latency (1.5s–5s per request). `REQUEST_TIMEOUT` is set to 35 seconds to ensure reliable end-to-end execution.

### 5. Amazon Fresh ALM Infinite Scroll & Category Aisle Extraction
- Handles modern Amazon Local Market (ALM) category pages (`/alm/category/fresh/...`).
- Resolves all 38+ category sub-aisles with real category paths and node IDs (extracted via `data-node-link`).
- Seamlessly bridges SPA category landing shells to paginated product catalog streams (`/gp/search?ie=UTF8&keywords={cat}&almBrandId=ctnow&fpw=alm`), avoiding WAF challenges and extracting live products across all pages.

---

## 📂 Project Structure

```text
amazon_fresh_scraper/
│
├── config/
│   ├── __init__.py             # Config package initializer
│   └── api_key.py              # Centralized API key definition & validate_api_key()
│
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application, exception handlers & lifespan
│   ├── config.py               # Pydantic BaseSettings & environment variables
│   ├── logging_config.py       # Custom formatted logging adapter with categories
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py           # Product, Search, Category, Health endpoints
│   │   └── schemas.py          # Pydantic v2 request/response & validation schemas
│   │
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── session.py          # AmazonSessionContext, proxy normalizer, SSL config
│   │   ├── pincode.py          # Dual GLOW location configuration & verification
│   │   ├── listing_scraper.py  # Search & category scraper with pagination & ALM bridge
│   │   ├── product.py          # 10-stage Amazon Fresh product scraping pipeline
│   │   └── anti_block.py       # Anti-bot, CAPTCHA, WAF, bm-verify challenge detector
│   │
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── listing_parser.py   # Search/category product card & aisle parser
│   │   ├── product_parser.py   # Full 32+ product field extractor
│   │   ├── pricing.py          # Currency & pricing utilities
│   │   └── delivery.py         # Delivery estimate & location text parser
│   │
│   └── utils/
│       ├── __init__.py
│       └── validation.py       # Pincode, product URL, and category URL validators
│
├── tests/
│   ├── test_all.py             # 61 pytest test cases covering all features
│   └── fixtures/               # Sample HTML mock files for deterministic testing
│
├── .env                        # Active environment configuration
├── .env.example                # Example environment configuration
├── requirements.txt            # Python dependencies
└── README.md                   # Complete architectural and API documentation
```

---

## ⚙️ Setup & Configuration

### 1. Installation

```bash
cd amazon_fresh_scraper
pip install -r requirements.txt
```

### 2. Environment Variables (`.env`)
```ini
# Amazon Base Target
AMAZON_BASE_URL=https://www.amazon.in

# Timeouts & Retries
REQUEST_TIMEOUT=35
MAX_RETRIES=3
RETRY_BACKOFF_FACTOR=1.5

# Application Server
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO
DEBUG_MODE=false

# Authentication
SCRAPER_API_KEY=fresh-api-key-2026-secure

# Network & Proxy (Configured with ScraperAPI India Proxy)
PROXY_URL=http://scraperapi.country_code=ind:c5c0632e2085b50a6858e2aecad14cc2@proxy-server.scraperapi.com:8001
VERIFY_SSL=false

# Scraper Rules
STRICT_FRESH_CHECK=true
STRICT_PINCODE_VERIFY=true
```

---

## 🚀 Running the API Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## 🧪 Running Tests

Run the full test suite (61 tests covering pincode setting, non-600078 verification, pagination limits, API key authentication, ScraperAPI proxy normalization/SSL handling, and ALM category infinite scroll):

```bash
PYTHONPATH=. pytest -v
```

---

## 📡 API Endpoints & Usage

### Authentication Contract
All scraping endpoints require `"apikey"` in the JSON request body:
- **Missing `"apikey"`**: `HTTP 422 Unprocessable Content` -> `{"detail": "API key is required"}`
- **Invalid `"apikey"`**: `HTTP 401 Unauthorized` -> `{"detail": "Invalid API key"}`

---

### 1. Keyword Search Scraping
`POST /api/v1/scrape/search`

Scrapes Amazon Fresh keyword search results.
- **Bounded pages**: Pass `"page": 2` to scrape pages 1 through 2.
- **Until end page**: Omit `"page"` (or set `null`) to scrape until the end of available pagination.

```bash
# Scrape pages 1 through 2 with Mumbai pincode 400001
curl -X POST http://localhost:8000/api/v1/scrape/search \
  -H "Content-Type: application/json" \
  -d '{
    "request_type": "search",
    "keyword": "milk",
    "pincode": "400001",
    "apikey": "fresh-api-key-2026-secure",
    "page": 2
  }'
```

---

### 2. Category Scraping
`POST /api/v1/scrape/category`

Scrapes an Amazon Fresh category page, resolving sub-aisles and streaming products.

```bash
# Scrape category pages 1 through 1 with Bangalore pincode 560001
curl -X POST http://localhost:8000/api/v1/scrape/category \
  -H "Content-Type: application/json" \
  -d '{
    "request_type": "category",
    "url": "https://www.amazon.in/alm/category/fresh/Fruit-Juice?almBrandId=ctnow&node=4859554031",
    "pincode": "560001",
    "apikey": "fresh-api-key-2026-secure",
    "page": 1
  }'
```

---

### 3. Product Page Scraping
`POST /api/v1/scrape/product`

Scrapes 32+ product fields for a specific Amazon Fresh product URL.

```bash
curl -X POST http://localhost:8000/api/v1/scrape/product \
  -H "Content-Type: application/json" \
  -d '{
    "request_type": "product",
    "url": "https://www.amazon.in/dp/B0H5QSCFTW?fpw=alm&almBrandId=ctnow",
    "pincode": "400001",
    "apikey": "fresh-api-key-2026-secure"
  }'
```

---

## 🖥️ Log Formatting Example

```text
2026-09-18 11:00:26 | INFO     | AUTH     | API key validated successfully
2026-09-18 11:00:26 | INFO     | PAGINATION | Page limit set to 1; scraping pages 1 through 1
2026-09-18 11:00:26 | INFO     | SEARCH   | Starting SEARCH scrape for 'mango' with pincode: 400001 (Pagination: up to 1 pages)
2026-09-18 11:00:43 | INFO     | PINCODE  | Setting delivery pincode: 400001
2026-09-18 11:00:43 | INFO     | PINCODE  | Requested pincode: 400001
2026-09-18 11:00:48 | INFO     | PINCODE  | Requested: 400001, Setting: GLOW, Returned: 400001, Verification: verified
2026-09-18 11:00:48 | INFO     | PINCODE  | Actual pincode: 400001
2026-09-18 11:00:48 | INFO     | PINCODE  | Verification status: verified
2026-09-18 11:00:48 | INFO     | PINCODE  | Pincode verified successfully
2026-09-18 11:00:48 | INFO     | PAGE     | Fetching page 1 from: https://www.amazon.in/gp/search?ie=UTF8&keywords=mango&almBrandId=ctnow&fpw=alm
2026-09-18 11:00:50 | INFO     | PAGE     | Page 1 completed: 48 new items extracted (Total items: 48) | Has Next: YES
2026-09-18 11:00:50 | INFO     | PAGINATION | Reached requested limit of 1 pages.
2026-09-18 11:00:50 | INFO     | REQUEST  | SEARCH scrape completed: 48 products across 1 pages in 23.78s
```
"# Amazon_fresh" 
