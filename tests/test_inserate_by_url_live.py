"""
Live integration tests for POST /inserate-by-url.

Requires the server to be running:
  uvicorn main:app

Run with:
  pytest tests/test_inserate_by_url_live.py -v

Data is fetched once per session and shared across all tests to avoid
hitting Kleinanzeigen rate limits from rapid back-to-back requests.
Fixtures are chained so each request waits for the previous one before
sleeping — guaranteeing sequential execution with cooldowns.
"""

import time
from datetime import datetime
import pytest
import httpx

BASE_URL = "http://localhost:8000"

# URL with 100k+ results — reliable target for pagination tests
LARGE_RESULT_URL = (
    "https://www.kleinanzeigen.de/s-autos/volkswagen/klima/"
    "k0c216+autos.marke_s:volkswagen"
)

EXPECTED_RESULT_FIELDS = {
    "adid",
    "url",
    "title",
    "price",
    "description",
    "published_at",
}
EXPECTED_METRICS_FIELDS = {
    "pages_requested",
    "pages_successful",
    "success_rate",
    "average_page_time",
}
EXPECTED_TOP_FIELDS = {
    "success",
    "results",
    "unique_results",
    "time_taken",
    "total_results",
    "performance_metrics",
}

COOLDOWN = 5  # seconds between requests to avoid rate limiting


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
    resp = http_client.post(
        "/inserate-by-url", json={"url": LARGE_RESULT_URL, "max_pages": 1}
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


@pytest.fixture(scope="session")
def two_page_response(http_client, single_page_response):
    time.sleep(COOLDOWN)
    resp = http_client.post(
        "/inserate-by-url", json={"url": LARGE_RESULT_URL, "max_pages": 2}
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


@pytest.fixture(scope="session")
def three_page_response(http_client, two_page_response):
    time.sleep(COOLDOWN)
    resp = http_client.post(
        "/inserate-by-url", json={"url": LARGE_RESULT_URL, "max_pages": 3}
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


@pytest.fixture(scope="session")
def four_page_response(http_client, three_page_response):
    time.sleep(COOLDOWN)
    resp = http_client.post(
        "/inserate-by-url", json={"url": LARGE_RESULT_URL, "max_pages": 4}
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


@pytest.fixture(scope="session")
def future_cutoff_response(http_client, four_page_response):
    """Fetch with a far-future min_publish_date — all listings are older → 0 results, stops after page 1."""
    time.sleep(COOLDOWN)
    resp = http_client.post(
        "/inserate-by-url",
        json={
            "url": LARGE_RESULT_URL,
            "max_pages": 2,
            "min_publish_date": "2099-01-01T00:00:00",
        },
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


@pytest.fixture(scope="session")
def past_cutoff_response(http_client, future_cutoff_response):
    """Fetch with a far-past min_publish_date — no listing is filtered, result count unchanged."""
    time.sleep(COOLDOWN)
    resp = http_client.post(
        "/inserate-by-url",
        json={
            "url": LARGE_RESULT_URL,
            "max_pages": 1,
            "min_publish_date": "2000-01-01T00:00:00",
        },
    )
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
    assert "total_results" in single_page_response, (
        "total_results field missing from response"
    )


def test_total_results_exceeds_100k(single_page_response):
    total = single_page_response.get("total_results", 0)
    assert total > 100_000, f"Expected total_results > 100,000, got {total}"


# ── Result counts per page ────────────────────────────────────────────────────


def test_single_page_returns_25_results(single_page_response):
    assert single_page_response["unique_results"] == 25, (
        f"Expected 25, got {single_page_response['unique_results']}"
    )
    assert len(single_page_response["results"]) == 25


def test_two_pages_returns_50_results(two_page_response):
    assert two_page_response["unique_results"] == 50, (
        f"Expected 50 results for 2 pages, got {two_page_response['unique_results']}"
    )
    assert len(two_page_response["results"]) == 50


def test_three_pages_returns_75_results(three_page_response):
    assert three_page_response["unique_results"] == 75, (
        f"Expected 75 results for 3 pages, got {three_page_response['unique_results']}"
    )
    assert len(three_page_response["results"]) == 75


def test_four_pages_returns_100_results(four_page_response):
    assert four_page_response["unique_results"] == 100, (
        f"Expected 100 results for 4 pages, got {four_page_response['unique_results']}"
    )
    assert len(four_page_response["results"]) == 100


# ── Metrics per page count ────────────────────────────────────────────────────


def test_single_page_metrics(single_page_response):
    pm = single_page_response["performance_metrics"]
    assert pm["pages_requested"] == 1
    assert pm["pages_successful"] == 1
    assert pm["success_rate"] == 100.0


def test_two_pages_metrics(two_page_response):
    pm = two_page_response["performance_metrics"]
    assert pm["pages_requested"] == 2
    assert pm["pages_successful"] == 2
    assert pm["success_rate"] == 100.0


def test_three_pages_metrics(three_page_response):
    pm = three_page_response["performance_metrics"]
    assert pm["pages_requested"] == 3
    assert pm["pages_successful"] == 3
    assert pm["success_rate"] == 100.0


def test_four_pages_metrics(four_page_response):
    pm = four_page_response["performance_metrics"]
    assert pm["pages_requested"] == 4
    assert pm["pages_successful"] == 4
    assert pm["success_rate"] == 100.0


# ── min_publish_date (datetime filtering) ─────────────────────────────────────


def test_future_cutoff_returns_no_results(future_cutoff_response):
    """A cutoff far in the future filters out every listing."""
    assert future_cutoff_response["unique_results"] == 0
    assert future_cutoff_response["results"] == []


def test_future_cutoff_stops_after_first_page(future_cutoff_response):
    """Early-stop fires on page 1 because all listings predate 2099 — no page 2 fetched."""
    assert future_cutoff_response["performance_metrics"]["pages_requested"] == 1


def test_past_cutoff_does_not_filter(past_cutoff_response):
    """A cutoff far in the past keeps every listing — result count same as no filter."""
    assert past_cutoff_response["unique_results"] == 25
    assert len(past_cutoff_response["results"]) == 25


def test_published_at_respects_cutoff(four_page_response):
    """All published_at values in a real response are valid ISO 8601 datetimes."""
    cutoff = datetime(2000, 1, 1)
    for item in four_page_response["results"]:
        pub = item.get("published_at")
        if pub is not None:
            assert datetime.fromisoformat(pub) >= cutoff, (
                f"published_at {pub!r} is older than cutoff {cutoff.isoformat()}"
            )
