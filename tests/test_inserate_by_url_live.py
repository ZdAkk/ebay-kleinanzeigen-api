"""
Live integration tests for POST /inserate-by-url.

Requires the server to be running:
  uvicorn main:app

Run with:
  pytest tests/test_inserate_by_url_live.py -v

Data is fetched once per session and shared across all tests to avoid
hitting Kleinanzeigen rate limits from rapid back-to-back requests.
"""

import pytest
import httpx

BASE_URL = "http://localhost:8000"

# URL with 100k+ results — reliable target for pagination tests
LARGE_RESULT_URL = (
    "https://www.kleinanzeigen.de/s-autos/volkswagen/klima/"
    "k0c216+autos.marke_s:volkswagen"
)

EXPECTED_RESULT_FIELDS   = {"adid", "url", "title", "price", "description", "published_at"}
EXPECTED_METRICS_FIELDS  = {"pages_requested", "pages_successful", "success_rate", "average_page_time"}
EXPECTED_TOP_FIELDS      = {"success", "results", "unique_results", "time_taken",
                            "total_results", "performance_metrics"}


# ── Fixtures — fetch once, reuse across all tests ─────────────────────────────

@pytest.fixture(scope="session")
def http_client():
    try:
        httpx.get(f"{BASE_URL}/", timeout=5).raise_for_status()
    except Exception:
        pytest.skip("Server not running — start with: uvicorn main:app")
    with httpx.Client(base_url=BASE_URL, timeout=300) as client:
        yield client


@pytest.fixture(scope="session")
def single_page_response(http_client):
    resp = http_client.post("/inserate-by-url", json={"url": LARGE_RESULT_URL, "max_pages": 1})
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


@pytest.fixture(scope="session")
def four_page_response(http_client, single_page_response):
    import time
    time.sleep(5)  # wait after single-page request to avoid rate limiting
    resp = http_client.post("/inserate-by-url", json={"url": LARGE_RESULT_URL, "max_pages": 4})
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


# ── JSON structure ────────────────────────────────────────────────────────────

def test_top_level_fields_present(single_page_response):
    missing = EXPECTED_TOP_FIELDS - single_page_response.keys()
    assert not missing, f"Missing top-level fields: {missing}"


def test_performance_metrics_fields_present(single_page_response):
    pm = single_page_response["performance_metrics"]
    missing = EXPECTED_METRICS_FIELDS - pm.keys()
    assert not missing, f"Missing performance_metrics fields: {missing}"


def test_each_result_has_required_fields(single_page_response):
    for i, item in enumerate(single_page_response["results"]):
        missing = EXPECTED_RESULT_FIELDS - item.keys()
        assert not missing, f"Result #{i} missing fields: {missing}"


def test_success_flag_is_true(single_page_response):
    assert single_page_response["success"] is True


# ── total_results ─────────────────────────────────────────────────────────────

def test_total_results_present(single_page_response):
    assert "total_results" in single_page_response, "total_results field missing from response"


def test_total_results_exceeds_100k(single_page_response):
    total = single_page_response.get("total_results", 0)
    assert total > 100_000, f"Expected total_results > 100,000, got {total}"


# ── Result counts ─────────────────────────────────────────────────────────────

def test_single_page_returns_25_results(single_page_response):
    assert single_page_response["unique_results"] == 25, (
        f"Expected 25, got {single_page_response['unique_results']}"
    )
    assert len(single_page_response["results"]) == 25


def test_single_page_metrics(single_page_response):
    pm = single_page_response["performance_metrics"]
    assert pm["pages_requested"] == 1
    assert pm["pages_successful"] == 1
    assert pm["success_rate"] == 100.0


def test_four_pages_returns_100_results(four_page_response):
    assert four_page_response["unique_results"] == 100, (
        f"Expected 100 results for 4 pages, got {four_page_response['unique_results']}"
    )
    assert len(four_page_response["results"]) == 100


def test_four_pages_metrics(four_page_response):
    pm = four_page_response["performance_metrics"]
    assert pm["pages_requested"] == 4
    assert pm["pages_successful"] == 4
    assert pm["success_rate"] == 100.0
