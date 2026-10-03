"""Stage 1 time/ordering checks (spec §3.4, §8 feed/requests, §11 settlements)."""
from hcommon import parse_ts


def test_created_at_rfc3339_on_every_record(world):
    api, t = world
    p = api.pay(t["ada"], "bob", 100)
    r = api.post("/requests", t["bob"], {"payer_handle": "ada", "amount": 50})
    assert r.status_code == 201
    sp = api.post("/splits", t["ada"], {"amount": 90, "participant_handles": ["ada", "bob", "cy"]})
    assert sp.status_code == 201
    st = api.post("/settlements", t["cy"], {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 5}]})
    assert st.status_code == 201, st.text
    parse_ts(p["created_at"])
    parse_ts(r.json()["created_at"])
    parse_ts(sp.json()["created_at"])
    for q in sp.json()["requests"]:
        parse_ts(q["created_at"])
    parse_ts(st.json()["committed_at"])
    for m in st.json()["payments"]:
        parse_ts(m["created_at"])
    for item in api.get("/activity", t["ada"]).json()["payments"]:
        parse_ts(item["created_at"])
    for item in api.get("/requests", t["ada"]).json()["requests"]:
        parse_ts(item["created_at"])


def test_activity_newest_first_never_increasing(world):
    api, t = world
    for i in range(12):
        api.pay(t["ada"], "bob", 1 + i)
    ts = [parse_ts(p["created_at"]) for p in api.get("/activity", t["ada"]).json()["payments"]]
    assert len(ts) == 12
    assert all(a >= b for a, b in zip(ts, ts[1:])), "activity not newest-first"


def test_activity_reverse_creation_when_timestamps_strictly_increase(world):
    """Builder design: strictly increasing server timestamps => no ties => exact reverse creation order."""
    api, t = world
    ids = [api.pay(t["ada"], "bob", 1 + i)["payment_id"] for i in range(15)]
    feed = api.get("/activity", t["ada"]).json()["payments"]
    ts = [p["created_at"] for p in feed]
    assert len(set(ts)) == len(ts), "equal created_at on distinct payments (design says strictly increasing)"
    assert [p["payment_id"] for p in feed] == ids[::-1]


def test_requests_newest_first_and_strict(world):
    api, t = world
    ids = []
    for i in range(12):
        r = api.post("/requests", t["bob"], {"payer_handle": "ada", "amount": 10 + i})
        ids.append(r.json()["request_id"])
    out = api.get("/requests", t["ada"]).json()["requests"]
    ts = [parse_ts(x["created_at"]) for x in out]
    assert all(a >= b for a, b in zip(ts, ts[1:]))
    assert [x["request_id"] for x in out] == ids[::-1]


def test_pagination_has_more_and_order_stable(world):
    api, t = world
    ids = [api.pay(t["ada"], "bob", 1)["payment_id"] for _ in range(5)]
    seen = []
    for off in (0, 2, 4):
        j = api.get("/activity", t["ada"], params={"limit": 2, "offset": off}).json()
        seen += [p["payment_id"] for p in j["payments"]]
        assert j["has_more"] == (off < 4)
    assert seen == ids[::-1]


def test_settlement_members_share_created_at_equal_committed_at(world):
    api, t = world
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                          {"from_handle": "bob", "to_handle": "cy", "amount": 50},
                          {"from_handle": "ada", "to_handle": "cy", "amount": 7}]}
    r = api.post("/settlements", t["cy"], body)
    assert r.status_code == 201, r.text
    j = r.json()
    assert len(j["payments"]) == 3
    for m in j["payments"]:
        assert m["created_at"] == j["committed_at"]
        assert m["settlement_id"] == j["settlement_id"]
        assert m["request_id"] is None
    feed = {p["payment_id"]: p for p in api.get("/activity", t["ada"]).json()["payments"]}
    for m in j["payments"]:
        if m["payment_id"] in feed:
            assert feed[m["payment_id"]]["created_at"] == j["committed_at"]
    later = api.pay(t["ada"], "bob", 1)
    assert parse_ts(later["created_at"]) > parse_ts(j["committed_at"])
    assert later["settlement_id"] is None


def test_timestamps_monotonic_across_record_kinds(world):
    api, t = world
    seq = [api.pay(t["ada"], "bob", 1)["created_at"],
           api.post("/requests", t["bob"], {"payer_handle": "ada", "amount": 5}).json()["created_at"],
           api.pay(t["bob"], "ada", 1)["created_at"],
           api.post("/settlements", t["cy"], {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}).json()["committed_at"],
           api.pay(t["ada"], "bob", 1)["created_at"]]
    dts = [parse_ts(s) for s in seq]
    assert all(a < b for a, b in zip(dts, dts[1:])), seq


def test_paying_request_creates_newer_payment_than_request(world):
    api, t = world
    rq = api.post("/requests", t["bob"], {"payer_handle": "ada", "amount": 5}).json()
    pay = api.post(f"/requests/{rq['request_id']}/pay", t["ada"], {})
    assert pay.status_code == 201
    assert parse_ts(pay.json()["created_at"]) > parse_ts(rq["created_at"])
    assert pay.json()["request_id"] == rq["request_id"]
