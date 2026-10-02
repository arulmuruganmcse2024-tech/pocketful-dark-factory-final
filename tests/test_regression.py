"""Project-owned regression and adversarial tests (not the official suite)."""
import time, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def key(headers):
    return {**headers, "Idempotency-Key": uuid.uuid4().hex}


# ---------------------------------------------------------------- packaging

def test_stage_folders_share_one_implementation():
    cores = {(ROOT / f"stage-{n}" / "core.py").read_bytes() for n in range(1, 5)}
    servers = {(ROOT / f"stage-{n}" / "server.py").read_bytes() for n in range(1, 5)}
    assert len(cores) == 1 and len(servers) == 1


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_dockerfile_ships_stage_module_and_sets_stage(n):
    text = (ROOT / f"stage-{n}" / "Dockerfile").read_text()
    assert "stage.py" in text and f"POCKETFUL_STAGE={n}" in text
    assert f'"POCKETFUL_STAGE", "{n}"' in (ROOT / f"stage-{n}" / "stage.py").read_text()


# ---------------------------------------------------------------- gating

@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_stage_gating_defaults_to_folder_stage(service, stage):
    svc = service(stage)
    svc.reset()
    a = svc.login("alice")
    probes = {
        2: svc.http.post("/authorizations", headers=key(a), json={"to_handle": "bob", "amount": 1}),
        3: svc.http.get("/statement", headers=a),
        4: svc.http.post("/correction-batches", headers=key(a), json={"corrections": []}),
    }
    for introduced, resp in probes.items():
        if stage < introduced:
            assert resp.status_code == 404, (introduced, resp.text)
        else:
            assert resp.status_code != 404, (introduced, resp.text)
    reserve = 'href="/authorizations"' in svc.http.get("/", headers={"Accept": "text/html"}).text
    assert reserve == (stage >= 2)


# ---------------------------------------------------------------- money

def test_integral_float_amounts_are_stored_as_integers(service):
    svc = service(4); svc.reset()
    a, b = svc.login("alice"), svc.login("bob")
    auth = svc.http.post("/authorizations", headers=key(a), json={"to_handle": "bob", "amount": 500.0})
    assert auth.status_code == 201 and type(auth.json()["amount"]) is int
    cap = svc.http.post(f"/authorizations/{auth.json()['authorization_id']}/capture",
                        headers=key(b), json={"amount": 100.0, "final": False})
    assert cap.status_code == 201 and type(cap.json()["amount"]) is int
    pay = svc.http.post("/payments", headers=key(a), json={"to_handle": "bob", "amount": 300}).json()
    cor = svc.http.post(f"/payments/{pay['payment_id']}/corrections", headers=key(a), json={
        "expected_revision": 1, "amount": 250.0, "effective_at": pay["created_at"], "reason": "fix"})
    assert cor.status_code == 201 and type(cor.json()["amount"]) is int
    me = svc.http.get("/me", headers=a).json()
    assert all(type(me[f]) is int for f in ("balance", "available", "held"))


def test_fractional_amount_rejected_without_mutation(service):
    svc = service(1); svc.reset()
    a = svc.login("alice")
    r = svc.http.post("/payments", headers=key(a), json={"to_handle": "bob", "amount": 1.5})
    assert r.status_code == 422
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000


# ---------------------------------------------------------------- idempotency / concurrency

def test_concurrent_same_key_payment_debits_once(service):
    svc = service(1); svc.reset()
    a = svc.login("alice")
    h = key(a); body = {"to_handle": "bob", "amount": 7}
    with ThreadPoolExecutor(12) as ex:
        resps = list(ex.map(lambda _: httpx.post(svc.base + "/payments", headers=h, json=body, timeout=30), range(12)))
    assert all(r.status_code in (200, 201) for r in resps)
    assert len({r.json()["payment_id"] for r in resps}) == 1
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000 - 7


def test_same_key_different_body_conflicts(service):
    svc = service(1); svc.reset()
    a = svc.login("alice"); h = key(a)
    assert svc.http.post("/payments", headers=h, json={"to_handle": "bob", "amount": 5}).status_code == 201
    r = svc.http.post("/payments", headers=h, json={"to_handle": "bob", "amount": 6})
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_key_reuse"
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000 - 5


def test_concurrent_payments_never_overdraw(service):
    svc = service(1); svc.reset()
    b = svc.login("bob")  # balance 5000
    with ThreadPoolExecutor(16) as ex:
        codes = list(ex.map(lambda _: httpx.post(svc.base + "/payments", headers=key(b),
                                                 json={"to_handle": "alice", "amount": 400}, timeout=30).status_code,
                            range(20)))
    assert codes.count(201) == 12 and codes.count(409) == 8
    assert svc.http.get("/me", headers=b).json()["balance"] == 5000 - 12 * 400


# ---------------------------------------------------------------- ordering

def test_activity_is_chronological_across_timestamp_formats(service):
    svc = service(1)
    svc.reset(payments=[
        {"id": "p_early", "from_user_id": "u_alice", "to_user_id": "u_bob", "amount": 1, "created_at": "2026-01-01T00:00:00Z"},
        {"id": "p_later", "from_user_id": "u_alice", "to_user_id": "u_bob", "amount": 1, "created_at": "2026-01-01T00:00:00.500000+00:00"},
        {"id": "p_mid", "from_user_id": "u_alice", "to_user_id": "u_bob", "amount": 1, "created_at": "2026-01-01T01:00:00.250+01:00"},
    ])
    a = svc.login("alice")
    ids = [p["payment_id"] for p in svc.http.get("/activity", headers=a).json()["payments"]]
    assert ids == ["p_later", "p_mid", "p_early"]


# ---------------------------------------------------------------- holds

def test_historical_held_is_zero_after_expiry(service):
    svc = service(3); svc.reset(authorization_ttl_seconds=1)
    a = svc.login("alice")
    assert svc.http.post("/authorizations", headers=key(a), json={"to_handle": "bob", "amount": 700}).status_code == 201
    assert svc.http.get("/me", headers=a).json()["held"] == 700
    time.sleep(1.3)
    as_of = datetime.now(timezone.utc).isoformat()
    hist = svc.http.get("/me", headers=a, params={"as_of": as_of}).json()
    assert hist["held"] == 0 and hist["available"] == hist["balance"]
    assert svc.http.get("/me", headers=a).json()["held"] == 0


def test_capture_after_expiry_rejected(service):
    svc = service(2); svc.reset(authorization_ttl_seconds=1)
    a, b = svc.login("alice"), svc.login("bob")
    aid = svc.http.post("/authorizations", headers=key(a), json={"to_handle": "bob", "amount": 300}).json()["authorization_id"]
    time.sleep(1.2)
    r = svc.http.post(f"/authorizations/{aid}/capture", headers=key(b), json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "authorization_expired"
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000


def test_hold_reduces_available_for_payments(service):
    svc = service(2); svc.reset()
    b = svc.login("bob")
    assert svc.http.post("/authorizations", headers=key(b), json={"to_handle": "alice", "amount": 4000}).status_code == 201
    r = svc.http.post("/payments", headers=key(b), json={"to_handle": "alice", "amount": 1001})
    assert r.status_code == 409
    me = svc.http.get("/me", headers=b).json()
    assert (me["total"], me["held"], me["available"]) == (5000, 4000, 1000)


# ---------------------------------------------------------------- atomicity

def test_settlement_all_or_nothing(service):
    svc = service(1); svc.reset()
    c, a = svc.login("carol"), svc.login("alice")
    r = svc.http.post("/settlements", headers=key(c), json={"transfers": [
        {"from_handle": "alice", "to_handle": "bob", "amount": 100},
        {"from_handle": "bob", "to_handle": "nobody", "amount": 100}]})
    assert r.status_code == 404
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000
    assert svc.http.get("/activity", headers=a).json()["payments"] == []


def test_correction_batch_rejects_non_object_items(service):
    svc = service(4); svc.reset()
    c = svc.login("carol")
    for item in (None, 1, "payment_id", [1], True):
        r = svc.http.post("/correction-batches", headers=key(c), json={"corrections": [item]})
        assert r.status_code == 422, (item, r.text)


def test_correction_batch_stale_item_is_atomic(service):
    svc = service(4); svc.reset()
    a, c = svc.login("alice"), svc.login("carol")
    p1 = svc.http.post("/payments", headers=key(a), json={"to_handle": "bob", "amount": 100}).json()
    p2 = svc.http.post("/payments", headers=key(a), json={"to_handle": "bob", "amount": 200}).json()
    r = svc.http.post("/correction-batches", headers=key(c), json={"corrections": [
        {"payment_id": p1["payment_id"], "expected_revision": 1, "amount": 50, "effective_at": p1["created_at"], "reason": "r"},
        {"payment_id": p2["payment_id"], "expected_revision": 2, "amount": 50, "effective_at": p2["created_at"], "reason": "r"}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_revision"
    revs = svc.http.get(f"/payments/{p1['payment_id']}/revisions", headers=a).json()["revisions"]
    assert len(revs) == 1
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000 - 300


# ---------------------------------------------------------------- history / refunds

def test_statement_snapshot_is_immutable(service):
    svc = service(3); svc.reset()
    a = svc.login("alice")
    svc.http.post("/payments", headers=key(a), json={"to_handle": "bob", "amount": 100})
    first = svc.http.get("/statement", headers=a).json()
    svc.http.post("/payments", headers=key(a), json={"to_handle": "bob", "amount": 50})
    again = svc.http.get("/statement", headers=a, params={"snapshot": first["snapshot"]}).json()
    assert again == first
    fresh = svc.http.get("/statement", headers=a).json()
    assert fresh["closing_balance"] == first["closing_balance"] - 50


def test_statement_requests_do_not_lose_concurrent_payments(service):
    svc = service(3); svc.reset()
    a, b = svc.login("alice"), svc.login("bob")

    def pay(_):
        return httpx.post(svc.base + "/payments", headers=key(a), json={"to_handle": "bob", "amount": 1}, timeout=30).status_code

    def stmt(_):
        return httpx.get(svc.base + "/statement", headers=b, timeout=30).status_code

    with ThreadPoolExecutor(16) as ex:
        futs = [ex.submit(pay, i) for i in range(30)] + [ex.submit(stmt, i) for i in range(30)]
        codes = [f.result() for f in futs]
    assert codes[:30].count(201) == 30
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000 - 30


def test_cumulative_refunds_capped(service):
    svc = service(4); svc.reset()
    a, b = svc.login("alice"), svc.login("bob")
    pid = svc.http.post("/payments", headers=key(a), json={"to_handle": "bob", "amount": 100}).json()["payment_id"]
    assert svc.http.post(f"/payments/{pid}/refunds", headers=key(b), json={"amount": 60}).status_code == 201
    r = svc.http.post(f"/payments/{pid}/refunds", headers=key(b), json={"amount": 41})
    assert r.status_code == 422 and r.json()["error"]["code"] == "refund_exceeds_payment"
    assert svc.http.post(f"/payments/{pid}/refunds", headers=key(b), json={"amount": 40}).status_code == 201
    assert svc.http.get("/me", headers=a).json()["balance"] == 10000


# ---------------------------------------------------------------- browser UI

@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_ui_pay_form_submits_and_reports_errors(service, stage):
    sync_api = pytest.importorskip("playwright.sync_api")
    import os
    svc = service(stage); svc.reset()
    exe = os.environ.get("POCKETFUL_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(svc.base + "/login")
        page.get_by_test_id("login-email").fill("alice@example.com")
        page.get_by_test_id("login-password").fill("password-a")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("current-handle").wait_for()
        assert page.get_by_test_id("logout-button").count() == 1
        page.get_by_test_id("pay-handle").fill("bob")
        page.get_by_test_id("pay-amount").fill("12.34")
        page.get_by_test_id("pay-submit").click()
        sync_api.expect(page.get_by_test_id("wallet-balance")).to_have_text("87.66 EUR")
        page.get_by_test_id("pay-handle").fill("nobody")
        page.get_by_test_id("pay-submit").click()
        sync_api.expect(page.get_by_test_id("pay-error")).to_be_visible()
        browser.close()
    assert errors == []
