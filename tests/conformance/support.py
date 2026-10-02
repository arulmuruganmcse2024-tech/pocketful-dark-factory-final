"""Helpers for the spec-derived conformance suite: an HTTP client, assertions and fixtures.

Everything here talks to the service over HTTP only, exactly as a judge would.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx

REQUEST_TIMEOUT = 5.0   # stage-1 §2: per-request timeout
RESET_TIMEOUT = 10.0    # stage-1 §2: POST /_test/reset gets 10 s

# ---- fixtures (stage-1 §4) --------------------------------------------------

CURRENCIES = {"EUR": 2, "JPY": 0, "BHD": 3}
PASSWORD = "correct horse"


def user(handle: str, balance: int, **extra) -> dict:
    body = {"id": f"u_{handle}", "email": f"{handle}@example.com", "password": PASSWORD,
            "display_name": handle.title(), "handle": handle, "balance": balance}
    body.update(extra)
    return body


ADA, BOB, CY = user("ada", 10_000), user("bob", 2_500), user("cy", 500)


def fixture(*, users: list[dict] | None = None, currency: str = "EUR", **extra) -> dict:
    """A reset body. Extra keys (payments, requests, authorizations, ...) pass through."""
    body = {"currency": currency, "minor_units": CURRENCIES[currency],
            "users": [dict(u) for u in (users or [ADA, BOB, CY])]}
    body.update(extra)
    return body


def seeded_total(fx: dict) -> int:
    return sum(u["balance"] for u in fx["users"])


def equal_split(amount: int, n: int) -> list[int]:
    """stage-1 §9: base = amount // n; the first amount % n participants get one more."""
    base, rem = divmod(amount, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def money(minor: int, minor_units: int = 2, currency: str = "EUR") -> str:
    """stage-2 formatted amount: `100.00 EUR`, `1200 JPY`, `1.500 BHD`."""
    if minor_units == 0:
        return f"{minor} {currency}"
    text = str(minor).rjust(minor_units + 1, "0")
    return f"{text[:-minor_units]}.{text[-minor_units:]} {currency}"


def new_key() -> str:
    return uuid.uuid4().hex


# ---- client -------------------------------------------------------------------

class Api:
    """httpx client carrying an optional bearer token. One per simulated client."""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = REQUEST_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, *, json: Any = None, content: bytes | str | None = None,
                idempotency_key: str | None = None, token: Any = ..., headers: dict | None = None,
                params: dict | None = None, timeout: float | None = None) -> httpx.Response:
        hdrs = dict(headers or {})
        effective = self.token if token is ... else token
        if effective is not None:
            hdrs.setdefault("Authorization", f"Bearer {effective}")
        if idempotency_key is not None:
            hdrs.setdefault("Idempotency-Key", idempotency_key)
        if json is not None or content is not None:
            hdrs.setdefault("Content-Type", "application/json")
        kwargs: dict = {"headers": hdrs}
        if json is not None:
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        if params is not None:
            kwargs["params"] = params
        if timeout is not None:
            kwargs["timeout"] = timeout
        return self._client.request(method, path, **kwargs)

    def get(self, path: str, **kw) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> httpx.Response:
        return self.request("POST", path, **kw)

    def signup(self, email: str, password: str, display_name: str) -> httpx.Response:
        return self.post("/auth/signup", json={"email": email, "password": password,
                                               "display_name": display_name}, token=None)

    def login(self, email: str, password: str = PASSWORD) -> httpx.Response:
        return self.post("/auth/login", json={"email": email, "password": password}, token=None)

    def authenticate(self, email: str, password: str = PASSWORD) -> "Api":
        resp = self.login(email, password)
        assert_status(resp, 200)
        self.token = resp.json()["token"]
        return self


# ---- assertions ---------------------------------------------------------------

def _describe(resp: httpx.Response) -> str:
    body = resp.text if len(resp.text) <= 400 else resp.text[:400] + "..."
    return f"{resp.request.method} {resp.request.url.path} -> {resp.status_code} {body!r}"


def assert_status(resp: httpx.Response, expected: int) -> httpx.Response:
    assert resp.status_code == expected, f"expected {expected}, got {resp.status_code}. {_describe(resp)}"
    return resp


def error_code(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        raise AssertionError(f"error body is not JSON. {_describe(resp)}") from None
    assert isinstance(body, dict) and isinstance(body.get("error"), dict), \
        f"error body must be {{'error': {{'code', 'message'}}}}. {_describe(resp)}"
    assert isinstance(body["error"].get("message"), str), f"error.message missing. {_describe(resp)}"
    return body["error"].get("code")


def assert_error(resp: httpx.Response, status: int, code: str) -> httpx.Response:
    actual = error_code(resp) if 400 <= resp.status_code < 600 else None
    assert resp.status_code == status and actual == code, \
        f"expected {status} {code}, got {resp.status_code} {actual}. {_describe(resp)}"
    return resp


# ---- concurrency --------------------------------------------------------------

def burst(fn: Callable[[int], Any], n: int, *, timeout: float = 60.0) -> list:
    """Call fn(i) for i in range(n), at most 50 in flight, each batch released together.

    A worker exception is returned in place of its result so one transport error
    cannot hide the other outcomes.
    """
    results: list = []
    for start in range(0, n, 50):
        size = min(50, n - start)
        barrier = threading.Barrier(size)

        def worker(i: int, offset: int = start):
            try:
                barrier.wait(timeout=timeout)
            except threading.BrokenBarrierError:
                pass
            try:
                return fn(offset + i)
            except Exception as exc:  # reported, not swallowed
                return exc

        with ThreadPoolExecutor(max_workers=size) as pool:
            results.extend(pool.map(worker, range(size)))
    return results


def tally(responses) -> dict[int, int]:
    counts: dict[int, int] = {}
    for r in responses:
        s = getattr(r, "status_code", 0)
        counts[s] = counts.get(s, 0) + 1
    return dict(sorted(counts.items()))


def assert_no_5xx(responses) -> None:
    bad = [r for r in responses if isinstance(r, Exception) or r.status_code >= 500]
    assert not bad, f"5xx or transport errors under load: {tally(responses)}; first: {bad[0]!r}"
