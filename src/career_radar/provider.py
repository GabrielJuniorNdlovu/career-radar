import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from career_radar.config import Settings
from career_radar.rules import safe_himalayas_url

BASE_URL = "https://himalayas.app"


class ProviderError(Exception):
    """Safe diagnostic: never carries URLs, credentials, or response bodies."""


class BudgetExceeded(ProviderError):
    pass


class HimalayasClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None, sleep=time.sleep):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout, follow_redirects=False
        )
        self.sleep = sleep
        self.requests = 0
        self.pages = 0

    def close(self):
        self.client.close()

    def request(self, path: str, params: dict | None = None) -> httpx.Response:
        headers = {"User-Agent": "CareerRadar/0.1 (personal job discovery)"}
        if self.settings.himalayas_api_key:
            headers["Authorization"] = (
                "Bearer " + self.settings.himalayas_api_key.get_secret_value()
            )
        for attempt in range(self.settings.max_retries + 1):
            if self.requests >= self.settings.max_requests:
                raise BudgetExceeded("request budget exhausted")
            if self.requests:
                self.sleep(self.settings.request_interval)
            self.requests += 1
            response = None
            try:
                response = self.client.get(
                    BASE_URL + path,
                    params=params,
                    headers=headers,
                    timeout=self.settings.request_timeout,
                )
            except httpx.TransportError:
                error = "provider transport failure"
            else:
                if response.status_code not in (429, 500, 502, 503, 504):
                    if response.status_code in (200, 404, 410):
                        return response
                    raise ProviderError(f"provider HTTP {response.status_code}")
                error = f"provider HTTP {response.status_code}"
            if attempt == self.settings.max_retries:
                raise ProviderError(error + "; retries exhausted")
            delay = min(2**attempt + random.random(), self.settings.max_retry_wait)
            if response is not None and "Retry-After" in response.headers:
                raw = response.headers["Retry-After"]
                try:
                    wait = float(raw)
                except ValueError:
                    try:
                        wait = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        wait = delay
                if wait > self.settings.max_retry_wait:
                    raise ProviderError("Retry-After exceeds configured wait budget")
                delay = max(delay, wait, 0)
            self.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def body(response: httpx.Response) -> dict:
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("provider returned malformed JSON") from None
        if not isinstance(data, dict):
            raise ProviderError("provider returned a non-object response")
        return data

    def search(self, query: dict):
        for page in range(1, self.settings.max_pages + 1):
            response = self.request("/jobs/api/search", {**query, "page": page})
            if response.status_code != 200:
                raise ProviderError(f"search HTTP {response.status_code}")
            data = self.body(response)
            jobs = data.get("jobs")
            if not isinstance(jobs, list):
                raise ProviderError("provider jobs must be an array")
            self.pages += 1
            if not jobs:
                return
            yield jobs
        raise BudgetExceeded("page budget exhausted")

    def verify(self, guid: str) -> tuple[str, dict | None]:
        safe_himalayas_url(guid)
        path = "/jobs/api" + urlsplit(guid).path
        response = self.request(path)
        if response.status_code == 410:
            return "closed", None
        if response.status_code == 404:
            return "unknown", None
        job = self.body(response).get("job")
        if not isinstance(job, dict):
            raise ProviderError("provider single-job response is malformed")
        if job.get("guid") != guid:
            raise ProviderError("provider single-job identity mismatch")
        return "open", job
