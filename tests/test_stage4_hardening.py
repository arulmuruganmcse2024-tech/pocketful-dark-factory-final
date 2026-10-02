
def _post(s, path, headers, body, key):
    h = dict(headers)
    h["Idempotency-Key"] = key
    return s.http.post(path, headers=h, json=body)


def _login(s, name):
    return s.login(name)


def test_historical_available_balance_guard(service):
    s = service(4)
    s.reset()
    ada = _login(s, "alice")
    r = _post(s, "/authorizations", ada, {"to_handle": "bob", "amount": 9000}, "hold-1")
    assert r.status_code == 201
    auth_id = r.json()["authorization_id"]
    r = _post(s, "/payments", ada, {"to_handle": "bob", "amount": 1000}, "pay-1")
    assert r.status_code == 201
    payment = r.json()
    r = s.http.post(f"/authorizations/{auth_id}/void", headers=ada)
    assert r.status_code == 200
    r = _post(
        s,
        f"/payments/{payment['payment_id']}/corrections",
        ada,
        {"expected_revision": 1, "amount": 2500,
         "effective_at": payment["created_at"], "reason": "history guard"},
        "corr-1",
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "historical_overdraft"
def test_single_correction_respects_refund_ceiling(service):
    s = service(4)
    s.reset()
    ada = _login(s, "alice")
    bob = _login(s, "bob")
    r = _post(s, "/payments", ada, {"to_handle": "bob", "amount": 1000}, "pay-2")
    assert r.status_code == 201
    payment = r.json()
    r = _post(s, f"/payments/{payment['payment_id']}/refunds",
              bob, {"amount": 400}, "refund-2")
    assert r.status_code == 201
    r = _post(
        s,
        f"/payments/{payment['payment_id']}/corrections",
        ada,
        {"expected_revision": 1, "amount": 300,
         "effective_at": payment["created_at"], "reason": "too low"},
        "corr-2",
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "refund_exceeds_payment"


def test_batch_correction_respects_refund_ceiling(service):
    s = service(4)
    s.reset()
    ada = _login(s, "alice")
    bob = _login(s, "bob")
    operator = _login(s, "carol")
    r = _post(s, "/payments", ada, {"to_handle": "bob", "amount": 1000}, "pay-3")
    assert r.status_code == 201
    payment = r.json()
    r = _post(s, f"/payments/{payment['payment_id']}/refunds",
              bob, {"amount": 400}, "refund-3")
    assert r.status_code == 201
    body = {"corrections": [{
        "payment_id": payment["payment_id"], "expected_revision": 1,
        "amount": 300, "effective_at": payment["created_at"],
        "reason": "too low batch"
    }]}
    r = _post(s, "/correction-batches", operator, body, "batch-3")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "refund_exceeds_payment"


def test_known_at_hides_later_void_release(service):
    s = service(4)
    s.reset()
    ada = _login(s, "alice")
    r = _post(s, "/authorizations", ada, {"to_handle": "bob", "amount": 5000}, "hold-4")
    assert r.status_code == 201
    auth = r.json()
    created = auth["created_at"]
    r = s.http.post(f"/authorizations/{auth['authorization_id']}/void", headers=ada)
    assert r.status_code == 200
    closed = r.json()["closed_at"]
    r = s.http.get(
        "/me",
        headers=ada,
        params={"as_of": closed, "known_at": created},
    )
    assert r.status_code == 200
    view = r.json()
    assert view["held"] == 5000
    assert view["available"] == view["balance"] - 5000
    r = s.http.get(
        "/me",
        headers=ada,
        params={"as_of": closed, "known_at": closed},
    )
    assert r.status_code == 200
    view = r.json()
    assert view["held"] == 0
    assert view["available"] == view["balance"]
