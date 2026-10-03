import itertools
import re
import uuid
from datetime import datetime, timezone

import httpx

RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")
_seq = itertools.count(1)


def parse_ts(s):
    assert isinstance(s, str) and RFC3339.match(s), f"not RFC3339 with offset: {s!r}"
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    assert dt.tzinfo is not None
    return dt


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def fixture(**extra):
    fx = {
        "currency": "EUR", "minor_units": 2,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
             "display_name": "Ada", "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
             "display_name": "Bob", "handle": "bob", "balance": 2500},
            {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
             "display_name": "Cy", "handle": "cy", "balance": 0},
        ],
        "settlement_operator_ids": ["u_cy"],
    }
    fx.update(extra)
    return fx


def key():
    return f"k-{uuid.uuid4().hex}-{next(_seq)}"


class Api:
    def __init__(self, base):
        self.c = httpx.Client(base_url=base, timeout=10)

    def reset(self, fx):
        r = self.c.post("/_test/reset", json=fx)
        assert r.status_code == 204, r.text
        return r

    def login(self, name, pw="correct horse"):
        r = self.c.post("/auth/login", json={"email": f"{name}@example.com", "password": pw})
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def req(self, method, path, tok=None, idem=None, **kw):
        h = dict(kw.pop("headers", {}))
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        if idem:
            h["Idempotency-Key"] = idem
        return self.c.request(method, path, headers=h, **kw)

    def get(self, path, tok, **kw):
        return self.req("GET", path, tok, **kw)

    def post(self, path, tok, body=None, idem="auto", **kw):
        if idem == "auto":
            idem = key()
        return self.req("POST", path, tok, idem, json=body if body is not None else {}, **kw)

    def pay(self, tok, to, amount, **extra):
        r = self.post("/payments", tok, {"to_handle": to, "amount": amount, **extra})
        assert r.status_code == 201, r.text
        return r.json()

    def me(self, tok, **params):
        r = self.get("/me", tok, params=params)
        assert r.status_code == 200, r.text
        return r.json()

    def export(self):
        r = self.c.get("/_test/export")
        assert r.status_code == 200, r.text
        return r.json()

    def import_(self, blob):
        return self.c.post("/_test/import", json=blob)
