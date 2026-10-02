import os


def test_demo_fund_is_opt_in_idempotent_and_visible(service):
    os.environ["POCKETFUL_DEMO_LOGIN"] = "true"
    s = service(4)
    s.reset()
    headers = s.login("alice")
    headers = {**headers, "Idempotency-Key": "demo-credit-once"}
    first = s.http.post("/demo/fund", headers=headers, json={})
    assert first.status_code == 201, first.text
    assert first.json()["demo_only"] is True
    assert first.json()["credited"] == 2500
    replay = s.http.post("/demo/fund", headers=headers, json={})
    assert replay.status_code == 200, replay.text
    me = s.http.get("/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["balance"] == 12500
