# Ebay Kleinanzeigen API

<div align="center">
  <h3 align="center">Ebay Kleinanzeigen API</h3>

  <p align="center">
    A powerful API interface for Ebay-Kleinanzeigen.de that enables you to fetch listings and specific data.
  </p>

  <p align="center">
    <b>🚀 Looking for a ready-to-use solution?</b>
    <br />
    Try it at <a href="https://kleinanzeigen-agent.de/features/developer-api"><strong>kleinanzeigen-agent.de »</strong></a>
    <br />
    ✓ Automated Search Agents
    <br />
    ✓ Search & Detail API
    <br />
    <a href="https://github.com/DanielWTE/ebay-kleinanzeigen-api/issues">Report Bug</a>
    ·
    <a href="https://github.com/DanielWTE/ebay-kleinanzeigen-api/issues">Request Feature</a>
  </p>
</div>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Want to skip the setup?

Visit [kleinanzeigen-agent.de](https://kleinanzeigen-agent.de/features/developer-api) for our hosted solution with additional features and zero configuration required.

### Prerequisites

- Python 3.12 or higher
- pip (Python package manager)
- Playwright

### Installation

1. Clone the repository

```sh
git clone https://github.com/DanielWTE/ebay-kleinanzeigen-api.git
cd ebay-kleinanzeigen-api
```

2. Install dependencies

```sh
pip install -r requirements.txt
playwright install chromium
```

3. Start the API

```sh
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

#### Non-headless mode (visible browser)

Set the `HEADLESS` environment variable to `false` to watch the browser while scraping — useful during development:

```sh
HEADLESS=false uvicorn main:app --reload
```

### Installation using UV

#### Prerequisites

- uv package manager

#### Installation of dependencies

```sh
uv sync
```

#### Start the API

```sh
uv run uvicorn main:app --reload
```

#### Non-headless mode with UV

```sh
HEADLESS=false uv run uvicorn main:app --reload
```

### Installation using Docker

1. Build the Docker image

```sh
docker build -t ebay-kleinanzeigen-api .
```

2. Run the Docker container

```sh
docker run -p 8000:8000 ebay-kleinanzeigen-api
```

The API will be available at `http://localhost:8000`

### API Endpoints

#### 1. Fetch Listings (Standard)

**Endpoint:** `GET /inserate`

**Description:** Retrieves a list of listings based on search criteria.

##### Query Parameters

- **`query`** *(string, optional)*: The search term (e.g., "fahrrad" to search for bicycles).
- **`location`** *(string, optional)*: The location or postal code to narrow the search (e.g., `10178` for Berlin).
- **`radius`** *(integer, optional)*: The search radius in kilometers from the specified location (e.g., `5` for a 5 km radius).
- **`min_price`** *(integer, optional)*: The minimum price in Euros for the listings (e.g., `200` for at least 200 Euros).
- **`max_price`** *(integer, optional)*: The maximum price in Euros for the listings (e.g., `500` for at most 500 Euros).
- **`page_count`** *(integer, optional)*: The number of pages to search or return (e.g., `5` for the first 5 pages, default is 1, max: 20 pages).

##### Example Request

```http
GET /inserate?query=fahrrad&location=10178&radius=5&min_price=200&page_count=5
```

#### 2. Fetch Listing Details

**Endpoint:** `GET /inserat/{id}`

**Description:** Retrieves detailed information about a specific listing.

##### Path Parameters

- **`id`** *(string)*: The unique identifier of the listing to fetch details for.

##### Example Request

```http
GET /inserat/12345
```

#### 3. Fetch Listings with Details (Combined)

**Endpoint:** `GET /inserate-detailed`

**Description:** Retrieves listings and their detailed information in a single request.

##### Query Parameters

Same as `/inserate` endpoint, plus:

- **`max_concurrent_details`** *(integer, optional)*: Maximum concurrent detail fetches (default: 5, max: 10).

##### Example Request

```http
GET /inserate-detailed?query=laptop&page_count=2&max_concurrent_details=5
```

#### 4. Scrape by URL

**Endpoint:** `POST /inserate-by-url`

**Description:** Scrape listings using a full Kleinanzeigen search URL. All filters already encoded in the URL (category, brand, year, fuel type, transmission, car type, etc.) are preserved as-is. Page numbers are injected automatically for multi-page fetching. Use this when `/inserate` does not yet support a filter you need.

Pages are fetched **sequentially** to avoid IP-level rate limiting by Kleinanzeigen.

##### Request Body

```json
{
  "url": "https://www.kleinanzeigen.de/s-autos/volkswagen/klima/k0c216+autos.marke_s:volkswagen",
  "max_pages": 3
}
```

- **`url`** *(string, required)*: Any Kleinanzeigen search or category URL.
- **`max_pages`** *(integer, optional)*: Number of pages to fetch (default: 1). Each page returns up to 25 listings.

##### Example Request

```sh
curl -X POST http://localhost:8000/inserate-by-url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.kleinanzeigen.de/s-autos/volkswagen/klima/k0c216+autos.ez_i:2008%2C+autos.fuel_s:(cng%2Clpg)+autos.marke_s:volkswagen+autos.shift_s:automatik+autos.typ_s:(kombi%2Csuv)",
    "max_pages": 3
  }'
```

##### Example Response

```json
{
  "success": true,
  "results": [
    {
      "adid": "3398033022",
      "url": "https://www.kleinanzeigen.de/s-anzeige/...",
      "title": "VW Golf Variant 2.0 TDI Automatik Klima",
      "price": "12500",
      "description": "Gepflegter Zustand, Erstbesitz...",
      "published_at": "2026-05-03T22:06:00"
    }
  ],
  "unique_results": 75,
  "total_results": 120140,
  "time_taken": 12.358,
  "performance_metrics": {
    "pages_requested": 3,
    "pages_successful": 3,
    "success_rate": 100.0,
    "average_page_time": 4.119
  },
  "browser_metrics": {
    "contexts_created": 3,
    "contexts_reused": 0,
    "contexts_in_pool": 3,
    "contexts_in_use": 0
  }
}
```

**Response fields:**

- **`results`**: Array of listing objects. Each listing contains:
  - `adid` — Kleinanzeigen internal listing ID
  - `url` — Direct link to the listing
  - `title` — Listing title
  - `price` — Price as string (numeric digits only, no currency symbol; empty string if not set)
  - `description` — Short teaser text from the listing card
  - `published_at` — ISO 8601 publish datetime (e.g. `"2026-05-03T22:06:00"`). Older listings show only the date at midnight (`"2026-04-26T00:00:00"`). `null` if not shown on the card.
- **`unique_results`**: Total number of listings returned across all fetched pages.
- **`total_results`**: Total hits reported by Kleinanzeigen for this search (e.g. `120140`). Extracted from the page breadcrumb on the first page load — no extra request needed.
- **`time_taken`**: Total elapsed time in seconds.
- **`performance_metrics.pages_requested`** / **`pages_successful`** / **`success_rate`**: Page-level fetch statistics.

#### 5. Convert URL to API Parameters

**Endpoint:** `POST /convert-url`

**Description:** Parses a Kleinanzeigen URL and returns two groups of parameters: `inserate_params` (what the `/inserate` endpoint currently understands) and `unmapped` (filters not yet supported by `/inserate`, such as category, brand, year, or transmission). Useful for inspecting which parts of a URL can be expressed via the structured API.

##### Request Body

```json
{
  "url": "https://www.kleinanzeigen.de/s-autos/volkswagen/klima/k0c216+autos.marke_s:volkswagen"
}
```

##### Example Request

```sh
curl -X POST http://localhost:8000/convert-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.kleinanzeigen.de/s-autos/volkswagen/klima/k0c216+autos.ez_i:2008%2C+autos.marke_s:volkswagen"}' \
  | python -m json.tool
```

##### Example Response

```json
{
  "inserate_params": {
    "query": "klima",
    "page_count": 1
  },
  "unmapped": {
    "category_slug": "s-autos",
    "subcategory": "volkswagen",
    "category_id": 216,
    "year_from": 2008,
    "year_to": null,
    "brands": ["volkswagen"]
  }
}
```

### Documentation

#### API Response Format

##### `GET /inserate` and `GET /inserate-detailed`

```json
{
  "success": true,
  "time_taken": 1.23,
  "unique_results": 25,
  "data": [
    {
      "adid": "123456",
      "url": "https://www.kleinanzeigen.de/s-anzeige/...",
      "title": "Example Item",
      "price": "100",
      "description": "Short teaser text..."
    }
  ],
  "performance_metrics": {
    "pages_requested": 1,
    "pages_successful": 1,
    "success_rate": 100.0,
    "average_page_time": 1.23
  }
}
```

The `/inserate-detailed` response additionally nests a `details` object inside each listing with full description, seller info, and location.

##### `POST /inserate-by-url`

```json
{
  "success": true,
  "results": [
    {
      "adid": "123456",
      "url": "https://www.kleinanzeigen.de/s-anzeige/...",
      "title": "Example Item",
      "price": "100",
      "description": "Short teaser text...",
      "published_at": "2026-05-03T22:06:00"
    }
  ],
  "unique_results": 75,
  "total_results": 120140,
  "time_taken": 12.358,
  "performance_metrics": {
    "pages_requested": 3,
    "pages_successful": 3,
    "success_rate": 100.0,
    "average_page_time": 4.119
  },
  "browser_metrics": { ... }
}
```

`total_results` is the total hit count shown by Kleinanzeigen (e.g. `120140`). It is extracted from the breadcrumb of the first page — no extra request is made. The field is omitted if the breadcrumb is not found.

##### `POST /convert-url`

```json
{
  "inserate_params": {
    "query": "klima",
    "page_count": 1
  },
  "unmapped": {
    "category_slug": "s-autos",
    "subcategory": "volkswagen",
    "category_id": 216,
    "year_from": 2008,
    "year_to": null,
    "brands": ["volkswagen"]
  }
}
```

## Performance Features

## 📊 Performance Benchmarks

Performance tests conducted on **Arch Linux** with **Intel i7-1260P** processor:

| Endpoint | Operation | Avg Time | Min Time | Max Time | Success Rate | Results |
|----------|-----------|----------|----------|----------|--------------|---------|
| Root | API status check | 0.004s | 0.001s | 0.009s | 100% | - |
| Listings | 1 page search | 1.209s | 1.081s | 1.596s | 100% | 25 |
| Listings | 5 pages search | 2.436s | 2.328s | 2.532s | 100% | 125 |
| Listings | 10 pages search | 4.989s | 4.790s | 5.229s | 100% | 250 |
| Details | Single listing details | 1.072s | 0.928s | 1.276s | 100% | 1 |
| Combined | 1 page + details | 9.058s | 8.804s | 9.319s | 100% | 25 |
| Combined | 2 pages + details | 17.512s | 17.063s | 18.038s | 100% | 50 |

### Performance Highlights

- **Single page search**: ~1.2s average response time
- **10-page search**: ~5.0s average response time  
- **Individual listing details**: ~1.1s average response time
- **Combined search + details**: ~9.1s average for 1 page with full details

*All tests performed with uvloop optimization and browser context pooling enabled.*

### 🚀 Technical Features

- **uvloop Integration**: High-performance asyncio event loop
- **Context Pooling**: Efficient browser resource reuse
- **Memory Optimization**: Automatic garbage collection and efficient processing
- **Intelligent Concurrency**: Optimal concurrent processing with resource control

### 🔧 Production Ready

- **Clean API Responses**: Minimal overhead with essential data only
- **Resource Management**: Automatic cleanup and efficient resource usage
- **Scalable Architecture**: Handles concurrent requests efficiently
- **Docker Optimized**: Fast container builds with uv package manager

API documentation is available at `http://localhost:8000/docs` when running locally.

## License

Distributed under the MIT License. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>
