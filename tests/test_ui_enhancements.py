"""Focused browser checks for wallet activity discovery and export."""
import os
import uuid

import pytest


def _key(headers):
    return {**headers, "Idempotency-Key": uuid.uuid4().hex}


def test_wallet_activity_search_filters_and_csv(service):
    sync_api = pytest.importorskip("playwright.sync_api")
    s = service(4)
    s.reset()
    alice, bob = s.login("alice"), s.login("bob")
    sent = s.http.post("/payments", headers=_key(alice), json={
        "to_handle": "bob", "amount": 1234, "note": "coffee run", "visibility": "public"
    })
    received = s.http.post("/payments", headers=_key(bob), json={
        "to_handle": "alice", "amount": 2500, "note": "dinner plan", "visibility": "public"
    })
    assert sent.status_code == received.status_code == 201

    exe = os.environ.get("POCKETFUL_CHROMIUM") or (
        "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
    )
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(s.base + "/login")
        page.get_by_test_id("login-email").fill("alice@example.com")
        page.get_by_test_id("login-password").fill("password-a")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("current-handle").wait_for()
        assert page.locator("#activity-search").is_visible(), page.locator("#activity-search").evaluate("(e) => ({outer: e.outerHTML, display: getComputedStyle(e).display, visibility: getComputedStyle(e).visibility, rect: e.getBoundingClientRect().toJSON(), parent: e.parentElement.outerHTML})")
        sync_api.expect(page.get_by_test_id("activity-item-" + sent.json()["payment_id"])).to_be_visible()
        sync_api.expect(page.get_by_test_id("activity-item-" + received.json()["payment_id"])).to_be_visible()

        page.get_by_test_id("activity-search").fill("coffee")
        sync_api.expect(page.get_by_test_id("activity-item-" + sent.json()["payment_id"])).to_be_visible()
        assert page.get_by_test_id("activity-item-" + received.json()["payment_id"]).count() == 0

        page.get_by_test_id("activity-search").fill("")
        page.get_by_label("Filter activity").select_option("sent")
        sync_api.expect(page.get_by_test_id("activity-item-" + sent.json()["payment_id"])).to_be_visible()
        assert page.get_by_test_id("activity-item-" + received.json()["payment_id"]).count() == 0
        page.get_by_label("Filter activity").select_option("received")
        sync_api.expect(page.get_by_test_id("activity-item-" + received.json()["payment_id"])).to_be_visible()
        assert page.get_by_test_id("activity-item-" + sent.json()["payment_id"]).count() == 0

        page.get_by_label("Filter activity").select_option("all")
        with page.expect_download() as download_info:
            page.get_by_test_id("activity-export").click()
        download = download_info.value
        exported = open(download.path(), encoding="utf-8-sig").read()
        assert "coffee run" in exported and "dinner plan" in exported
        browser.close()
    assert errors == []

def test_split_preview_and_submit(service):
    sync_api = pytest.importorskip("playwright.sync_api")
    s = service(4)
    s.reset()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(s.base + "/login")
        page.get_by_test_id("login-email").fill("alice@example.com")
        page.get_by_test_id("login-password").fill("password-a")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("current-handle").wait_for()
        page.goto(s.base + "/split")
        page.get_by_test_id("split-amount").fill("10.01")
        page.get_by_test_id("split-handles").fill("bob,carol")
        sync_api.expect(page.get_by_test_id("split-share-bob")).to_have_text("5.01 EUR")
        sync_api.expect(page.get_by_test_id("split-share-carol")).to_have_text("5.00 EUR")
        page.get_by_test_id("split-submit").click()
        sync_api.expect(page.get_by_test_id("split-success")).to_contain_text("2 payment request(s) created")
        browser.close()


def test_statement_page_and_partial_refund(service):
    sync_api = pytest.importorskip("playwright.sync_api")
    s = service(4)
    s.reset()
    alice, bob = s.login("alice"), s.login("bob")
    payment = s.http.post("/payments", headers=_key(bob), json={
        "to_handle": "alice", "amount": 2500, "note": "shared dinner", "visibility": "public"
    })
    assert payment.status_code == 201
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(s.base + "/login")
        page.get_by_test_id("login-email").fill("alice@example.com")
        page.get_by_test_id("login-password").fill("password-a")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("current-handle").wait_for()
        page.goto(s.base + "/statement")
        sync_api.expect(page.locator("#statement-content")).to_be_visible()
        sync_api.expect(page.locator("#statement-count")).to_have_text("1")
        sync_api.expect(page.get_by_text("shared dinner")).to_be_visible()
        page.once("dialog", lambda dialog: dialog.accept("10.00"))
        page.locator("[data-refund]").click()
        sync_api.expect(page.locator("#statement-count")).to_have_text("2")
        assert s.http.get("/me", headers=alice).json()["balance"] == 11500
        assert s.http.get("/me", headers=bob).json()["balance"] == 3500
        browser.close()

def test_requests_search_status_summary_and_cancel(service):
    sync_api = pytest.importorskip("playwright.sync_api")
    s = service(4)
    s.reset()
    alice, bob = s.login("alice"), s.login("bob")
    outgoing = s.http.post("/requests", headers=_key(alice), json={
        "payer_handle": "bob", "amount": 1000, "note": "concert tickets"
    })
    incoming = s.http.post("/requests", headers=_key(bob), json={
        "payer_handle": "alice", "amount": 1200, "note": "dinner tab"
    })
    assert outgoing.status_code == incoming.status_code == 201
    outgoing_id = outgoing.json()["request_id"]
    incoming_id = incoming.json()["request_id"]

    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(s.base + "/login")
        page.get_by_test_id("login-email").fill("alice@example.com")
        page.get_by_test_id("login-password").fill("password-a")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("current-handle").wait_for()
        page.goto(s.base + "/requests")
        sync_api.expect(page.get_by_test_id("request-incoming-count")).to_have_text("1")
        sync_api.expect(page.get_by_test_id("request-outgoing-count")).to_have_text("1")
        sync_api.expect(page.get_by_test_id("request-item-" + outgoing_id)).to_be_visible()
        sync_api.expect(page.get_by_test_id("request-item-" + incoming_id)).to_be_visible()

        page.get_by_test_id("request-search").fill("concert")
        sync_api.expect(page.get_by_test_id("request-item-" + outgoing_id)).to_be_visible()
        assert page.get_by_test_id("request-item-" + incoming_id).count() == 0
        page.get_by_test_id("request-search").fill("")
        page.get_by_test_id("request-status").select_option("paid")
        sync_api.expect(page.get_by_test_id("empty-requests")).to_be_visible()
        page.get_by_test_id("request-status").select_option("all")
        page.get_by_test_id("request-cancel-" + outgoing_id).click()
        sync_api.expect(page.get_by_test_id("request-item-" + outgoing_id)).to_have_attribute("data-status", "cancelled")
        sync_api.expect(page.get_by_test_id("request-outgoing-count")).to_have_text("0")
        sync_api.expect(page.get_by_test_id("request-closed-count")).to_have_text("1")
        browser.close()

def test_request_form_creates_a_pending_request(service):
    sync_api = pytest.importorskip("playwright.sync_api")
    s = service(4)
    s.reset()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(s.base + "/login")
        page.get_by_test_id("login-email").fill("alice@example.com")
        page.get_by_test_id("login-password").fill("password-a")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("current-handle").wait_for()
        page.goto(s.base + "/requests")
        page.get_by_test_id("request-handle").fill("bob")
        page.get_by_test_id("request-amount").fill("4.50")
        page.get_by_test_id("request-note").fill("coffee split")
        page.get_by_test_id("request-submit").click()
        sync_api.expect(page.get_by_test_id("request-outgoing-count")).to_have_text("1")
        row = page.locator('[data-testid^="request-item-"]').first
        sync_api.expect(row).to_be_visible()
        request_testid = row.get_attribute("data-testid")
        request_id = request_testid.removeprefix("request-item-")
        sync_api.expect(page.get_by_test_id("request-amount-" + request_id)).to_have_text("4.50 EUR")
        browser.close()


def test_authorization_reserve_and_capture_in_browser(service):
    sync_api = pytest.importorskip("playwright.sync_api")
    s = service(4)
    s.reset()
    alice, bob = s.login("alice"), s.login("bob")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        alice_page = browser.new_page()
        alice_page.goto(s.base + "/login")
        alice_page.get_by_test_id("login-email").fill("alice@example.com")
        alice_page.get_by_test_id("login-password").fill("password-a")
        alice_page.get_by_test_id("login-submit").click()
        alice_page.get_by_test_id("current-handle").wait_for()
        alice_page.goto(s.base + "/authorizations")
        alice_page.get_by_test_id("authorize-handle").fill("bob")
        alice_page.get_by_test_id("authorize-amount").fill("20.00")
        alice_page.get_by_test_id("authorize-submit").click()
        sync_api.expect(alice_page.get_by_test_id("authorize-success")).to_be_visible()
        auth_row = alice_page.locator('[data-testid^="authorization-item-"]').first
        sync_api.expect(auth_row).to_be_visible()
        auth_id = auth_row.get_attribute("data-testid").removeprefix("authorization-item-")

        bob_page = browser.new_page()
        bob_page.goto(s.base + "/login")
        bob_page.get_by_test_id("login-email").fill("bob@example.com")
        bob_page.get_by_test_id("login-password").fill("password-b")
        bob_page.get_by_test_id("login-submit").click()
        bob_page.get_by_test_id("current-handle").wait_for()
        bob_page.goto(s.base + "/authorizations")
        bob_page.get_by_test_id("authorization-capture-" + auth_id).click()
        sync_api.expect(bob_page.get_by_test_id("authorization-item-" + auth_id)).to_have_attribute("data-status", "captured")
        assert s.http.get("/me", headers=alice).json()["balance"] == 8000
        assert s.http.get("/me", headers=bob).json()["balance"] == 7000
        browser.close()
