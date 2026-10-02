"""Stage gating: a folder must not serve later-stage API surfaces."""
from __future__ import annotations

import pytest

from conftest import STAGE, key

LATER = [
    (2, "POST", "/authorizations", {"to_handle": "bob", "amount": 1}),
    (2, "GET", "/authorizations", None),
    (3, "GET", "/statement", None),
    (3, "GET", "/payments/p_x/revisions", None),
    (3, "POST", "/payments/p_x/corrections", {}),
    (4, "POST", "/payments/p_x/refunds", {"amount": 1}),
    (4, "POST", "/correction-batches", {"corrections": []}),
]


@pytest.mark.parametrize("stage,method,path,body", LATER)
def test_later_stage_endpoints_absent(w, stage, method, path, body):
    if stage <= STAGE:
        pytest.skip("surface belongs to this stage")
    r = w.ada.req(method, path, json=body, key=key() if method == "POST" else None)
    assert r.status_code == 404, (r.status_code, r.text[:200])


def test_me_has_no_hold_fields_before_stage_2(w):
    if STAGE >= 2:
        pytest.skip("stage 2 adds the fields")
    me = w.ada.me()
    assert not {"available", "held", "total"} & set(me), me


def test_ui_not_served_before_stage_2(w):
    if STAGE >= 2:
        pytest.skip("stage 2 adds the UI")
    r = w.ada.get("/requests", headers={"Accept": "text/html"})
    assert "text/html" not in r.headers.get("content-type", ""), r.headers
