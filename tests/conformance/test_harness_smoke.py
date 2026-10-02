"""Smoke check that the conformance harness reaches a service (stage-1 §3.2, §3.3, §6)."""
import pytest

from support import ADA, assert_status

pytestmark = pytest.mark.stage(1)


def test_health_reset_and_login(anon, world):
    assert_status(anon.get("/health"), 200).json() == {"status": "ok"}
    me = assert_status(world.ada.get("/me"), 200).json()
    assert me["handle"] == "ada" and me["balance"] == ADA["balance"]
