"""Stage 4 adversarial probes (spec: pocketful/spec/stage-4.md): refunds and batches."""
from __future__ import annotations

import concurrent.futures as cf
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from conftest import BASE, Client, expect, fixture, key, login, reset, users

pytestmark = pytest.mark.stage(4)


def now():
    return datetime.now(timezone.utc)


def pay(c, to="bob", amount=100, **extra):
    r = c.post("/payments", json={"to_handle": to, "amount": amount, **extra}, key=key())
    expect(r, 201)
    return r.json()


def refund(c, pid, amount, k=None):
    return c.post(f"/payments/{pid}/refunds", json={"amount": amount}, key=k or key())


def item(pid, rev=1, amount=0, eff=None, reason="reversal", **extra):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount,
            "effective_at": eff or now().isoformat(), "reason": reason, **extra}


def batch(c, items, k=None):
    return c.post("/correction-batches", json={"corrections": items}, key=k or key())


def test_refund_shape_ceiling_and_replay(w):
    p = pay(w.ada, amount=1000, note="dinner 🍝", visibility="private")
    k = key()
    r1 = refund(w.bob, p["payment_id"], 400, k=k)
    expect(r1, 201)
    j = r1.json()
    assert (j["from_handle"], j["to_handle"], j["amount"]) == ("bob", "ada", 400)
    assert j["refund_of"] == p["payment_id"] and j["request_id"] is None
    assert j["authorization_id"] is None
    assert (j["note"], j["visibility"]) == ("dinner 🍝", "private")
    again = refund(w.bob, p["payment_id"], 400, k=k)
    expect(again, 200)
    assert again.json() == j
    expect(refund(w.bob, p["payment_id"], 601), 422, "refund_exceeds_payment")
    expect(refund(w.bob, p["payment_id"], 600), 201)
    expect(refund(w.bob, p["payment_id"], 1), 422, "refund_exceeds_payment")
    expect(refund(w.ada, j["payment_id"], 1), 422, "invalid_refund_target")
    expect(refund(w.ada, p["payment_id"], 1), 403, "forbidden")
    expect(refund(w.cy, p["payment_id"], 1), 403, "forbidden")
    expect(refund(w.bob, "p_nope", 1), 404, "not_found")
    for bad in (0, -1, 1.5, "1", True):
        expect(refund(w.bob, p["payment_id"], bad), 422, "validation_failed")
    assert w.ada.me()["balance"] == 10000 and w.bob.me()["balance"] == 2500
    assert pay(w.ada, amount=1)["refund_of"] is None


def test_refund_uses_available_and_never_reopens(w):
    rq = w.bob.post("/requests", json={"payer_handle": "ada", "amount": 2000}, key=key()).json()
    paid = w.ada.post(f"/requests/{rq['request_id']}/pay", json={}, key=key()).json()
    w.bob.post("/authorizations", json={"to_handle": "cy", "amount": 4000}, key=key())
    expect(refund(w.bob, paid["payment_id"], 600), 409, "insufficient_funds")
    expect(refund(w.bob, paid["payment_id"], 500), 201)
    reqs = {r["request_id"]: r for r in w.bob.get("/requests").json()["requests"]}
    assert reqs[rq["request_id"]]["status"] == "paid"


def test_refund_capture_and_settlement_member(w):
    a = w.ada.post("/authorizations", json={"to_handle": "bob", "amount": 1000}, key=key()).json()
    c = w.bob.post(f"/authorizations/{a['authorization_id']}/capture",
                   json={"amount": 300}, key=key()).json()
    expect(refund(w.bob, c["payment_id"], 300), 201)
    auths = w.ada.get("/authorizations").json()["authorizations"]
    assert auths[0]["status"] == "captured" and w.ada.me()["held"] == 0
    s = w.ada.post("/settlements", key=key(), json={"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 50}]}).json()
    m = s["payments"][0]
    r = refund(w.cy, m["payment_id"], 50)
    expect(r, 201)
    assert r.json()["settlement_id"] is None


def test_correction_vs_refund_interaction(w):
    p = pay(w.ada, amount=1000)
    expect(refund(w.bob, p["payment_id"], 600), 201)
    cr = lambda amt: w.ada.post(f"/payments/{p['payment_id']}/corrections", key=key(), json={
        "expected_revision": 1, "amount": amt, "effective_at": p["created_at"], "reason": "r"})
    expect(cr(599), 422, "refund_exceeds_payment")
    expect(cr(600), 201)
    expect(refund(w.bob, p["payment_id"], 1), 422, "refund_exceeds_payment")
    rf = [x for x in w.ada.get("/activity").json()["payments"] if x["refund_of"]][0]
    expect(w.bob.post(f"/payments/{rf['payment_id']}/corrections", key=key(), json={
        "expected_revision": 1, "amount": 1, "effective_at": rf["created_at"], "reason": "r"}),
        422, "linked_payment_immutable")


def test_concurrent_refunds_respect_ceiling(w):
    p = pay(w.ada, amount=1000)

    def go(_):
        return Client(w.bob.token).post(f"/payments/{p['payment_id']}/refunds",
                                        json={"amount": 300}, key=key())

    with cf.ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(go, range(8)))
    st = sorted(r.status_code for r in rs)
    assert st.count(201) == 3 and st.count(422) == 5, st


def _settled(w):
    s = w.ada.post("/settlements", key=key(), json={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 100},
        {"from_handle": "bob", "to_handle": "cy", "amount": 50}]})
    expect(s, 201)
    return s.json()


def test_batch_auth_and_shape(w):
    p = pay(w.ada, amount=100)
    expect(httpx.post(f"{BASE}/correction-batches", json={"corrections": [item(p["payment_id"])]},
                      headers={"Idempotency-Key": "k"}), 401, "unauthenticated")
    expect(batch(w.bob, [item(p["payment_id"])]), 403, "forbidden")
    expect(batch(w.ada, []), 422, "validation_failed")
    expect(batch(w.ada, [item(p["payment_id"]), item(p["payment_id"])]), 422, "validation_failed")
    many = [pay(w.ada, amount=1)["payment_id"] for _ in range(33)]
    expect(batch(w.ada, [item(x, amount=1) for x in many]), 422, "validation_failed")
    expect(batch(w.ada, [item(x, amount=1) for x in many[:32]]), 201)


def test_batch_settlement_completeness_and_offsets(w):
    s = _settled(w)
    m1, m2 = (x["payment_id"] for x in s["payments"])
    t = (now() - timedelta(minutes=1)).replace(microsecond=0)
    expect(batch(w.ada, [item(m1, eff=t.isoformat())]), 422, "incomplete_settlement")
    expect(batch(w.ada, [item(m1, eff=t.isoformat()),
                         item(m2, eff=(t - timedelta(seconds=1)).isoformat())]),
           422, "validation_failed")
    alt = t.astimezone(timezone(timedelta(hours=-7))).isoformat()
    k = key()
    r = batch(w.ada, [item(m1, eff=t.isoformat()), item(m2, eff=alt)], k=k)
    expect(r, 201)
    j = r.json()
    assert [x["payment_id"] for x in j["revisions"]] == [m1, m2]
    assert {x["recorded_at"] for x in j["revisions"]} == {j["recorded_at"]}
    assert all(x["correction_batch_id"] == j["correction_batch_id"] for x in j["revisions"])
    again = batch(w.ada, [item(m1, eff=t.isoformat()), item(m2, eff=alt)], k=k)
    expect(again, 200)
    assert again.json() == j
    assert w.bob.me()["balance"] == 2500 and w.cy.me()["balance"] == 500
    assert any(x["payment_id"] == m1 and x["amount"] == 100
               for x in w.cy.get("/activity").json()["payments"])


def test_batch_precedence(w):
    s = _settled(w)
    m1, m2 = (x["payment_id"] for x in s["payments"])
    p = pay(w.ada, amount=100)
    a = w.ada.post("/authorizations", json={"to_handle": "bob", "amount": 10}, key=key()).json()
    cap = w.bob.post(f"/authorizations/{a['authorization_id']}/capture", json={},
                     key=key()).json()
    # item errors in input order beat completeness and funds
    expect(batch(w.ada, [item("p_nope"), item(p["payment_id"], rev=9)]), 404, "not_found")
    expect(batch(w.ada, [item(p["payment_id"], rev=9), item("p_nope")]), 409, "stale_revision")
    expect(batch(w.ada, [item(m1), item(cap["payment_id"])]), 422, "linked_payment_immutable")
    # completeness beats funds
    expect(batch(w.ada, [item(m1, amount=10**9)]), 422, "incomplete_settlement")
    # funds: cy cannot cover reversing a 500 payment to her after she spent it
    q = pay(w.ada, to="cy", amount=500)
    pay(w.cy, to="bob", amount=1000)
    expect(batch(w.ada, [item(q["payment_id"])]), 409, "insufficient_funds")
    revs = w.ada.get(f"/payments/{q['payment_id']}/revisions").json()["revisions"]
    assert len(revs) == 1


def test_batch_combined_affordability(w):
    reset(fixture(users=users(("ada", 1000), ("bob", 0), ("cy", 0))))
    ada, bob = login("ada@example.com"), login("bob@example.com")
    p1 = pay(ada, to="bob", amount=500)
    p2 = pay(bob, to="ada", amount=500)
    # reversing p1 alone is unaffordable for bob (0); with p2 reversed too it nets to zero
    eff1, eff2 = p1["created_at"], p2["created_at"]
    expect(batch(ada, [item(p1["payment_id"], eff=eff1)]), 409, "insufficient_funds")
    expect(batch(ada, [item(p1["payment_id"], eff=eff1), item(p2["payment_id"], eff=eff2)]), 201)
    assert bob.me()["balance"] == 0 and ada.me()["balance"] == 1000


def test_batch_vs_single_correction_race(w):
    p = pay(w.ada, amount=100)
    body_item = item(p["payment_id"], amount=50, eff=p["created_at"])

    def single():
        return Client(w.ada.token).post(f"/payments/{p['payment_id']}/corrections", key=key(),
                                        json={k: v for k, v in body_item.items()
                                              if k != "payment_id"})

    def multi():
        return Client(w.ada.token).post("/correction-batches", key=key(),
                                        json={"corrections": [body_item]})

    with cf.ThreadPoolExecutor(2) as ex:
        a, b = ex.submit(single), ex.submit(multi)
    st = sorted([a.result().status_code, b.result().status_code])
    assert st == [201, 409], st


def test_old_snapshot_survives_batch(w):
    p = pay(w.ada, amount=100)
    s = w.ada.get("/statement").json()
    expect(batch(w.ada, [item(p["payment_id"], eff=p["created_at"])]), 201)
    old = w.ada.get("/statement", params={"snapshot": s["snapshot"]}).json()
    assert old["entries"][0]["delta"] == -100
    new = w.ada.get("/statement").json()
    assert new["entries"][0]["delta"] == 0 and new["entries"][0]["revision"] == 2
