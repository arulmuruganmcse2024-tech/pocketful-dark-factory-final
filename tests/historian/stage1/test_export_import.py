"""Stage 1 export/import fidelity (spec §10, §11, §7)."""
import copy
import os
import threading

import pytest

from hcommon import Api, key, parse_ts

EMPTY = {"currency": "EUR", "minor_units": 2, "users": []}


def _scenario(api, t):
    k1 = key()
    body = {"to_handle": "bob", "amount": 1500, "note": "dîner \U0001F35D ", "visibility": "private"}
    r1 = api.req("POST", "/payments", t["ada"], k1, json=body)
    assert r1.status_code == 201
    rq = api.post("/requests", t["bob"], {"payer_handle": "ada", "amount": 300, "note": "taxi"})
    rid = rq.json()["request_id"]
    kp = key()
    rp = api.req("POST", f"/requests/{rid}/pay", t["ada"], kp, json={"visibility": "private"})
    assert rp.status_code == 201
    sp = api.post("/splits", t["ada"], {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]})
    assert sp.status_code == 201
    ks = key()
    sbody = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 11},
                           {"from_handle": "bob", "to_handle": "cy", "amount": 5}]}
    st = api.req("POST", "/settlements", t["cy"], ks, json=sbody)
    assert st.status_code == 201
    dec = api.post("/requests", t["cy"], {"payer_handle": "bob", "amount": 9}).json()["request_id"]
    assert api.post(f"/requests/{dec}/decline", t["bob"], {}, idem=None).status_code == 200
    return dict(k1=k1, body=body, r1=r1.json(), rid=rid, kp=kp, rp=rp.json(), sp=sp.json(),
                ks=ks, sbody=sbody, st=st.json())


def _snapshot(api, t):
    return {n: (api.get("/me", t[n]).json(), api.get("/activity", t[n]).json(),
                api.get("/requests", t[n]).json()) for n in t}


def test_export_shape_and_roundtrip_identity(world):
    api, t = world
    s = _scenario(api, t)
    before = _snapshot(api, t)
    blob = api.export()
    assert blob["track"] == "pocketful" and blob["format_version"] == 1 and isinstance(blob["state"], dict)
    api.reset({"currency": "JPY", "minor_units": 0, "users": []})
    assert api.c.post("/auth/login", json={"email": "ada@example.com", "password": "correct horse"}).status_code == 401
    assert api.import_(blob).status_code == 204
    assert _snapshot(api, t) == before  # old tokens still valid, identical JSON values
    r = api.req("POST", "/payments", t["ada"], s["k1"], json=s["body"])
    assert r.status_code == 200 and r.json() == s["r1"]
    r = api.req("POST", f"/requests/{s['rid']}/pay", t["ada"], s["kp"], json={"visibility": "private"})
    assert r.status_code == 200 and r.json() == s["rp"]
    r = api.req("POST", "/settlements", t["cy"], s["ks"], json=s["sbody"])
    assert r.status_code == 200 and r.json() == s["st"]
    r = api.req("POST", "/payments", t["ada"], s["k1"], json={**s["body"], "amount": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_key_reuse"
    assert _snapshot(api, t) == before
    assert api.login("ada")


def test_export_import_export_is_stable(world):
    api, t = world
    _scenario(api, t)
    a = api.export()
    assert api.import_(a).status_code == 204
    assert api.import_(a).status_code == 204
    assert api.export() == a


def test_new_ids_and_times_after_import_do_not_collide(world):
    api, t = world
    s = _scenario(api, t)
    api.import_(api.export())
    p = api.pay(t["ada"], "bob", 1)
    existing = {s["r1"]["payment_id"], s["rp"]["payment_id"]} | {m["payment_id"] for m in s["st"]["payments"]}
    assert p["payment_id"] not in existing
    assert parse_ts(p["created_at"]) > parse_ts(s["st"]["committed_at"])
    rq = api.post("/requests", t["bob"], {"payer_handle": "ada", "amount": 1}).json()
    assert rq["request_id"] not in {s["rid"]} | {r["request_id"] for r in s["sp"]["requests"]}


def test_failed_keys_remain_reusable_across_import(world):
    api, t = world
    k = key()
    bad = api.req("POST", "/payments", t["ada"], k, json={"to_handle": "bob", "amount": 10**8})
    assert bad.status_code == 409
    blob = api.export()
    api.reset(EMPTY)
    assert api.import_(blob).status_code == 204
    ok = api.req("POST", "/payments", t["ada"], k, json={"to_handle": "bob", "amount": 10})
    assert ok.status_code == 201, ok.text
    again = api.req("POST", "/payments", t["ada"], k, json={"to_handle": "bob", "amount": 10})
    assert again.status_code == 200 and again.json() == ok.json()


def test_failed_settlement_does_not_claim_key(world):
    api, t = world
    k = key()
    sb = {"transfers": [{"from_handle": "cy", "to_handle": "ada", "amount": 5}]}
    assert api.req("POST", "/settlements", t["cy"], k, json=sb).status_code == 409
    api.pay(t["ada"], "cy", 100)
    assert api.req("POST", "/settlements", t["cy"], k, json=sb).status_code == 201


def test_import_is_replacement_not_merge(world):
    api, t = world
    base = api.export()
    api.pay(t["ada"], "bob", 100)
    z = api.c.post("/auth/signup", json={"email": "zed@example.com", "password": "longenough1", "display_name": "Z"})
    assert z.status_code == 201
    ztok = z.json()["token"]
    assert api.import_(base).status_code == 204
    assert api.get("/activity", t["ada"]).json()["payments"] == []
    assert api.get("/me", ztok).status_code == 401
    assert api.c.post("/auth/login", json={"email": "zed@example.com", "password": "longenough1"}).status_code == 401
    assert api.me(t["ada"])["balance"] == 10000


@pytest.mark.parametrize("mut", [
    lambda b: b.pop("state"),
    lambda b: b.update(track="other"),
    lambda b: b.update(format_version=2),
    lambda b: b.update(state="notanobject"),
    lambda b: b.update(state={}),
    lambda b: b.pop("track"),
])
def test_invalid_import_422_no_change(world, mut):
    api, t = world
    api.pay(t["ada"], "bob", 100)
    before = api.export()
    blob = copy.deepcopy(before)
    mut(blob)
    r = api.import_(blob)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert api.export() == before


def test_unparseable_import_is_400_no_change(world):
    api, t = world
    before = api.export()
    r = api.c.post("/_test/import", content=b"{nope", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "malformed_request"
    assert api.export() == before


def test_corrupt_state_internals_422_no_change(world):
    api, t = world
    api.pay(t["ada"], "bob", 100)
    before = api.export()
    for mangle in (lambda s: {k: ("x" if isinstance(v, (list, dict)) else v) for k, v in s.items()},
                   lambda s: {k: None for k in s}):
        blob = copy.deepcopy(before)
        blob["state"] = mangle(blob["state"])
        r = api.import_(blob)
        assert r.status_code == 422, r.text
        assert api.export() == before


def test_export_is_snapshot(world):
    api, t = world
    api.pay(t["ada"], "bob", 100)
    blob = api.export()
    frozen = copy.deepcopy(blob)
    api.pay(t["ada"], "bob", 200)
    assert blob == frozen
    api.import_(blob)
    assert [p["amount"] for p in api.get("/activity", t["ada"]).json()["payments"]] == [100]


def test_export_with_concurrent_writes_is_consistent(world):
    api, t = world
    stop = threading.Event()

    def writer():
        a = Api(os.environ["POCKETFUL_BASE_URL"])
        while not stop.is_set():
            a.post("/payments", t["ada"], {"to_handle": "bob", "amount": 1})
            a.post("/payments", t["bob"], {"to_handle": "ada", "amount": 1})

    th = threading.Thread(target=writer)
    th.start()
    try:
        blobs = [api.export() for _ in range(15)]
    finally:
        stop.set()
        th.join()
    for b in blobs:
        assert api.import_(b).status_code == 204
        assert sum(api.me(t[n])["balance"] for n in ("ada", "bob", "cy")) == 12500
        feed = api.get("/activity", t["ada"], params={"limit": 200}).json()["payments"]
        net = sum(p["amount"] * (1 if p["to_handle"] == "ada" else -1) for p in feed)
        assert api.me(t["ada"])["balance"] == 10000 + net


def test_seeded_payments_timestamps_survive_roundtrip(api):
    fx = {"currency": "EUR", "minor_units": 2,
          "users": [{"id": "u_a", "email": "a@example.com", "password": "correct horse", "display_name": "A", "handle": "a", "balance": 100},
                    {"id": "u_b", "email": "b@example.com", "password": "correct horse", "display_name": "B", "handle": "b", "balance": 50}],
          "payments": [{"id": "p_1", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 5, "note": "x", "visibility": "public"}]}
    api.reset(fx)
    ta = api.login("a")
    before = api.get("/activity", ta).json()
    assert api.import_(api.export()).status_code == 204
    assert api.get("/activity", ta).json() == before
    assert api.me(ta)["balance"] == 100
