"""Stage 3 adversarial probes (spec: pocketful/spec/stage-3.md): history and corrections."""
from __future__ import annotations

import concurrent.futures as cf
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import pytest

from conftest import BASE, Client, expect, fixture, key, login, reset, users

pytestmark = pytest.mark.stage(3)


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def q(s):
    return quote(s, safe="")


def pay(c, to="bob", amount=100, **extra):
    r = c.post("/payments", json={"to_handle": to, "amount": amount, **extra}, key=key())
    expect(r, 201)
    return r.json()


def correct(c, pid, rev, amount, eff, reason="fix", k=None):
    return c.post(f"/payments/{pid}/corrections", key=k or key(),
                  json={"expected_revision": rev, "amount": amount,
                        "effective_at": eff, "reason": reason})


def stmt(c, **params):
    r = c.get("/statement", params=params)
    expect(r, 200)
    return r.json()


# ---- known_at without as_of ----

def test_me_known_at_alone_selects_old_revision(w):
    p = pay(w.ada, amount=1000)
    time.sleep(0.05)
    before = iso(now())
    time.sleep(0.05)
    expect(correct(w.ada, p["payment_id"], 1, 400, p["created_at"]), 201)
    assert w.ada.me()["balance"] == 9600
    old = w.ada.me(known_at=before)
    assert old["known_at"] == before
    assert old["balance"] == 9000, old


def test_statement_echoes_known_at(w):
    pay(w.ada, amount=100)
    k = iso(now() + timedelta(seconds=1))
    s = stmt(w.ada, known_at=k)
    assert s.get("known_at") == k, s.keys()


def test_me_as_of_echo_and_invalid_instants(w):
    t = "2026-09-24T13:20:00+02:00"
    assert w.ada.me(as_of=t)["as_of"] == t
    for bad in ("", "2026-09-24", "2026-09-24T13:20:00", "yesterday", "2026-13-01T00:00:00Z"):
        expect(w.ada.get("/me", params={"as_of": bad}), 422, "validation_failed")
        expect(w.ada.get("/me", params={"known_at": bad}), 422, "validation_failed")
        expect(w.ada.get("/statement", params={"from": bad}), 422, "validation_failed")


# ---- exact boundaries using a correction to pin an effective instant ----

def test_boundaries_inclusive_as_of_half_open_statement(w):
    p = pay(w.ada, amount=1000)
    t = now() - timedelta(minutes=5)
    T = iso(t.replace(microsecond=0))
    expect(correct(w.ada, p["payment_id"], 1, 1000, T), 201)
    assert w.ada.me(as_of=T)["balance"] == 9000
    assert w.ada.me(as_of=iso(t.replace(microsecond=0) - timedelta(microseconds=1)))["balance"] == 10000
    s_to = stmt(w.ada, to=T)
    assert s_to["entries"] == [] and s_to["closing_balance"] == 10000
    s_from = stmt(w.ada, **{"from": T})
    assert [e["payment"]["payment_id"] for e in s_from["entries"]] == [p["payment_id"]]
    assert s_from["opening_balance"] == 10000 and s_from["closing_balance"] == 9000
    # same instant, different offset spelling
    T2 = iso(t.replace(microsecond=0).astimezone(timezone(timedelta(hours=5, minutes=30))))
    assert w.ada.me(as_of=T2)["balance"] == 9000


@pytest.mark.interpretation("[from, to) with from == to is an empty window, not an error")
def test_empty_window_from_equals_to(w):
    pay(w.ada, amount=10)
    T = iso(now())
    s = stmt(w.ada, **{"from": T, "to": T})
    assert s["entries"] == [] and s["opening_balance"] == s["closing_balance"]


def test_statement_ordering_ties_by_payment_id_and_pagination_invariants(w):
    ps = [pay(w.ada, to=h, amount=a) for h, a in (("bob", 10), ("cy", 20), ("bob", 30), ("cy", 40))]
    T = iso((now() - timedelta(minutes=1)).replace(microsecond=0))
    for p in ps:
        expect(correct(w.ada, p["payment_id"], 1, p["amount"], T), 201)
    full = stmt(w.ada, limit=200)
    ids = [e["payment"]["payment_id"] for e in full["entries"]]
    assert ids == sorted(ids)
    assert full["opening_balance"] + sum(e["delta"] for e in full["entries"]) == full["closing_balance"]
    snap = full["snapshot"]
    pages = []
    for off in range(0, 5):
        r = w.ada.get("/statement", params={"snapshot": snap, "limit": 1, "offset": off})
        expect(r, 200)
        j = r.json()
        assert j["opening_balance"] == full["opening_balance"]
        assert j["closing_balance"] == full["closing_balance"]
        assert j["has_more"] == (off < 3)
        pages += j["entries"]
    assert pages == full["entries"]


def test_snapshot_rules(w):
    pay(w.ada, amount=100)
    s = stmt(w.ada, limit=1)
    tok = s["snapshot"]
    pay(w.ada, amount=200)
    again = w.ada.get("/statement", params={"snapshot": tok, "limit": 200}).json()
    assert len(again["entries"]) == 1
    for extra in ({"from": iso(now())}, {"to": iso(now())}, {"known_at": iso(now())}):
        expect(w.ada.get("/statement", params={"snapshot": tok, **extra}), 422, "validation_failed")
    expect(w.bob.get("/statement", params={"snapshot": tok}), 404, "not_found")
    expect(w.ada.get("/statement", params={"snapshot": "nope"}), 404, "not_found")
    reset(fixture())
    ada = login("ada@example.com")
    expect(ada.get("/statement", params={"snapshot": tok}), 404, "not_found")


def test_snapshot_frozen_under_concurrent_corrections(w):
    ps = [pay(w.ada, amount=100 + i) for i in range(5)]
    s = stmt(w.ada, limit=2)

    def go(p):
        return Client(w.ada.token).post(f"/payments/{p['payment_id']}/corrections", key=key(),
                                        json={"expected_revision": 1, "amount": 1,
                                              "effective_at": p["created_at"], "reason": "r"})

    with cf.ThreadPoolExecutor(5) as ex:
        list(ex.map(go, ps))
    later = w.ada.get("/statement", params={"snapshot": s["snapshot"], "limit": 200}).json()
    assert [e["payment"]["amount"] for e in later["entries"]] == [100, 101, 102, 103, 104]
    assert later["closing_balance"] == s["closing_balance"]


# ---- corrections ----

def test_correction_validation_and_permissions(w):
    p = pay(w.ada, amount=500)
    pid, eff = p["payment_id"], p["created_at"]
    bad = [({"expected_revision": 0, "amount": 1, "effective_at": eff, "reason": "r"}, 422),
           ({"expected_revision": 1, "amount": -1, "effective_at": eff, "reason": "r"}, 422),
           ({"expected_revision": 1, "amount": 1, "effective_at": eff, "reason": ""}, 422),
           ({"expected_revision": 1, "amount": 1, "effective_at": eff, "reason": "x" * 201}, 422),
           ({"expected_revision": 1, "amount": 1, "effective_at": iso(now() + timedelta(hours=1)),
             "reason": "r"}, 422),
           ({"expected_revision": 1, "amount": 1, "effective_at": "2026-01-01", "reason": "r"}, 422),
           ({"amount": 1, "effective_at": eff, "reason": "r"}, 422)]
    for body, st in bad:
        expect(w.ada.post(f"/payments/{pid}/corrections", json=body, key=key()), st,
               "validation_failed")
    expect(correct(w.bob, pid, 1, 1, eff), 403, "forbidden")
    expect(correct(w.ada, "p_nope", 1, 1, eff), 404, "not_found")
    expect(correct(w.ada, pid, 2, 1, eff), 409, "stale_revision")
    k = key()
    first = correct(w.ada, pid, 1, 0, eff, k=k)
    expect(first, 201)
    expect(correct(w.ada, pid, 2, 250, eff), 201)
    again = correct(w.ada, pid, 1, 0, eff, k=k)
    expect(again, 200)
    assert again.json() == first.json()
    revs = w.bob.get(f"/payments/{pid}/revisions").json()["revisions"]
    assert [r["revision"] for r in revs] == [1, 2, 3] and revs[0]["reason"] == ""
    rec = [datetime.fromisoformat(r["recorded_at"]) for r in revs]
    assert rec[0] < rec[1] < rec[2]
    expect(w.cy.get(f"/payments/{pid}/revisions"), 404, "not_found")
    expect(httpx.get(f"{BASE}/payments/{pid}/revisions"), 401, "unauthenticated")
    assert w.ada.me()["balance"] == 9750
    acts = {x["payment_id"]: x for x in w.cy.get("/activity").json()["payments"]}
    assert acts[pid]["amount"] == 500


def test_concurrent_corrections_same_revision_one_wins(w):
    p = pay(w.ada, amount=500)

    def go(i):
        return Client(w.ada.token).post(f"/payments/{p['payment_id']}/corrections", key=key(),
                                        json={"expected_revision": 1, "amount": 100 + i,
                                              "effective_at": p["created_at"], "reason": "r"})

    with cf.ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(go, range(8)))
    st = sorted(r.status_code for r in rs)
    assert st.count(201) == 1 and st.count(409) == 7, st
    total = sum(c.me()["balance"] for c in (w.ada, w.bob, w.cy))
    assert total == w.total


def test_historical_overdraft_vs_insufficient(w):
    reset(fixture(users=users(("ada", 1000), ("bob", 0), ("cy", 0)), settlement_operator_ids=[]))
    ada, bob, cy = (login(f"{h}@example.com") for h in ("ada", "bob", "cy"))
    p1 = pay(ada, to="bob", amount=500)
    time.sleep(0.01)
    pay(bob, to="cy", amount=500)
    time.sleep(0.01)
    # bob currently has 0: reversing p1 is currently unaffordable
    expect(correct(ada, p1["payment_id"], 1, 0, p1["created_at"]), 409, "insufficient_funds")
    pay(cy, to="bob", amount=500)
    # now bob has 500 but was at 0 between p2 and p3 -> history would go to -500
    r = correct(ada, p1["payment_id"], 1, 0, p1["created_at"])
    expect(r, 409, "historical_overdraft")
    assert len(ada.get(f"/payments/{p1['payment_id']}/revisions").json()["revisions"]) == 1
    # a correction replaces amount AND effective time: moving p1 to "now" still leaves
    # bob at -500 between p2 and p3, so this is also a historical overdraft
    expect(correct(ada, p1["payment_id"], 1, 0, iso(now())), 409, "historical_overdraft")
    assert bob.me()["balance"] == 500 and ada.me()["balance"] == 500


def test_correction_moves_payment_out_of_window(w):
    p = pay(w.ada, amount=300)
    start = iso(now() - timedelta(seconds=30))
    assert len(stmt(w.ada, **{"from": start})["entries"]) == 1
    expect(correct(w.ada, p["payment_id"], 1, 300, iso(now() - timedelta(days=2))), 201)
    s = stmt(w.ada, **{"from": start})
    assert s["entries"] == [] and s["opening_balance"] == 9700


def test_statement_entry_fields_and_selected_amount(w):
    p = pay(w.ada, amount=300)
    t0 = iso(now())
    time.sleep(0.02)
    expect(correct(w.ada, p["payment_id"], 1, 0, p["created_at"]), 201)
    e = stmt(w.ada)["entries"][0]
    assert e["revision"] == 2 and e["delta"] == 0 and e["payment"]["amount"] == 0
    assert {"effective_at", "recorded_at", "balance_after"} <= set(e)
    old = stmt(w.ada, known_at=t0)["entries"][0]
    assert old["revision"] == 1 and old["delta"] == -300
    assert stmt(w.ada, known_at=iso(now() - timedelta(days=1)))["entries"] == []


def test_settlement_members_and_captures_immutable(w):
    s = w.ada.post("/settlements", key=key(), json={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 5}]}).json()
    m = s["payments"][0]
    expect(correct(w.ada, m["payment_id"], 1, 1, m["created_at"]), 422, "linked_payment_immutable")
    rev = w.ada.get(f"/payments/{m['payment_id']}/revisions").json()["revisions"][0]
    assert rev["effective_at"] == rev["recorded_at"]
    assert datetime.fromisoformat(rev["recorded_at"]) == datetime.fromisoformat(s["committed_at"])
    a = w.ada.post("/authorizations", json={"to_handle": "bob", "amount": 50}, key=key()).json()
    c = w.bob.post(f"/authorizations/{a['authorization_id']}/capture", json={}, key=key()).json()
    expect(correct(w.ada, c["payment_id"], 1, 1, c["created_at"]), 422, "linked_payment_immutable")


def test_seeded_future_created_at_rejected_and_past_history(w):
    fut = iso(now() + timedelta(hours=1))
    fx = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                            "amount": 500, "created_at": fut}])
    expect(reset(fx, expect=None), 422, "validation_failed")
    past = "2026-01-01T00:00:00+00:00"
    reset(fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                             "amount": 500, "note": "", "visibility": "public",
                             "created_at": past}]))
    ada = login("ada@example.com")
    assert ada.me()["balance"] == 10000
    assert ada.me(as_of="2025-12-31T23:59:59+00:00")["balance"] == 10500
    assert ada.me(as_of=past)["balance"] == 10000
    s = stmt(ada)
    assert s["opening_balance"] == 10500 and s["closing_balance"] == 10000


def test_historical_holds_as_of(w):
    t_before = iso(now())
    time.sleep(0.02)
    a = w.ada.post("/authorizations", json={"to_handle": "bob", "amount": 3000}, key=key()).json()
    time.sleep(0.02)
    t_open = iso(now())
    time.sleep(0.02)
    expect(w.bob.post(f"/authorizations/{a['authorization_id']}/capture",
                      json={"amount": 1000, "final": False}, key=key()), 201)
    time.sleep(0.02)
    t_part = iso(now())
    time.sleep(0.02)
    expect(w.ada.post(f"/authorizations/{a['authorization_id']}/void"), 200)
    m = w.ada.me(as_of=t_before)
    assert (m["total"], m["held"], m["available"]) == (10000, 0, 10000)
    m = w.ada.me(as_of=t_open)
    assert (m["total"], m["held"], m["available"]) == (10000, 3000, 7000)
    m = w.ada.me(as_of=t_part)
    assert (m["total"], m["held"], m["available"]) == (9000, 2000, 7000)
    m = w.ada.me()
    assert (m["total"], m["held"]) == (9000, 0)
    far = iso(now() + timedelta(hours=1))
    m = w.ada.me(as_of=far, known_at=t_part)
    assert (m["total"], m["held"]) == (9000, 0), m  # open at K, but expired by deadline
    lst = w.ada.get("/authorizations").json()["authorizations"][0]
    assert lst["closed_at"] is not None


def test_historical_overdraft_from_hold(w):
    reset(fixture(users=users(("ada", 1000), ("bob", 0), ("cy", 0)), settlement_operator_ids=[]))
    ada, bob = login("ada@example.com"), login("bob@example.com")
    p1 = pay(ada, to="bob", amount=600)
    time.sleep(0.02)
    a = bob.post("/authorizations", json={"to_handle": "cy", "amount": 600}, key=key()).json()
    time.sleep(0.02)
    expect(bob.post(f"/authorizations/{a['authorization_id']}/void"), 200)
    time.sleep(0.02)
    expect(ada.post("/payments", json={"to_handle": "bob", "amount": 1}, key=key()), 201)
    # Reversing p1 at its original time is currently affordable (bob has 601) and keeps
    # bob's total >= 0, but makes his available negative while the hold was open.
    expect(correct(ada, p1["payment_id"], 1, 0, p1["created_at"]), 409, "historical_overdraft")
