"""Stage 1 adversarial probes (spec: pocketful/spec/stage-1.md)."""
from __future__ import annotations

import concurrent.futures as cf
import time

import httpx
import pytest

from conftest import BASE, PW, Client, code, expect, fixture, key, login, reset, users

pytestmark = pytest.mark.stage(1)


def pay(c, to="bob", amount=100, k=None, **extra):
    return c.post("/payments", json={"to_handle": to, "amount": amount, **extra}, key=k or key())


# ---- §5 wrong JSON types: only amount/note/visibility are 422; others are 400 ----

def test_payment_to_handle_wrong_type_is_400(w):
    expect(w.ada.post("/payments", json={"to_handle": 7, "amount": 100}, key=key()),
           400, "malformed_request")


def test_request_payer_handle_wrong_type_is_400(w):
    expect(w.bob.post("/requests", json={"payer_handle": ["ada"], "amount": 100}, key=key()),
           400, "malformed_request")


def test_split_handles_wrong_type_is_400(w):
    expect(w.ada.post("/splits", json={"amount": 300, "participant_handles": "ada,bob"},
                      key=key()), 400, "malformed_request")


def test_signup_email_wrong_type_is_400(w):
    r = httpx.post(f"{BASE}/auth/signup",
                   json={"email": 5, "password": "longenough", "display_name": "X"})
    expect(r, 400, "malformed_request")


def test_login_password_wrong_type_is_400(w):
    r = httpx.post(f"{BASE}/auth/login", json={"email": "ada@example.com", "password": 123456789})
    expect(r, 400, "malformed_request")


@pytest.mark.parametrize("raw", ["[1,2]", '"str"', "null", "{nope", ""])
def test_non_object_body_is_400(w, raw):
    expect(w.ada.post("/payments", content=raw, key=key()), 400, "malformed_request")


# ---- §4 amounts ----

@pytest.mark.parametrize("amt", [1000.0, 1e3])
def test_integral_float_amount_accepted_and_returned_as_int(w, amt):
    r = pay(w.ada, amount=amt)
    expect(r, 201)
    assert r.json()["amount"] == 1000 and isinstance(r.json()["amount"], int)


@pytest.mark.parametrize("amt", [True, "100", 0, -1, 1.5, 1000000001, None, 1e400])
def test_bad_amounts_are_422(w, amt):
    if amt == 1e400:
        r = w.ada.post("/payments", content='{"to_handle":"bob","amount":1e400}', key=key())
    else:
        r = pay(w.ada, amount=amt)
    expect(r, 422, "validation_failed")


def test_note_null_is_422_and_emoji_roundtrip(w):
    expect(pay(w.ada, note=None), 422, "validation_failed")
    note = "  🍕 café́ <b>&amp;</b>\n" + "😀" * 10
    r = pay(w.ada, note=note)
    expect(r, 201)
    assert r.json()["note"] == note
    assert any(p["note"] == note for p in w.bob.get("/activity").json()["payments"])


def test_note_200_codepoints_ok_201_rejected(w):
    expect(pay(w.ada, note="😀" * 200), 201)
    expect(pay(w.ada, note="x" * 201), 422, "validation_failed")


# ---- §5/§7 key and query ranges ----

def test_key_length_bounds(w):
    expect(pay(w.ada, k="k" * 255), 201)
    expect(pay(w.ada, k="k" * 256), 422, "validation_failed")
    expect(w.ada.post("/payments", json={"to_handle": "bob", "amount": 1},
                      headers={"Idempotency-Key": ""}), 400, "missing_idempotency_key")


@pytest.mark.parametrize("q", ["limit=0", "limit=201", "limit=4.0", "limit=+4", "limit=1e2",
                               "limit=", "offset=-1", "offset=1.0", "offset=", "limit=-0"])
def test_bad_pagination_is_422(w, q):
    expect(w.ada.get(f"/activity?{q}"), 422, "validation_failed")
    expect(w.ada.get(f"/requests?{q}"), 422, "validation_failed")


def test_unknown_query_param_ignored_and_offset_beyond_end(w):
    r = w.ada.get("/activity?offset=999&foo=bar&limit=200")
    expect(r, 200)
    assert r.json() == {"payments": [], "has_more": False}


@pytest.mark.interpretation("auth is resolved before the idempotency header (§7 ordering)")
def test_no_token_and_no_key_is_401(w):
    r = httpx.post(f"{BASE}/payments", json={"to_handle": "bob", "amount": 1})
    expect(r, 401, "unauthenticated")


@pytest.mark.parametrize("hdr", ["Bearer", "bearer abc", "Token abc", "Bearer nope"])
def test_bad_tokens_are_401(w, hdr):
    r = httpx.get(f"{BASE}/me", headers={"Authorization": hdr})
    expect(r, 401, "unauthenticated")


# ---- §7 idempotency ----

def test_concurrent_same_key_moves_money_once(w):
    k = key()
    body = {"to_handle": "bob", "amount": 700}

    def go(_):
        c = Client(w.ada.token)
        return c.post("/payments", json=body, key=k)

    with cf.ThreadPoolExecutor(20) as ex:
        rs = list(ex.map(go, range(20)))
    statuses = sorted(r.status_code for r in rs)
    assert statuses.count(201) == 1 and statuses.count(200) == 19, statuses
    bodies = {r.text and str(sorted(r.json().items())) for r in rs}
    assert len(bodies) == 1
    assert w.ada.me()["balance"] == 10000 - 700
    assert w.bob.me()["balance"] == 2500 + 700


def test_same_key_different_path_is_not_replay(w):
    k = key()
    expect(pay(w.ada, k=k), 201)
    expect(w.ada.post("/requests", json={"payer_handle": "bob", "amount": 100}, key=k), 201)
    expect(w.ada.post("/splits", json={"amount": 100, "participant_handles": ["ada"]}, key=k), 201)


def test_same_key_other_user_independent(w):
    k = key()
    expect(pay(w.ada, k=k, amount=100), 201)
    expect(pay(w.bob, to="ada", k=k, amount=100), 201)


def test_key_reusable_after_4xx_failure(w):
    k = key()
    expect(pay(w.cy, to="ada", amount=600, k=k), 409, "insufficient_funds")
    expect(pay(w.ada, to="cy", amount=200), 201)
    r = pay(w.cy, to="ada", amount=600, k=k)
    expect(r, 201)
    expect(pay(w.cy, to="ada", amount=600, k=k), 200)
    assert w.cy.me()["balance"] == 100


def test_key_reuse_with_invalid_body_is_409(w):
    k = key()
    expect(pay(w.ada, amount=100, k=k), 201)
    expect(w.ada.post("/payments", json={"amount": "nope"}, key=k), 409, "idempotency_key_reuse")
    expect(w.ada.post("/payments", json={"to_handle": "ghost", "amount": 100}, key=k),
           409, "idempotency_key_reuse")


def test_replay_body_key_order_whitespace_insensitive(w):
    k = key()
    expect(w.ada.post("/payments", content='{"to_handle":"bob","amount":5}', key=k), 201)
    expect(w.ada.post("/payments", content='{ "amount" : 5 ,\n "to_handle":"bob" }', key=k), 200)


@pytest.mark.interpretation("same JSON value: 5 and 5.0 parse to the same number")
def test_replay_integral_float_same_value(w):
    k = key()
    expect(w.ada.post("/payments", content='{"to_handle":"bob","amount":5}', key=k), 201)
    r = w.ada.post("/payments", content='{"to_handle":"bob","amount":5.0}', key=k)
    assert r.status_code in (200, 409), r.text


def test_pay_request_replay_after_paid_and_body_variants(w):
    rq = w.bob.post("/requests", json={"payer_handle": "ada", "amount": 300}, key=key()).json()
    k = key()
    path = f"/requests/{rq['request_id']}/pay"
    first = w.ada.post(path, json={}, key=k)
    expect(first, 201)
    again = w.ada.post(path, json={}, key=k)
    expect(again, 200)
    assert again.json() == first.json()
    expect(w.ada.post(path, json={"visibility": "public"}, key=k), 409, "idempotency_key_reuse")
    expect(w.ada.post(path, json={}, key=key()), 409, "request_not_pending")
    assert w.ada.me()["balance"] == 9700


def test_concurrent_pay_same_request_different_keys_once(w):
    rq = w.bob.post("/requests", json={"payer_handle": "ada", "amount": 300}, key=key()).json()
    path = f"/requests/{rq['request_id']}/pay"

    def go(_):
        return Client(w.ada.token).post(path, json={}, key=key())

    with cf.ThreadPoolExecutor(10) as ex:
        rs = list(ex.map(go, range(10)))
    st = sorted(r.status_code for r in rs)
    assert st.count(201) == 1 and st.count(409) == 9, st
    assert w.ada.me()["balance"] == 9700


# ---- §8 requests / decline / cancel ----

def test_request_lifecycle_errors(w):
    rq = w.bob.post("/requests", json={"payer_handle": "ada", "amount": 99999999},
                    key=key()).json()
    rid = rq["request_id"]
    expect(w.ada.post(f"/requests/{rid}/pay", json={}, key=key()), 409, "insufficient_funds")
    expect(w.cy.post(f"/requests/{rid}/pay", json={}, key=key()), 403, "forbidden")
    expect(w.bob.post(f"/requests/{rid}/decline"), 403, "forbidden")
    expect(w.ada.post(f"/requests/{rid}/cancel"), 403, "forbidden")
    expect(w.ada.post(f"/requests/{rid}/decline"), 200)
    expect(w.ada.post(f"/requests/{rid}/decline"), 200)
    expect(w.bob.post(f"/requests/{rid}/cancel"), 409, "request_not_pending")
    expect(w.ada.post("/requests/nope/pay", json={}, key=key()), 404, "not_found")
    assert w.cy.get("/requests").json() == {"requests": [], "has_more": False}


def test_self_request_and_self_payment(w):
    expect(w.ada.post("/requests", json={"payer_handle": "ada", "amount": 1}, key=key()),
           422, "self_request")
    expect(pay(w.ada, to="ada"), 422, "self_payment")


def test_private_payment_feed_contract(w):
    r = pay(w.ada, to="bob", visibility="private")
    pid = r.json()["payment_id"]
    ids = lambda c: {p["payment_id"] for p in c.get("/activity?limit=200").json()["payments"]}
    assert pid in ids(w.ada) and pid in ids(w.bob) and pid not in ids(w.cy)


# ---- §9 splits ----

@pytest.mark.parametrize("amt,order,expected", [
    (1000, ["ada", "bob", "cy"], [334, 333, 333]),
    (1, ["cy", "bob", "ada"], [1, 0, 0]),
    (10, ["bob", "ada", "cy"], [4, 3, 3]),
])
def test_split_shares_and_zero_share_requests(w, amt, order, expected):
    r = w.ada.post("/splits", json={"amount": amt, "participant_handles": order}, key=key())
    expect(r, 201)
    j = r.json()
    assert [s["amount"] for s in j["shares"]] == expected
    assert [s["handle"] for s in j["shares"]] == order
    others = [(h, a) for h, a in zip(order, expected) if h != "ada"]
    assert [(q["payer_handle"], q["amount"]) for q in j["requests"]] == others


def test_split_duplicate_and_empty_and_unknown(w):
    expect(w.ada.post("/splits", json={"amount": 10, "participant_handles": []}, key=key()),
           422, "validation_failed")
    expect(w.ada.post("/splits", json={"amount": 10, "participant_handles": ["bob", "bob"]},
                      key=key()), 422, "validation_failed")
    expect(w.ada.post("/splits", json={"amount": 10, "participant_handles": ["bob", "zed"]},
                      key=key()), 404, "not_found")
    assert w.bob.get("/requests").json()["requests"] == []


# ---- §6 auth ----

def test_signup_derived_handle_and_handle_taken_creates_nothing(w):
    r = httpx.post(f"{BASE}/auth/signup", json={"email": "Zed.Q+x@Example.com",
                                                 "password": "longenough", "display_name": "Z"})
    expect(r, 201)
    z = Client(r.json()["token"])
    assert z.me()["handle"] == "zed_q_x" and z.me()["balance"] == 0
    r2 = httpx.post(f"{BASE}/auth/signup", json={"email": "ADA@other.org",
                                                  "password": "longenough", "display_name": "A"})
    expect(r2, 409, "handle_taken")
    r3 = httpx.post(f"{BASE}/auth/login", json={"email": "ADA@other.org", "password": "longenough"})
    expect(r3, 401, "unauthenticated")


def test_signup_long_local_part_truncated(w):
    r = httpx.post(f"{BASE}/auth/signup", json={"email": "a" * 30 + "@x.io",
                                                 "password": "longenough", "display_name": "L"})
    expect(r, 201)
    assert Client(r.json()["token"]).me()["handle"] == "a" * 20


def test_signup_validation(w):
    for body, st, c in [({"email": "noat", "password": "longenough", "display_name": "x"}, 422,
                         "validation_failed"),
                        ({"email": "q@x.io", "password": "short7!", "display_name": "x"}, 422,
                         "validation_failed"),
                        ({"email": "ada@example.com", "password": "longenough",
                          "display_name": "x"}, 409, "email_taken")]:
        expect(httpx.post(f"{BASE}/auth/signup", json=body), st, c)


# ---- §3/§4 reset ----

def test_failed_reset_changes_nothing(w):
    bad = fixture()
    bad["users"][0]["balance"] = -1
    expect(reset(bad, expect=None), 422, "validation_failed")
    assert w.ada.me()["balance"] == 10000  # old token still valid


def test_reset_seeded_history_not_replayed(w):
    fx = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                            "amount": 500, "note": "coffee", "visibility": "private"}],
                 requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                            "amount": 1200, "note": "taxi", "status": "pending"}])
    reset(fx)
    ada, bob, cy = (login(f"{h}@example.com") for h in ("ada", "bob", "cy"))
    assert ada.me()["balance"] == 10000 and bob.me()["balance"] == 2500
    assert [p["payment_id"] for p in bob.get("/activity").json()["payments"]] == ["p_1"]
    assert cy.get("/activity").json()["payments"] == []
    r = ada.post("/requests/rq_1/pay", json={}, key=key())
    expect(r, 201)
    assert r.json()["request_id"] == "rq_1"


@pytest.mark.interpretation("seeded history must remain nonnegative at reset")
def test_reset_seeded_payment_receiver_low_balance_rejected(w):
    fx = fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_cy",
                            "amount": 5000, "note": "", "visibility": "public"}])
    expect(reset(fx, expect=None), 422, "validation_failed")
    assert w.ada.me()["balance"] == 10000


def test_reset_jpy_and_bhd(w):
    for cur, mu in (("JPY", 0), ("BHD", 3)):
        reset(fixture(currency=cur, minor_units=mu))
        me = login("ada@example.com").me()
        assert me["currency"] == cur and me["minor_units"] == mu


# ---- §11 settlements ----

def test_settlement_net_affordability_zero_balance_cycle(w):
    reset(fixture(users=users(("ada", 100), ("bob", 0), ("cy", 0))))
    ada, bob = login("ada@example.com"), login("bob@example.com")
    r = ada.post("/settlements", key=key(), json={"transfers": [
        {"from_handle": "bob", "to_handle": "cy", "amount": 50},
        {"from_handle": "cy", "to_handle": "bob", "amount": 50}]})
    expect(r, 201)
    j = r.json()
    assert len(j["payments"]) == 2
    assert {p["created_at"] for p in j["payments"]} == {j["committed_at"]}
    assert all(p["settlement_id"] == j["settlement_id"] and p["request_id"] is None
               for p in j["payments"])
    assert bob.me()["balance"] == 0


def test_settlement_precedence_and_atomicity(w):
    t = lambda f, to, a, **x: {"from_handle": f, "to_handle": to, "amount": a, **x}
    cases = [
        ([t("cy", "bob", 999999), t("zed", "bob", 1)], 404, "not_found"),
        ([t("bob", "bob", 1), t("zed", "bob", 1)], 422, "self_payment"),
        ([t("zed", "bob", 1), t("bob", "bob", 1)], 404, "not_found"),
        ([t("ada", "bob", 1, visibility="secret"), t("zed", "bob", 1)], 422, "validation_failed"),
        ([t("cy", "bob", 501)], 409, "insufficient_funds"),
        ([], 422, "validation_failed"),
        ([t("ada", "bob", 1)] * 33, 422, "validation_failed"),
    ]
    for transfers, st, c in cases:
        expect(w.ada.post("/settlements", json={"transfers": transfers}, key=key()), st, c)
    assert w.bob.me()["balance"] == 2500 and w.cy.me()["balance"] == 500
    expect(w.ada.post("/settlements", json={"transfers": [t("ada", "bob", 1)] * 32}, key=key()),
           201)


def test_settlement_auth_rules_and_key_unclaimed_on_failure(w):
    body = {"transfers": [{"from_handle": "cy", "to_handle": "bob", "amount": 600}]}
    expect(httpx.post(f"{BASE}/settlements", json=body, headers={"Idempotency-Key": "x"}),
           401, "unauthenticated")
    expect(w.bob.post("/settlements", json=body, key=key()), 403, "forbidden")
    k = key()
    expect(w.ada.post("/settlements", json=body, key=k), 409, "insufficient_funds")
    expect(pay(w.ada, to="cy", amount=100), 201)
    first = w.ada.post("/settlements", json=body, key=k)
    expect(first, 201)
    again = w.ada.post("/settlements", json=body, key=k)
    expect(again, 200)
    assert again.json() == first.json()


def test_settlement_private_member_hidden_from_operator_feed(w):
    r = w.ada.post("/settlements", key=key(), json={"transfers": [
        {"from_handle": "bob", "to_handle": "cy", "amount": 5, "visibility": "private"}]})
    expect(r, 201)
    pid = r.json()["payments"][0]["payment_id"]
    assert pid not in {p["payment_id"] for p in w.ada.get("/activity").json()["payments"]}
    assert pid in {p["payment_id"] for p in w.cy.get("/activity").json()["payments"]}


# ---- conservation under concurrent load ----

def test_concurrent_overspend_conserves_and_no_5xx(w):
    def go(i):
        c = Client([w.ada, w.bob, w.cy][i % 3].token)
        to = ["bob", "cy", "ada"][i % 3]
        return c.post("/payments", json={"to_handle": to, "amount": 400}, key=key())

    with cf.ThreadPoolExecutor(50) as ex:
        rs = list(ex.map(go, range(150)))
    assert all(r.status_code in (201, 409) for r in rs), {r.status_code for r in rs}
    bals = [c.me()["balance"] for c in (w.ada, w.bob, w.cy)]
    assert min(bals) >= 0 and sum(bals) == w.total


def test_50_concurrent_logins_within_timeout(w):
    def go(_):
        t0 = time.time()
        r = httpx.post(f"{BASE}/auth/login",
                       json={"email": "ada@example.com", "password": "correct horse"}, timeout=5)
        return r.status_code, time.time() - t0

    with cf.ThreadPoolExecutor(50) as ex:
        rs = list(ex.map(go, range(50)))
    assert all(s == 200 for s, _ in rs)


def test_reset_with_many_users_is_fast(w):
    fx = fixture(users=users(*[(f"u{i}", 100) for i in range(40)]), settlement_operator_ids=[])
    t0 = time.time()
    reset(fx)
    assert time.time() - t0 < 10


# ---- §10 export / import ----

def test_export_import_roundtrip_tokens_replays_and_atomic_reject(w):
    k = key()
    first = pay(w.ada, amount=250, k=k, note="pre-export")
    expect(first, 201)
    failed = key()
    expect(pay(w.cy, to="ada", amount=99999, k=failed), 409)
    snap = httpx.get(f"{BASE}/_test/export").json()
    assert snap["track"] == "pocketful" and snap["format_version"] == 1
    expect(pay(w.ada, amount=1), 201)  # source write after export
    reset(fixture(users=users(("zz", 5)), settlement_operator_ids=[]))
    for bad in ({"track": "pocketful", "format_version": 2, "state": snap["state"]},
                {"track": "other", "format_version": 1, "state": snap["state"]},
                {"track": "pocketful", "format_version": 1},
                {"track": "pocketful", "format_version": 1, "state": {"nonsense": True}}):
        expect(httpx.post(f"{BASE}/_test/import", json=bad), 422, "validation_failed")
    assert login("zz@example.com").me()["balance"] == 5
    for _ in range(2):
        expect(httpx.post(f"{BASE}/_test/import", json=snap), 204)
    expect(httpx.post(f"{BASE}/auth/login", json={"email": "zz@example.com",
                                                   "password": PW}), 401, "unauthenticated")
    assert w.ada.me()["balance"] == 9750  # old token survives
    again = pay(w.ada, amount=250, k=k, note="pre-export")
    expect(again, 200)
    assert again.json() == first.json()
    expect(pay(w.cy, to="ada", amount=100, k=failed), 201)
    assert len(w.bob.get("/activity").json()["payments"]) == 2

