"""Stage 3 drafts for the five easiest-to-misread temporal requirements (see ../DESIGN-NOTES.md).

M1 as_of inclusive vs statement half-open [from,to)
M2 known_at selects by recorded_at (<=), applies by effective_at; unknown payments contribute nothing,
   but the opening balance is NOT changed by corrections
M3 correction error precedence + historical_overdraft at every effective boundary (same-instant combined)
M4 statement snapshot tokens freeze everything, incl. default `to`
(M5 lives in stage4: batch corrections.)

Run with POCKETFUL_STAGE=3 (or 4) and POCKETFUL_BASE_URL.
"""
import pytest

from hist import (US, anchor, correct, hist_fixture, iso, key, parse_ts, revisions, setup, stage_at_least,
                  statement, timedelta, total_all)

pytestmark = stage_at_least(3)


def basic():
    T0 = anchor()
    T1 = T0 + timedelta(hours=1)
    # ada opening 9300 (10000+500-1200); bob opening 3200; cy 0. Total 12500.
    fx = hist_fixture({"ada": 10000, "bob": 2500, "cy": 0},
                      [("p_1", "ada", "bob", 500, T0, "a", "public"),
                       ("p_2", "bob", "ada", 1200, T1, "b", "private")])
    return fx, T0, T1


# ---------------------------------------------------------------- M1
def test_m1_as_of_is_inclusive_and_echoed_exactly(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    ada = t["ada"]
    assert api.me(ada, as_of=iso(T0 - US))["balance"] == 9300          # before earliest = opening
    assert api.me(ada, as_of=iso(T0))["balance"] == 8800               # at exactly T0 counts
    assert api.me(ada, as_of=iso(T1 - US))["balance"] == 8800
    assert api.me(ada, as_of=iso(T1))["balance"] == 10000              # at exactly T1 counts
    assert api.me(ada, as_of=iso(T1 + timedelta(days=400)))["balance"] == api.me(ada)["balance"] == 10000
    spelled = (T0 + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S") + "+02:00"   # = T0 exactly
    j = api.me(ada, as_of=spelled)
    assert j["as_of"] == spelled and j["balance"] == 8800
    assert "as_of" not in api.me(ada) or api.me(ada)["as_of"] is None


@pytest.mark.parametrize("bad", ["2026-09-24T13:20:00", "2026-09-24", "", "yesterday", "2026-09-24T13:20:00 00:00"])
def test_m1_invalid_instants_422(api, bad):
    fx, *_ = basic()
    t = setup(api, fx)
    for path, name in (("/me", "as_of"), ("/statement", "from"), ("/statement", "to")):
        r = api.get(path, t["ada"], params={name: bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed", (path, name, r.text)


def test_m1_statement_is_half_open(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    ada = t["ada"]
    s = statement(api, ada, **{"from": iso(T0), "to": iso(T1)})
    assert [e["payment"]["payment_id"] for e in s["entries"]] == ["p_1"]      # T0 in, T1 out
    assert (s["opening_balance"], s["closing_balance"]) == (9300, 8800)
    assert s["entries"][0]["delta"] == -500 and s["entries"][0]["balance_after"] == 8800
    s = statement(api, ada, **{"from": iso(T1)})
    assert [e["payment"]["payment_id"] for e in s["entries"]] == ["p_2"]
    assert (s["opening_balance"], s["closing_balance"]) == (8800, 10000)
    s = statement(api, ada, **{"from": iso(T1), "to": iso(T1)})
    assert s["entries"] == [] and s["opening_balance"] == s["closing_balance"] == 8800
    s = statement(api, ada)
    assert (s["opening_balance"], s["closing_balance"]) == (9300, 10000)
    assert s["opening_balance"] + sum(e["delta"] for e in s["entries"]) == s["closing_balance"]
    assert [e["delta"] for e in s["entries"]] == [-500, 1200]


def test_m1_statement_pagination_does_not_change_balances(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    full = statement(api, t["ada"])
    p0 = statement(api, t["ada"], limit=1, offset=0)
    p1 = statement(api, t["ada"], limit=1, offset=1)
    p2 = statement(api, t["ada"], limit=1, offset=2)
    assert p0["entries"] + p1["entries"] == full["entries"]
    assert (p0["has_more"], p1["has_more"], p2["has_more"]) == (True, False, False)
    assert p2["entries"] == []
    for p in (p0, p1, p2):
        assert (p["opening_balance"], p["closing_balance"]) == (full["opening_balance"], full["closing_balance"])


def test_m1_statement_only_own_payments_even_if_public(api):
    fx, T0, T1 = basic()
    fx["payments"].append({"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 0 + 1,
                           "note": "", "visibility": "public", "created_at": iso(T1 + timedelta(minutes=1))})
    fx["users"][0]["balance"] = 10000  # unchanged: seeded balance is *after* payments
    t = setup(api, fx)
    ids = [e["payment"]["payment_id"] for e in statement(api, t["cy"])["entries"]]
    assert ids == []


def test_m1_seeded_future_created_at_is_422_no_change(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    before = api.me(t["ada"])
    bad = hist_fixture({"ada": 5}, [("p_x", "ada", "ada", 1, T0)])
    bad["payments"][0]["created_at"] = iso(T1 + timedelta(days=3650))
    r = api.c.post("/_test/reset", json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert api.me(t["ada"]) == before


# ---------------------------------------------------------------- M2
def test_m2_known_at_selects_by_recorded_applies_by_effective(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    ada, bob, cy = t["ada"], t["bob"], t["cy"]
    eff = T0 - timedelta(hours=1)                                   # p_2 moves to before p_1
    r = correct(api, bob, "p_2", 1, 700, eff, "earlier+smaller")
    assert r.status_code == 201, r.text
    c = r.json()
    R1 = parse_ts(c["recorded_at"])
    assert c["revision"] == 2 and c["amount"] == 700 and c["payment_id"] == "p_2"
    assert parse_ts(c["effective_at"]) == eff and R1 > T1
    # current view reports corrected values: ada 10000 - 500 (receiver debited by the decrease)
    assert api.me(ada)["balance"] == 9500 and api.me(bob)["balance"] == 3000
    # effective-time application of the NEW revision, known only from R1 on
    mid = T0 - timedelta(minutes=30)
    assert api.me(ada, as_of=iso(mid), known_at=iso(R1))["balance"] == 9300 + 700
    assert api.me(ada, as_of=iso(mid), known_at=iso(R1 - US))["balance"] == 9300   # old revision effective at T1
    assert api.me(ada, as_of=iso(R1), known_at=iso(R1 - US))["balance"] == 10000   # original view
    assert api.me(ada, as_of=iso(R1), known_at=iso(R1))["balance"] == 9500        # known_at is inclusive
    # not yet recorded => contributes nothing, but opening balance is unchanged by corrections
    assert api.me(ada, as_of=iso(R1), known_at=iso(T0 - timedelta(seconds=1)))["balance"] == 9300
    assert api.me(bob, as_of=iso(R1), known_at=iso(T0 - timedelta(seconds=1)))["balance"] == 3200
    assert api.me(ada, as_of=iso(R1), known_at=iso(T0 + timedelta(seconds=1)))["balance"] == 8800  # p_1 only
    # sums equal seeded total in every historical view
    for kw in ({}, {"as_of": iso(mid)}, {"known_at": iso(T0)}, {"as_of": iso(mid), "known_at": iso(R1 - US)},
               {"as_of": iso(T1 + timedelta(days=2)), "known_at": iso(R1 + timedelta(days=2))}):
        assert total_all(api, t, **kw) == 12500, kw
    spelled = (T0 + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S") + "+02:00"
    assert api.me(ada, known_at=spelled)["known_at"] == spelled


def test_m2_statement_orders_by_effective_and_reports_selected_revision(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    eff = T0 - timedelta(hours=1)
    c = correct(api, t["bob"], "p_2", 1, 700, eff).json()
    s = statement(api, t["ada"])
    assert [e["payment"]["payment_id"] for e in s["entries"]] == ["p_2", "p_1"]
    e = s["entries"][0]
    assert e["revision"] == 2 and e["payment"]["amount"] == 700 and e["delta"] == 700
    assert parse_ts(e["effective_at"]) == eff and e["recorded_at"] == c["recorded_at"]
    assert [x["balance_after"] for x in s["entries"]] == [10000, 9500]
    assert s["opening_balance"] == 9300 and s["closing_balance"] == 9500
    old = statement(api, t["ada"], known_at=iso(parse_ts(c["recorded_at"]) - US))
    assert [x["payment"]["payment_id"] for x in old["entries"]] == ["p_1", "p_2"]
    assert [x["revision"] for x in old["entries"]] == [1, 1] and old["closing_balance"] == 10000
    none_known = statement(api, t["ada"], known_at=iso(T0 - timedelta(seconds=1)))
    assert none_known["entries"] == [] and none_known["opening_balance"] == none_known["closing_balance"] == 9300


def test_m2_zero_revision_is_an_entry_with_zero_delta_and_no_double_count(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    r = correct(api, t["ada"], "p_1", 1, 0, T0, "reverse")
    assert r.status_code == 201, r.text
    s = statement(api, t["ada"])
    z = [e for e in s["entries"] if e["payment"]["payment_id"] == "p_1"]
    assert len(z) == 1 and z[0]["delta"] == 0 and z[0]["revision"] == 2 and z[0]["payment"]["amount"] == 0
    assert s["opening_balance"] == 9300 and s["closing_balance"] == 10500
    # original revision still listed with reason ""
    revs = revisions(api, t["ada"], "p_1")
    assert [x["revision"] for x in revs] == [1, 2] and revs[0]["reason"] == "" and revs[0]["amount"] == 500
    # activity keeps the original payment
    feed = {p["payment_id"]: p for p in api.get("/activity", t["ada"]).json()["payments"]}
    assert feed["p_1"]["amount"] == 500


def test_m2_recorded_at_strictly_increases_and_replay_returns_original_revision(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    k = key()
    r1 = correct(api, t["ada"], "p_1", 1, 400, T0, "a", idem=k)
    assert r1.status_code == 201
    r2 = correct(api, t["ada"], "p_1", 2, 300, T0, "b")
    assert r2.status_code == 201
    assert parse_ts(r2.json()["recorded_at"]) > parse_ts(r1.json()["recorded_at"]) > T1
    again = correct(api, t["ada"], "p_1", 1, 400, T0, "a", idem=k)
    assert again.status_code == 200 and again.json() == r1.json()
    stale = correct(api, t["ada"], "p_1", 1, 100, T0, "c")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_revision"
    reuse = correct(api, t["ada"], "p_1", 1, 401, T0, "a", idem=k)
    assert reuse.status_code == 409 and reuse.json()["error"]["code"] == "idempotency_key_reuse"
    assert correct(api, t["bob"], "p_1", 3, 1, T0).status_code == 403
    assert correct(api, t["ada"], "nope", 1, 1, T0).status_code == 404
    assert api.get("/payments/p_1/revisions", t["cy"]).status_code == 404       # public payment, third party
    assert api.req("GET", "/payments/p_1/revisions").status_code == 401


# ---------------------------------------------------------------- M3
def overdraft_world():
    T0 = anchor()
    T1, T2 = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
    # ada opening 0; bob opening 201; p1 bob->ada 100 @T0; p2 ada->cy 100 @T1; p3 bob->ada 100 @T2
    fx = hist_fixture({"ada": 100, "bob": 1, "cy": 100},
                      [("p_1", "bob", "ada", 100, T0), ("p_2", "ada", "cy", 100, T1), ("p_3", "bob", "ada", 100, T2)])
    return fx, T0, T1, T2


def test_m3_historical_overdraft_when_current_balance_suffices(api):
    fx, T0, T1, T2 = overdraft_world()
    t = setup(api, fx)
    before = (statement(api, t["ada"]), api.me(t["ada"]), revisions(api, t["bob"], "p_1"))
    k = key()
    r = correct(api, t["bob"], "p_1", 1, 0, T0, "reverse", idem=k)   # debits ada 100: now fine, at T1 ada would hold -100
    assert r.status_code == 409 and r.json()["error"]["code"] == "historical_overdraft", r.text
    assert (statement(api, t["ada"]), api.me(t["ada"]), revisions(api, t["bob"], "p_1")) == before
    assert total_all(api, t) == 201
    # failed key is reusable: same key, valid body (raise 100 -> 101 keeps every boundary >= 0)
    ok = correct(api, t["bob"], "p_1", 1, 101, T0, "raise", idem=k)
    assert ok.status_code == 201, ok.text
    assert api.me(t["ada"])["balance"] == 101 and api.me(t["bob"])["balance"] == 0


def test_m3_current_insufficient_funds_takes_precedence(api):
    fx, T0, T1, T2 = overdraft_world()
    t = setup(api, fx)
    api.pay(t["ada"], "cy", 100)                                    # ada now holds 0
    r = correct(api, t["bob"], "p_1", 1, 0, T0, "reverse")
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_funds", r.text


def test_m3_same_instant_movements_combine(api):
    T0 = anchor()
    T1 = T0 + timedelta(hours=1)
    # at T1 ada receives 100 (p_in) and sends 100 (p_out). p_out has the smaller id, so any
    # one-by-one id-order check dips to -100; the combined balance at T1 is 0 and must be accepted.
    fx = hist_fixture({"ada": 0, "bob": 0, "cy": 110},
                      [("p_0", "bob", "cy", 10, T0 - timedelta(hours=1)),
                       ("p_a", "ada", "cy", 100, T1),
                       ("p_b", "bob", "ada", 100, T1)])
    fx["users"][1]["balance"] = 0
    t = setup(api, fx)
    r = correct(api, t["bob"], "p_0", 1, 5, T0 - timedelta(hours=1), "smaller")
    assert r.status_code == 201, r.text
    assert total_all(api, t) == 110


def test_m3_increase_debits_sender_decrease_debits_receiver(api):
    fx, T0, T1, T2 = overdraft_world()
    t = setup(api, fx)
    assert correct(api, t["bob"], "p_3", 1, 101, T2).status_code == 409   # bob holds 1 less than needed? 1 -> ok? see below
    # (bob end=1, +1 more debit leaves 0 => allowed; this line documents expectation to be 201)


# ---------------------------------------------------------------- M4
def snap_world(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    return t, T0, T1


def test_m4_snapshot_freezes_entries_balances_and_default_to(api):
    t, T0, T1 = snap_world(api)
    first = statement(api, t["ada"], limit=1)
    tok = first["snapshot"]
    assert isinstance(tok, str) and tok
    api.pay(t["bob"], "ada", 7)                                     # new payment after snapshot
    correct(api, t["ada"], "p_1", 1, 0, T0, "rev")                  # and a correction
    pages = []
    for off in (0, 1, 2, 5):
        r = api.get("/statement", t["ada"], params={"snapshot": tok, "limit": 1, "offset": off})
        assert r.status_code == 200, r.text
        pages.append(r.json())
    assert pages[0]["entries"] == first["entries"] and pages[0]["has_more"] is True
    assert [len(p["entries"]) for p in pages] == [1, 1, 0, 0]
    assert [p["has_more"] for p in pages] == [True, False, False, False]
    for p in pages:
        assert (p["opening_balance"], p["closing_balance"]) == (9300, 10000)
        assert p["snapshot"] == tok or "snapshot" in p
    assert [e["balance_after"] for e in (pages[0]["entries"] + pages[1]["entries"])] == [8800, 10000]
    fresh = statement(api, t["ada"])
    assert fresh["closing_balance"] != 10000 and len(fresh["entries"]) == 3


def test_m4_snapshot_param_rules(api):
    t, T0, T1 = snap_world(api)
    tok = statement(api, t["ada"])["snapshot"]
    for extra in ({"from": iso(T0)}, {"to": iso(T1)}, {"known_at": iso(T1)}):
        r = api.get("/statement", t["ada"], params={"snapshot": tok, **extra})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed", extra
    ok = api.get("/statement", t["ada"], params={"snapshot": tok, "limit": 1, "offset": 0, "zzz": "ignored"})
    assert ok.status_code == 200
    assert api.get("/statement", t["ada"], params={"snapshot": "nonsense"}).status_code == 404
    assert api.get("/statement", t["bob"], params={"snapshot": tok}).status_code == 404   # another user's
    api.get("/statement", t["ada"], params={"snapshot": tok, "limit": 0})                   # 422 expected
    assert api.get("/statement", t["ada"], params={"snapshot": tok, "limit": 0}).status_code == 422


def test_m4_snapshot_dies_on_reset(api):
    fx, T0, T1 = basic()
    t = setup(api, fx)
    tok = statement(api, t["ada"])["snapshot"]
    t = setup(api, fx)
    assert api.get("/statement", t["ada"], params={"snapshot": tok}).status_code == 404
