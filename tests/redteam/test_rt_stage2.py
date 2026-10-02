"""Stage 2 adversarial probes (spec: pocketful/spec/stage-2.md): holds and captures."""
from __future__ import annotations

import concurrent.futures as cf
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from conftest import BASE, Client, expect, fixture, key, login, reset, users

pytestmark = pytest.mark.stage(2)


def auth(c, to="bob", amount=2000, **extra):
    return c.post("/authorizations", json={"to_handle": to, "amount": amount, **extra}, key=key())


def cap(c, aid, body=None, k=None):
    return c.post(f"/authorizations/{aid}/capture", json={} if body is None else body,
                  key=k or key())


def test_hold_fields_and_available_gates_every_debit(w):
    a = auth(w.ada, amount=9000, visibility="private")
    expect(a, 201)
    j = a.json()
    assert j["status"] == "open" and j["remaining_amount"] == 9000 and j["payment_ids"] == []
    created = datetime.fromisoformat(j["created_at"])
    assert datetime.fromisoformat(j["expires_at"]) - created == timedelta(seconds=600)
    me = w.ada.me()
    assert (me["balance"], me["total"], me["available"], me["held"]) == (10000, 10000, 1000, 9000)
    expect(w.ada.post("/payments", json={"to_handle": "bob", "amount": 1001}, key=key()),
           409, "insufficient_funds")
    expect(auth(w.ada, amount=1001), 409, "insufficient_funds")
    rq = w.bob.post("/requests", json={"payer_handle": "ada", "amount": 1001}, key=key()).json()
    expect(w.ada.post(f"/requests/{rq['request_id']}/pay", json={}, key=key()),
           409, "insufficient_funds")
    expect(w.ada.post("/settlements", key=key(), json={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 1001}]}), 409, "insufficient_funds")
    expect(w.ada.post("/settlements", key=key(), json={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 2000},
        {"from_handle": "bob", "to_handle": "ada", "amount": 1000}]}), 201)
    ids = {p["payment_id"] for p in w.ada.get("/activity?limit=200").json()["payments"]}
    assert j["authorization_id"] not in ids


def test_partial_captures_cumulative_and_remainder(w):
    aid = auth(w.ada, amount=2000).json()["authorization_id"]
    r1 = cap(w.bob, aid, {"amount": 700, "final": False})
    expect(r1, 201)
    p = r1.json()
    assert p["authorization_id"] == aid and p["request_id"] is None and p["amount"] == 700
    lst = w.ada.get("/authorizations").json()["authorizations"][0]
    assert lst["status"] == "open" and lst["remaining_amount"] == 1300
    assert lst["captured_amount"] == 700
    assert w.ada.me()["held"] == 1300 and w.ada.me()["total"] == 9300
    expect(cap(w.bob, aid, {"amount": 1301, "final": False}), 422, "capture_exceeds_authorization")
    expect(cap(w.bob, aid, {"amount": 0}), 422, "validation_failed")
    r2 = cap(w.bob, aid, {"amount": 300})  # final default true releases the remaining 1000
    expect(r2, 201)
    a = w.ada.get("/authorizations").json()["authorizations"][0]
    assert a["status"] == "captured" and a["captured_amount"] == 1000
    assert a["remaining_amount"] == 0 and a["payment_ids"] == [p["payment_id"], r2.json()["payment_id"]]
    assert a["payment_id"] == r2.json()["payment_id"]
    me = w.ada.me()
    assert (me["total"], me["held"], me["available"]) == (9000, 0, 9000)
    expect(cap(w.bob, aid, {"amount": 1}), 409, "authorization_not_open")
    expect(w.ada.post(f"/authorizations/{aid}/void"), 409, "authorization_not_open")


def test_nonfinal_capture_of_entire_remainder_closes(w):
    aid = auth(w.ada, amount=500).json()["authorization_id"]
    expect(cap(w.bob, aid, {"amount": 500, "final": False}), 201)
    a = w.ada.get("/authorizations").json()["authorizations"][0]
    assert a["status"] == "captured" and a["remaining_amount"] == 0


def test_capture_permissions_and_replay_body_identity(w):
    aid = auth(w.ada, amount=2000).json()["authorization_id"]
    expect(cap(w.ada, aid), 403, "forbidden")
    expect(cap(w.cy, aid), 403, "forbidden")
    expect(w.bob.post(f"/authorizations/{aid}/void"), 403, "forbidden")
    expect(w.cy.post(f"/authorizations/{aid}/void"), 403, "forbidden")
    expect(cap(w.bob, "a_nope"), 404, "not_found")
    expect(httpx.post(f"{BASE}/authorizations/{aid}/capture", json={},
                      headers={"Idempotency-Key": "z"}), 401, "unauthenticated")
    k = key()
    first = cap(w.bob, aid, {}, k=k)
    expect(first, 201)
    expect(cap(w.bob, aid, {"amount": 2000}, k=k), 409, "idempotency_key_reuse")
    again = cap(w.bob, aid, {}, k=k)
    expect(again, 200)
    assert again.json() == first.json()
    assert w.bob.me()["balance"] == 4500
    assert w.cy.get("/authorizations").json() == {"authorizations": [], "has_more": False}


def test_void_idempotent_and_releases(w):
    aid = auth(w.ada, amount=2000).json()["authorization_id"]
    v = w.ada.post(f"/authorizations/{aid}/void")
    expect(v, 200)
    assert v.json()["status"] == "voided" and v.json()["remaining_amount"] == 0
    expect(w.ada.post(f"/authorizations/{aid}/void"), 200)
    expect(cap(w.bob, aid), 409, "authorization_not_open")
    assert w.ada.me()["available"] == 10000


def test_clock_expiry_releases_without_any_write(w):
    reset(fixture(authorization_ttl_seconds=1))
    ada, bob = login("ada@example.com"), login("bob@example.com")
    aid = auth(ada, amount=4000).json()["authorization_id"]
    assert ada.me()["held"] == 4000
    time.sleep(1.3)
    me = ada.me()
    assert (me["held"], me["available"]) == (0, 10000)
    assert [a["authorization_id"] for a in
            ada.get("/authorizations?status=expired").json()["authorizations"]] == [aid]
    assert ada.get("/authorizations?status=open").json()["authorizations"] == []
    expect(cap(bob, aid), 409, "authorization_expired")
    expect(ada.post(f"/authorizations/{aid}/void"), 409, "authorization_not_open")


def test_partially_captured_then_expired_keeps_capture(w):
    reset(fixture(authorization_ttl_seconds=2))
    ada, bob = login("ada@example.com"), login("bob@example.com")
    aid = auth(ada, amount=1000).json()["authorization_id"]
    expect(cap(bob, aid, {"amount": 400, "final": False}), 201)
    time.sleep(2.3)
    a = ada.get("/authorizations").json()["authorizations"][0]
    assert a["status"] == "expired" and a["captured_amount"] == 400 and len(a["payment_ids"]) == 1
    me = ada.me()
    assert (me["total"], me["held"], me["available"]) == (9600, 0, 9600)


def test_seeded_holds(w):
    now = datetime.now(timezone.utc)
    seeded = lambda i, amt, st, exp: {"id": f"a_{i}", "from_user_id": "u_ada",
                                      "to_user_id": "u_bob", "amount": amt, "note": "dep",
                                      "visibility": "public", "status": st,
                                      "expires_at": exp.isoformat()}
    fx = fixture(authorizations=[seeded(1, 6000, "open", now + timedelta(hours=2)),
                                 seeded(2, 9000, "open", now - timedelta(hours=2)),
                                 seeded(3, 9000, "voided", now + timedelta(hours=2))])
    reset(fx)
    ada = login("ada@example.com")
    me = ada.me()
    assert (me["total"], me["held"], me["available"]) == (10000, 6000, 4000)
    st = {a["authorization_id"]: a["status"] for a in ada.get("/authorizations").json()["authorizations"]}
    assert st == {"a_1": "open", "a_2": "expired", "a_3": "voided"}
    bad = fixture(authorizations=[seeded(1, 6000, "open", now + timedelta(hours=2)),
                                  seeded(2, 4001, "open", now + timedelta(hours=3))])
    expect(reset(bad, expect=None), 422, "validation_failed")
    assert ada.me()["held"] == 6000  # failed reset changed nothing


@pytest.mark.parametrize("ttl", [0, -5, "600"])
def test_bad_ttl_rejected(w, ttl):
    expect(reset(fixture(authorization_ttl_seconds=ttl), expect=None), 422, "validation_failed")


def test_concurrent_nonfinal_captures_never_exceed(w):
    aid = auth(w.ada, amount=2000).json()["authorization_id"]

    def go(_):
        return Client(w.bob.token).post(f"/authorizations/{aid}/capture",
                                        json={"amount": 600, "final": False}, key=key())

    with cf.ThreadPoolExecutor(10) as ex:
        rs = list(ex.map(go, range(10)))
    ok = [r for r in rs if r.status_code == 201]
    assert len(ok) == 3, sorted(r.status_code for r in rs)
    assert all(r.status_code in (201, 422) for r in rs)
    me = w.ada.me()
    assert (me["total"], me["held"]) == (8200, 200)


def test_capture_void_race_is_serializable(w):
    for _ in range(8):
        reset(fixture())
        ada, bob = login("ada@example.com"), login("bob@example.com")
        aid = auth(ada, amount=1000).json()["authorization_id"]
        with cf.ThreadPoolExecutor(2) as ex:
            fc = ex.submit(lambda: Client(bob.token).post(
                f"/authorizations/{aid}/capture", json={}, key=key()))
            fv = ex.submit(lambda: Client(ada.token).post(f"/authorizations/{aid}/void"))
        c, v = fc.result(), fv.result()
        assert sorted([c.status_code, v.status_code]) in ([200, 409], [201, 409]), (c.text, v.text)
        me = ada.me()
        assert me["held"] == 0 and me["total"] == (9000 if c.status_code == 201 else 10000)


def test_html_and_json_share_routes(w):
    for path in ("/requests", "/authorizations"):
        h = w.ada.get(path, headers={"Accept": "text/html"})
        assert h.status_code == 200 and "text/html" in h.headers["content-type"]
        j = w.ada.get(path)
        assert j.status_code == 200 and "application/json" in j.headers["content-type"]
    for path in ("/", "/login", "/signup", "/split"):
        r = httpx.get(BASE + path, headers={"Accept": "text/html"})
        assert r.status_code == 200 and "text/html" in r.headers["content-type"], path
