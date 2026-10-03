"""Historian checks. Base URL from POCKETFUL_BASE_URL; stage gate from POCKETFUL_STAGE."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

from hcommon import Api, fixture  # noqa: E402


def _base():
    return os.environ.get("POCKETFUL_BASE_URL", "").rstrip("/")


@pytest.fixture(scope="session", autouse=True)
def _need_base():
    if not _base():
        pytest.skip("POCKETFUL_BASE_URL not set", allow_module_level=True)


@pytest.fixture
def api():
    return Api(_base())


@pytest.fixture
def world(api):
    """Reset to the standard fixture; returns (api, tokens by name)."""
    api.reset(fixture())
    return api, {n: api.login(n) for n in ("ada", "bob", "cy")}
