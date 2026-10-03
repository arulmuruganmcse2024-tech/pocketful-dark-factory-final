"""Helpers for stage 3/4 temporal drafts. Gate with POCKETFUL_STAGE (integer)."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from hcommon import Api, iso, key, parse_ts

US = timedelta(microseconds=1)


def stage_at_least(n):
    cur = os.environ.get("POCKETFUL_STAGE", "")
    ok = cur.isdigit() and int(cur) >= n
    return pytest.mark.skipif(not ok, reason=f"needs POCKETFUL_STAGE>={n} (got {cur or 'unset'})")


def anchor():
    """Whole-second anchor 6h in the past; seeded history must not be in the future."""
    return datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=6)


def hist_fixture(opening_end, payments, operators=("cy",), **extra):
    """opening_end: {handle: ending_balance}; payments: [(id, from, to, amount, created_at_dt, note, visibility)]."""
    fx = {"currency": "EUR", "minor_units": 2,
          "users": [{"id": f"u_{h}", "email": f"{h}@example.com", "password": "correct horse",
                     "display_name": h.title(), "handle": h, "balance": b} for h, b in opening_end.items()],
          "payments": [],
          "settlement_operator_ids": [f"u_{h}" for h in operators]}
    for p in payments:
        pid, frm, to, amt, at = p[:5]
        fx["payments"].append({"id": pid, "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": amt,
                               "note": p[5] if len(p) > 5 else "", "visibility": p[6] if len(p) > 6 else "public",
                               "created_at": iso(at)})
    fx.update(extra)
    return fx


def setup(api, fx):
    api.reset(fx)
    return {h["handle"]: api.login(h["handle"]) for h in fx["users"]}


def statement(api, tok, **params):
    r = api.get("/statement", tok, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def correct(api, tok, pid, rev, amount, effective_at, reason="fix", idem="auto"):
    return api.post(f"/payments/{pid}/corrections", tok,
                    {"expected_revision": rev, "amount": amount,
                     "effective_at": effective_at if isinstance(effective_at, str) else iso(effective_at),
                     "reason": reason}, idem=idem)


def revisions(api, tok, pid):
    r = api.get(f"/payments/{pid}/revisions", tok)
    assert r.status_code == 200, r.text
    return r.json()["revisions"]


def total_all(api, toks, **params):
    return sum(api.me(t, **params)["balance"] for t in toks.values())


__all__ = ["Api", "iso", "key", "parse_ts", "US", "stage_at_least", "anchor", "hist_fixture", "setup",
           "statement", "correct", "revisions", "total_all", "timedelta"]
