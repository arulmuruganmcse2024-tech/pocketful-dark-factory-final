"""Spec-derived black-box conformance suite (project-owned; NOT the official suite).

Every module declares the stage whose spec it checks: `pytestmark = pytest.mark.stage(N)`.

Which service a test talks to:
- default: the `stage-N/` folder matching the test's own stage;
- `POCKETFUL_FOLDER=M`: every test with stage <= M runs against `stage-M/` (cumulative
  check); tests above M are skipped.

How a folder's service is obtained:
- default: `uvicorn server:app` is started on a free port from
  `$POCKETFUL_IMPL_ROOT/stage-M` (POCKETFUL_IMPL_ROOT defaults to the repository root);
- `POCKETFUL_TARGET_M=http://host:port` uses an already running service (e.g. a container).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from support import ADA, BOB, CY, RESET_TIMEOUT, Api, assert_status, fixture, seeded_total

REPO = Path(__file__).resolve().parents[2]
IMPL_ROOT = Path(os.environ.get("POCKETFUL_IMPL_ROOT", REPO))


def pytest_configure(config):
    config.addinivalue_line("markers", "stage(n): the stage whose spec this test checks")
    config.addinivalue_line("markers", "interpretation(note): the spec is ambiguous here; the "
                            "test encodes the reading given in `note`")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Service:
    def __init__(self, folder: int):
        self.proc = None
        external = os.environ.get(f"POCKETFUL_TARGET_{folder}")
        if external:
            self.url = external.rstrip("/")
            return
        self.tmp = tempfile.TemporaryDirectory()
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}"
        env = {k: v for k, v in os.environ.items() if k != "POCKETFUL_STAGE"}
        env.update(POCKETFUL_DB=os.path.join(self.tmp.name, "state.db"), PYTHONDONTWRITEBYTECODE="1",
                   PORT=str(port))
        self.log = open(os.path.join(self.tmp.name, "service.log"), "w")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=IMPL_ROOT / f"stage-{folder}", env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if httpx.get(self.url + "/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        self.close()
        raise RuntimeError(f"stage-{folder} under {IMPL_ROOT} did not become healthy")

    def close(self) -> None:
        if self.proc is None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        else:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        self.log.close()
        self.tmp.cleanup()
        self.proc = None


_SERVICES: dict[int, _Service] = {}


def _service_url(folder: int) -> str:
    if folder not in _SERVICES:
        _SERVICES[folder] = _Service(folder)
    return _SERVICES[folder].url


def pytest_sessionfinish(session, exitstatus):
    for svc in _SERVICES.values():
        svc.close()
    _SERVICES.clear()


def _test_stage(request) -> int:
    marker = request.node.get_closest_marker("stage")
    if marker is None:
        raise pytest.UsageError(f"{request.node.nodeid} has no stage marker")
    return int(marker.args[0])


@pytest.fixture
def folder(request) -> int:
    """The stage folder this test runs against."""
    stage = _test_stage(request)
    chosen = os.environ.get("POCKETFUL_FOLDER")
    if chosen is None:
        return stage
    if stage > int(chosen):
        pytest.skip(f"stage-{stage} check is above folder stage-{chosen}")
    return int(chosen)


@pytest.fixture
def base_url(folder) -> str:
    return _service_url(folder)


@pytest.fixture
def previous_base_url(folder) -> str:
    """The preceding stage folder's service, for upgrade (export/import) checks."""
    if folder < 2:
        pytest.skip("stage-1 has no preceding stage")
    return _service_url(folder - 1)


@pytest.fixture
def reset(base_url):
    """POST /_test/reset. Asserts 204 unless raw=True."""
    def _reset(body: dict, *, raw: bool = False, url: str | None = None) -> httpx.Response:
        resp = httpx.post(f"{url or base_url}/_test/reset", json=body, timeout=RESET_TIMEOUT)
        if not raw:
            assert_status(resp, 204)
        return resp
    return _reset


@pytest.fixture
def api(base_url):
    made: list[Api] = []

    def _api(token: str | None = None, *, url: str | None = None) -> Api:
        client = Api(url or base_url, token=token)
        made.append(client)
        return client

    yield _api
    for client in made:
        client.close()


@pytest.fixture
def anon(api) -> Api:
    return api()


@pytest.fixture
def world(reset, api):
    """Ada 10000, Bob 2500, Cy 500 (EUR, minor_units 2), all signed in. No operators."""
    fx = fixture()
    reset(fx)
    return SimpleNamespace(fixture=fx, total=seeded_total(fx),
                           ada=api().authenticate(ADA["email"]),
                           bob=api().authenticate(BOB["email"]),
                           cy=api().authenticate(CY["email"]))


@pytest.fixture
def op_world(reset, api):
    """As `world`, but Ada is a settlement operator."""
    fx = fixture(settlement_operator_ids=["u_ada"])
    reset(fx)
    return SimpleNamespace(fixture=fx, total=seeded_total(fx),
                           ada=api().authenticate(ADA["email"]),
                           bob=api().authenticate(BOB["email"]),
                           cy=api().authenticate(CY["email"]))


@pytest.fixture
def balances():
    """Read every client's /me money fields."""
    def _read(*clients):
        out = []
        for c in clients:
            body = assert_status(c.get("/me"), 200).json()
            out.append(body["balance"])
        return out
    return _read


# ---- stage 2: the browser ---------------------------------------------------------

@pytest.fixture(scope="session")
def browser():
    from playwright import sync_api
    with sync_api.sync_playwright() as driver:
        instance = driver.chromium.launch(channel="chromium")
        yield instance
        instance.close()


@pytest.fixture
def page(browser, base_url):
    """A fresh browser context per test (no session leaks), 10 s default timeout."""
    context = browser.new_context(base_url=base_url)
    context.set_default_timeout(10_000)
    tab = context.new_page()
    yield tab
    context.close()


@pytest.fixture
def tid():
    return lambda name: f"[data-testid='{name}']"
