"""Red-team adversarial probes (project-owned; NOT the official suite).

Black-box only: every test talks HTTP to a running service.

    REDTEAM_BASE=http://127.0.0.1:8080 REDTEAM_STAGE=4 python -m pytest tests/redteam -q

Tests whose stage is above REDTEAM_STAGE are skipped. Tests marked
`interpretation` encode one reading of an ambiguous sentence; the reason names it.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import httpx
import pytest

BASE = os.environ.get("REDTEAM_BASE", "").rstrip("/")
STAGE = int(os.environ.get("REDTEAM_STAGE", "1"))

PW = "correct horse"


def users(*rows):
    return [{"id": f"u_{h}", "email": f"{h}@example.com", "password": PW,
             "display_name": h.title(), "handle": h, "balance": b} for h, b in rows]


def fixture(**extra):
    fx = {"currency": "EUR", "minor_units": 2,
          "users": users(("ada", 10000), ("bob", 2500), ("cy", 500)),
          "settlement_operator_ids": ["u_ada"]}
    fx.update(extra)
    return fx


def key():
    return uuid.uuid4().hex


class Client:
    def __init__(self, token=None):
        self.token = token
        self.http = httpx.Client(base_url=BASE, timeout=10)

    def req(self, method, path, *, json=None, content=None, key=None, token=..., headers=None,
            params=None):
        h = dict(headers or {})
        tok = self.token if token is ... else token
        if tok is not None:
            h["Authorization"] = f"Bearer {tok}"
        if key is not None:
            h["Idempotency-Key"] = key
        if json is not None or content is not None:
            h.setdefault("Content-Type", "application/json")
        return self.http.request(method, path, json=json, content=content, headers=h,
                                 params=params)

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, **kw):
        return self.req("POST", path, **kw)

    def me(self, **params):
        r = self.get("/me", params=params or None)
        assert r.status_code == 200, r.text
        return r.json()


def login(email, password=PW):
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=10)
    assert r.status_code == 200, r.text
    return Client(r.json()["token"])


def reset(fx, expect=204):
    r = httpx.post(f"{BASE}/_test/reset", json=fx, timeout=10)
    if expect is not None:
        assert r.status_code == expect, r.text
    return r


def code(resp):
    try:
        return resp.json()["error"]["code"]
    except Exception:
        return None


def expect(resp, status, err=None):
    assert resp.status_code == status, f"{resp.status_code} {resp.text[:300]}"
    if err:
        assert code(resp) == err, resp.text[:300]


def pytest_configure(config):
    config.addinivalue_line("markers", "stage(n): stage whose spec the probe checks")
    config.addinivalue_line("markers", "interpretation(note): ambiguous spec reading")


def pytest_collection_modifyitems(config, items):
    if not BASE:
        skip = pytest.mark.skip(reason="REDTEAM_BASE not set")
        for it in items:
            it.add_marker(skip)
        return
    for it in items:
        m = it.get_closest_marker("stage")
        if m and m.args[0] > STAGE:
            it.add_marker(pytest.mark.skip(reason=f"stage {m.args[0]} > {STAGE}"))


@pytest.fixture
def w():
    fx = fixture()
    reset(fx)
    return SimpleNamespace(fx=fx, total=sum(u["balance"] for u in fx["users"]),
                           ada=login("ada@example.com"), bob=login("bob@example.com"),
                           cy=login("cy@example.com"))
