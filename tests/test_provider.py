import httpx
import pytest

from career_radar.config import Settings
from career_radar.provider import BudgetExceeded, HimalayasClient, ProviderError


def adapter(handler, **kwargs):
    settings = Settings(_env_file=None, request_interval=0, **kwargs)
    waits = []
    return HimalayasClient(
        settings, httpx.Client(transport=httpx.MockTransport(handler)), sleep=waits.append
    ), waits


def test_short_pages_do_not_stop():
    pages = []

    def handler(request):
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(200, json={"jobs": [{"guid": "a"}] if page < 3 else []})

    client, _ = adapter(handler)
    assert len(list(client.search({"q": "data"}))) == 2
    assert pages == [1, 2, 3]


def test_429_retry_after():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "4"})
        return httpx.Response(200, json={"jobs": []})

    client, waits = adapter(handler)
    assert list(client.search({})) == []
    assert 4 in waits
    assert client.requests == 2


def test_retry_after_over_budget():
    client, waits = adapter(lambda r: httpx.Response(429, headers={"Retry-After": "86400"}))
    with pytest.raises(ProviderError, match="wait budget"):
        list(client.search({}))
    assert client.requests == 1


def test_timeout_bounded():
    def handler(request):
        raise httpx.ReadTimeout("credential-bearing URL must never escape")

    client, _ = adapter(handler, max_retries=2)
    with pytest.raises(ProviderError, match="transport failure"):
        list(client.search({}))
    assert client.requests == 3


@pytest.mark.parametrize("data", [{}, {"jobs": None}, [1]])
def test_malformed_response(data):
    client, _ = adapter(lambda r: httpx.Response(200, json=data))
    with pytest.raises(ProviderError):
        list(client.search({}))


def test_budget_counts_retries():
    client, _ = adapter(lambda r: httpx.Response(503), max_requests=1)
    with pytest.raises(BudgetExceeded):
        list(client.search({}))
    assert client.requests == 1


def test_page_budget():
    client, _ = adapter(lambda r: httpx.Response(200, json={"jobs": [1]}), max_pages=1)
    with pytest.raises(BudgetExceeded):
        list(client.search({}))


@pytest.mark.parametrize("code,state", [(410, "closed"), (404, "unknown")])
def test_status(code, state):
    client, _ = adapter(lambda r: httpx.Response(code))
    assert client.verify("https://himalayas.app/companies/example/jobs/job")[0] == state


def test_status_identity_mismatch():
    client, _ = adapter(lambda r: httpx.Response(200, json={"job": {"guid": "different"}}))
    with pytest.raises(ProviderError, match="identity mismatch"):
        client.verify("https://himalayas.app/companies/example/jobs/job")
