"""Starts each stage folder's service in a subprocess for the regression suite.

These are project-owned regression/adversarial tests. They are NOT the official
Dark Factory participant tests and do not certify official conformance.
"""
import os, socket, subprocess, sys, tempfile, time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent

FIXTURE = {
    "currency": "EUR", "minor_units": 2,
    "users": [
        {"id": "u_alice", "handle": "alice", "email": "alice@example.com", "password": "password-a", "display_name": "Alice", "balance": 10000},
        {"id": "u_bob", "handle": "bob", "email": "bob@example.com", "password": "password-b", "display_name": "Bob", "balance": 5000},
        {"id": "u_carol", "handle": "carol", "email": "carol@example.com", "password": "password-c", "display_name": "Carol", "balance": 0},
    ],
    "settlement_operator_ids": ["u_carol"],
}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Service:
    def __init__(self, stage):
        self.stage = stage
        self.proc = None
        external = os.environ.get(f"POCKETFUL_TARGET_{stage}")
        if external:  # e.g. a running container: POCKETFUL_TARGET_1=http://127.0.0.1:8081
            self.base = external.rstrip("/")
            self.http = httpx.Client(base_url=self.base, timeout=30)
            return
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k != "POCKETFUL_STAGE"}
        env.update(POCKETFUL_DB=os.path.join(self.tmp.name, "state.db"), PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT / f"stage-{stage}", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if httpx.get(self.base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            self.close()
            raise RuntimeError(f"stage-{stage} did not start")
        self.http = httpx.Client(base_url=self.base, timeout=30)

    def reset(self, **extra):
        fx = {**FIXTURE, **extra}
        r = self.http.post("/_test/reset", json=fx)
        assert r.status_code == 204, r.text

    def login(self, name):
        r = self.http.post("/auth/login", json={"email": f"{name}@example.com", "password": f"password-{name[0]}"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    def close(self):
        if self.proc is None:
            return
        # On Windows, terminating the Python parent can leave a child console
        # process holding SQLite open long enough to break TemporaryDirectory
        # cleanup. Kill the process tree, then wait for the parent.
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
        self.tmp.cleanup()


_services = {}


@pytest.fixture(scope="session")
def service():
    def get(stage):
        if stage not in _services:
            _services[stage] = Service(stage)
        return _services[stage]
    yield get
    for s in _services.values():
        s.close()
    _services.clear()
