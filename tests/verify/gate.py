"""Independent release gate for one stage folder at one committed revision.

    python tests/verify/gate.py --stage 1 --sha <commit>

Everything is checked against a fresh clone of the commit, never the working tree:

  1. layout: stage-N/ has Dockerfile + RUN.md, no nested .git, no symlinks/submodules,
     Dockerfile COPY sources exist, CMD present and honours PORT
  2. hygiene: `git diff --check` (the commit's own diff and the whole stage-N tree),
     tracked junk (.env, *.db, *.log, __pycache__, *.pyc), credential grep,
     plus the official offline `python -m harness check`
  3. runtime: the non-Docker command from stage-N/RUN.md, started from the clone on a
     free port, must reach GET /health 200 {"status": "ok"}
  4. conformance: official suites 1..N against that one server, then suite N+1 as the
     overshoot probe (it must NOT fully pass), exact counts from each counts.json
  5. server log: no 5xx status lines and no tracebacks
  6. project-owned suites: pytest tests/ in the clone (tests/verify excluded)

Docker cannot run on this host (no WSL), so isolated mode is not exercised; the
Dockerfile is only checked statically. The summary says so.

Writes gate-summary.json and gate-summary.md under the output directory and exits 0
on ACCEPT, 1 on REJECT, 2 on a gate setup error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(os.environ.get("DF_HARNESS", r"C:\Users\arulm\FORGE\OFFICIAL_DARK_FACTORY"))
CHECKS = Path(os.environ.get("DF_CHECKS", r"C:\Users\arulm\FORGE\band-work\checks"))
PYTHON = Path(os.environ.get("DF_PYTHON", REPO / ".dev" / "venv" / "Scripts" / "python.exe"))
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

JUNK = re.compile(r"(^|/)(\.env(\..*)?|.*\.db(-.*)?|.*\.sqlite3?|.*\.log|__pycache__/.*|.*\.py[co])$")
ALLOWED_JUNK = re.compile(r"(^|/)\.env\.example$")
SECRETS = (
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9._\-]{16,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+(?=[A-Za-z0-9._\-]*\d)[A-Za-z0-9._\-]{20,}")),
    ("url-credentials", re.compile(r"""(?<=://)[^/\s:@"'\\]+:[^/\s@"'\\]+(?=@)""")),
    ("password-literal", re.compile(r"""(?i)\b(pass(word|wd)?|secret|api_?key|token)\b["']?\s*[:=]\s*["'][^"'\s]{6,}["']""")),
)
# Test fixtures, the spec-derived room transcript and docs carry demo passwords by design.
FIXTURE_PATHS = re.compile(r"(^|/)(tests?|fixtures?|mandates)/|^room\.json$|\.md$")
FIVE_XX = re.compile(r"\"\s+5\d\d\s|\bHTTP/1\.[01]\"?\s+5\d\d\b|\bstatus[=: ]+5\d\d\b")
RUN_LINE = re.compile(r"^(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(python3?|py|uvicorn|gunicorn|hypercorn|node|npm|go|java|cargo)\b")


def sh(cmd, cwd=None, timeout=600, env=None):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env=env, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Gate:
    def __init__(self, stage: int, sha: str, out: Path):
        self.stage, self.sha, self.out = stage, sha, out
        self.problems: list[str] = []   # each one is a REJECT reason
        self.notes: list[str] = []      # informational, not gating
        self.commands: list[str] = []
        self.data: dict = {"stage": stage, "requested_sha": sha}

    def fail(self, msg):
        self.problems.append(msg)
        print(f"  REJECT: {msg}")

    def note(self, msg):
        self.notes.append(msg)
        print(f"  note: {msg}")

    # 0. clone ---------------------------------------------------------------------
    def clone(self, tmp: Path) -> Path:
        dest = tmp / "clone"
        cmd = ["git", "clone", "--no-local", "--quiet", str(REPO), str(dest)]
        self.commands.append(" ".join(cmd))
        code, _, err = sh(cmd)
        if code:
            raise SystemExit(f"clone failed: {err}")
        code, _, err = sh(["git", "-c", "advice.detachedHead=false", "checkout", "--quiet", self.sha], cwd=dest)
        if code:
            raise SystemExit(f"{self.sha} is not a committed revision of {REPO}: {err.strip()}")
        _, full, _ = sh(["git", "rev-parse", "HEAD"], cwd=dest)
        self.data["sha"] = full.strip()
        _, subject, _ = sh(["git", "log", "-1", "--format=%s"], cwd=dest)
        self.data["subject"] = subject.strip()
        print(f"clone {self.data['sha']} {subject.strip()}")
        return dest

    # 1. layout --------------------------------------------------------------------
    def layout(self, clone: Path) -> Path:
        folder = clone / f"stage-{self.stage}"
        if not folder.is_dir():
            self.fail(f"stage-{self.stage}/ does not exist at this commit")
            return folder
        for name in ("Dockerfile", "RUN.md"):
            if not (folder / name).is_file():
                self.fail(f"stage-{self.stage}/{name} missing")
        for path in folder.rglob("*"):
            if path.name == ".git":
                self.fail(f"nested .git at {path.relative_to(clone)}")
            if path.is_symlink():
                self.fail(f"symlink at {path.relative_to(clone)}")
        _, index, _ = sh(["git", "ls-files", "-s", "--", f"stage-{self.stage}"], cwd=clone)
        for line in index.splitlines():
            mode, _, rest = line.partition(" ")
            if mode in ("120000", "160000"):
                self.fail(f"{'symlink' if mode == '120000' else 'submodule'} in index: {rest.split(chr(9))[-1]}")
        tracked = index.count("\n")
        self.data["stage_tracked_files"] = tracked
        self.dockerfile(folder)
        return folder

    def dockerfile(self, folder: Path):
        path = folder / "Dockerfile"
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        if not any(l.upper().startswith("FROM ") for l in lines):
            self.fail("Dockerfile has no FROM")
        cmd = [l for l in lines if l.upper().startswith(("CMD ", "ENTRYPOINT "))]
        if not cmd:
            self.fail("Dockerfile has no CMD or ENTRYPOINT")
        self.data["dockerfile_cmd"] = cmd
        for line in lines:
            if re.match(r"(?i)^(COPY|ADD)\s", line):
                parts = [p for p in shlex.split(line, posix=True)[1:] if not p.startswith("--")]
                for src in parts[:-1]:
                    if re.match(r"https?://", src):
                        self.fail(f"Dockerfile fetches {src} (outbound at build is allowed, but pin it in-repo)")
                    elif src not in (".", "./") and not any(folder.glob(src)):
                        self.fail(f"Dockerfile copies {src}, which is not in stage-{self.stage}/")
        if "PORT" not in text:
            self.note("Dockerfile never mentions PORT; the server must still read it at runtime")

    # 2. hygiene -------------------------------------------------------------------
    def hygiene(self, clone: Path):
        _, parent, _ = sh(["git", "rev-parse", "--verify", "--quiet", "HEAD^"], cwd=clone)
        base = parent.strip() or EMPTY_TREE
        for label, cmd in (("commit diff", ["git", "diff", "--check", base, "HEAD"]),
                           (f"stage-{self.stage} tree", ["git", "diff", "--check", EMPTY_TREE, "HEAD", "--", f"stage-{self.stage}"])):
            self.commands.append(" ".join(cmd))
            code, out, _ = sh(cmd, cwd=clone)
            self.data[f"diff_check_{label.split()[0]}"] = "clean" if code == 0 else out.strip()[:2000]
            if code:
                self.fail(f"git diff --check ({label}) reports whitespace errors:\n{out.strip()[:800]}")
        _, files, _ = sh(["git", "ls-files", "-z"], cwd=clone)
        files = [f for f in files.split("\0") if f]
        junk = [f for f in files if JUNK.search(f) and not ALLOWED_JUNK.search(f)]
        for f in junk:
            self.fail(f"tracked file that must not be committed: {f}")
        hits, fixture_hits = [], 0
        for rel in files:
            path = clone / rel
            try:
                if path.stat().st_size > 5_000_000:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for name, rx in SECRETS:
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    if name == "password-literal" and FIXTURE_PATHS.search(rel):
                        fixture_hits += 1
                        continue
                    hits.append(f"{rel}:{line} [{name}]")
        self.data["secret_scan"] = {"files_scanned": len(files), "hits": hits,
                                    "fixture_password_literals_ignored": fixture_hits}
        for h in hits:
            self.fail(f"possible credential: {h}")
        cmd = [str(PYTHON), "-m", "harness", "check", str(clone), "--track", "pocketful"]
        self.commands.append(f"(cd {HARNESS}) " + " ".join(cmd))
        code, out, err = sh(cmd, cwd=HARNESS)
        report = (out + err).strip()
        self.data["harness_check"] = {"exit": code, "output": report[-4000:]}
        if code:
            cred = [l for l in report.splitlines() if re.search(r"(?i)credential|secret|token|key", l)]
            if cred:
                self.fail("official `harness check` flags credentials:\n" + "\n".join(cred[:10]))
            self.note(f"official `harness check` exit {code} (layout/mandate items are submission-level, not stage gating):\n{report[-1500:]}")

    # 3. runtime -------------------------------------------------------------------
    def run_command(self, folder: Path, override: str | None) -> str | None:
        if override:
            self.note(f"RUN.md extraction overridden with --run-cmd: {override}")
            return override
        text = (folder / "RUN.md").read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = next((i for i, l in enumerate(lines)
                      if re.search(r"(?i)without docker|non-docker|no docker|locally|natively", l)), 0)
        for line in lines[start:]:
            s = line.strip().strip("`").strip()
            s = re.sub(r"^[$>]\s*", "", s)
            if RUN_LINE.match(s) and not re.search(r"\bpip\b|\bnpm (ci|install)\b", s):
                return s
        self.fail("could not find a non-Docker start command in RUN.md")
        return None

    def start(self, folder: Path, command: str, port: int, log: Path):
        literal = command
        command = re.sub(r"\$\{PORT(:-[^}]*)?\}|\$PORT\b", str(port), command)
        command = re.sub(r"^python3\b", "python", command)
        env = dict(os.environ, PORT=str(port), PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        env["PATH"] = str(PYTHON.parent) + os.pathsep + env.get("PATH", "")
        for k in ("POCKETFUL_DB", "VIRTUAL_ENV"):
            env.pop(k, None)
        while (m := re.match(r"^([A-Z_][A-Z0-9_]*)=(\S+)\s+", command)):
            env[m.group(1)] = m.group(2)
            command = command[m.end():]
        self.data["run_md_command"] = literal
        self.data["run_command_executed"] = f"(cd stage-{self.stage}; PORT={port}) {command}"
        self.commands.append(self.data["run_command_executed"])
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        fh = open(log, "w", encoding="utf-8")
        proc = subprocess.Popen(command, cwd=folder, env=env, shell=True, stdout=fh,
                                stderr=subprocess.STDOUT, creationflags=flags)
        return proc, fh

    @staticmethod
    def stop(proc):
        if proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            pass

    def wait_health(self, proc, base: str, timeout=60.0) -> bool:
        t0 = time.monotonic()
        last = "no response"
        while time.monotonic() - t0 < timeout:
            if proc.poll() is not None:
                self.fail(f"server exited with code {proc.returncode} before /health was 200")
                return False
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    body = json.loads(r.read() or b"{}")
                    if r.status == 200 and body.get("status") == "ok":
                        self.data["health_seconds"] = round(time.monotonic() - t0, 2)
                        return True
                    last = f"{r.status} {body}"
            except Exception as exc:  # noqa: BLE001 - polling
                last = repr(exc)[:120]
            time.sleep(0.25)
        self.fail(f"/health not 200 {{'status':'ok'}} within {timeout:.0f}s (last: {last})")
        return False

    # 4. conformance ---------------------------------------------------------------
    def harness(self, stages: list[int], base: str, label: str, extra: list[str]) -> dict:
        out = self.out / label
        cmd = [str(PYTHON), "-m", "harness", "run", "--track", "pocketful", "--base-url", base,
               "--stages", *map(str, stages), "--out", str(out), *extra]
        self.commands.append(f"(cd {HARNESS}) " + " ".join(cmd))
        print(f"harness {label}: stages {stages}")
        code, stdout, stderr = sh(cmd, cwd=HARNESS, timeout=3600)
        result = {"exit": code, "stdout": stdout.strip()[-1500:], "stderr": stderr.strip()[-1500:], "stages": {}}
        try:
            result["report_stages"] = json.loads((out / "report.json").read_text())["stages"]
        except (OSError, ValueError, KeyError):
            result["report_stages"] = {}
        for s in stages:
            counts_path, log_path = out / f"stage-{s}.counts.json", out / f"stage-{s}.log"
            try:
                counts = json.loads(counts_path.read_text())
            except (OSError, ValueError):
                counts = {}
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            failures = [l for l in log.splitlines() if l.startswith(("FAILED ", "ERROR "))]
            result["stages"][str(s)] = {
                "status": result["report_stages"].get(str(s)),
                "counts": {k: counts.get(k) for k in ("collected", "passed", "failed", "errors", "skipped", "xfailed", "deselected")},
                "failures": failures, "log": str(log_path)}
            c = result["stages"][str(s)]["counts"]
            print(f"  stage {s}: {result['stages'][str(s)]['status']} {c}")
        return result

    def conformance(self, base: str):
        own = list(range(1, self.stage + 1))
        main = self.harness(own, base, "harness-stages", [])
        self.data["official"] = main
        for s in own:
            r = main["stages"][str(s)]
            c = r["counts"]
            ok = (r["status"] == "pass" and c["collected"] and c["passed"] == c["collected"]
                  and not c["failed"] and not c["errors"] and not c["skipped"])
            if not ok:
                detail = "\n".join(r["failures"][:40]) or main["stderr"]
                self.fail(f"official stage {s} not 100%: {c}\n{detail}")
        probe = self.stage + 1
        if not (HARNESS / "pocketful" / "test" / f"stage_{probe}").is_dir():
            self.note(f"no stage {probe} suite: overshoot probe not applicable")
            return
        extra = ["--previous-base-url", base] if probe >= 2 else []
        result = self.harness([probe], base, f"harness-probe-stage-{probe}", extra)
        self.data["overshoot_probe"] = result
        r = result["stages"][str(probe)]
        c = r["counts"]
        if r["status"] == "pass" or (c["collected"] and c["passed"] == c["collected"]):
            self.fail(f"overshoot: stage-{self.stage}/ fully passes the stage {probe} suite {c}, so it claims nothing")

    # 5. server log ----------------------------------------------------------------
    def server_log(self, log: Path):
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        lines = text.splitlines()
        five = [l for l in lines if FIVE_XX.search(l)]
        tracebacks = text.count("Traceback (most recent call last)")
        access = sum(1 for l in lines if re.search(r"\"(GET|POST|PUT|PATCH|DELETE) /", l))
        self.data["server_log"] = {"path": str(log), "lines": len(lines), "access_lines": access,
                                   "5xx_lines": five[:50], "tracebacks": tracebacks}
        if five:
            self.fail(f"{len(five)} 5xx line(s) in server log, e.g.:\n" + "\n".join(five[:10]))
        if tracebacks:
            first = text.index("Traceback (most recent call last)")
            self.fail(f"{tracebacks} traceback(s) in server log, first:\n{text[first:first + 1500]}")
        if not access:
            self.note("server log has no access lines; 5xx detection relies on the suites' own status assertions")

    # 6. project suites ------------------------------------------------------------
    def project_suites(self, clone: Path):
        tests = clone / "tests"
        if not tests.is_dir():
            self.note("no tests/ directory at this commit")
            return
        cmd = [str(PYTHON), "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
               "--ignore=tests/verify", "-o", "addopts="]
        self.commands.append("(cd <clone>) " + " ".join(cmd))
        print("project suites: pytest tests/")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("POCKETFUL_DB", None)
        try:
            code, out, err = sh(cmd, cwd=clone, timeout=2400, env=env)
        except subprocess.TimeoutExpired:
            self.fail("project suites exceeded 2400 s")
            return
        (self.out / "project-suites.log").write_text(out + "\n" + err, encoding="utf-8")
        tail = [l for l in out.splitlines() if l.strip()][-1:] or [""]
        counts = {k: int(n) for n, k in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)", tail[0])}
        failures = [l for l in out.splitlines() if l.startswith(("FAILED ", "ERROR "))]
        self.data["project_suites"] = {"exit": code, "summary": tail[0], "counts": counts,
                                       "failures": failures[:50], "log": str(self.out / "project-suites.log")}
        print(f"  {tail[0]}")
        if code not in (0, 5):
            self.fail(f"project suites exit {code}: {tail[0]}\n" + "\n".join(failures[:30]))

    # ------------------------------------------------------------------------------
    def run(self, run_cmd: str | None, skip_project: bool) -> int:
        self.out.mkdir(parents=True, exist_ok=False)
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        tmp = Path(tempfile.mkdtemp(prefix=f"gate-s{self.stage}-"))
        proc = fh = None
        try:
            clone = self.clone(tmp)
            folder = self.layout(clone)
            self.hygiene(clone)
            if folder.is_dir() and (folder / "RUN.md").is_file():
                command = self.run_command(folder, run_cmd)
                if command:
                    port = free_port()
                    base = f"http://127.0.0.1:{port}"
                    log = self.out / "server.log"
                    proc, fh = self.start(folder, command, port, log)
                    if self.wait_health(proc, base):
                        self.conformance(base)
                        if proc.poll() is not None:
                            self.fail(f"server died during the suites (exit {proc.returncode})")
                    self.stop(proc)
                    fh.close()
                    self.server_log(log)
            if not skip_project:
                self.project_suites(clone)
            else:
                self.note("project suites skipped (--skip-project)")
        finally:
            if proc:
                self.stop(proc)
            if fh and not fh.closed:
                fh.close()
            shutil.rmtree(tmp, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
        self.note("Docker unavailable on this host (no WSL): Dockerfile checked statically only; "
                  "isolated/no-outbound mode not exercised")
        verdict = "REJECT" if self.problems else "ACCEPT"
        self.data.update(verdict=verdict, problems=self.problems, notes=self.notes,
                         commands=self.commands, started_at=started,
                         finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                         out=str(self.out))
        (self.out / "gate-summary.json").write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        (self.out / "gate-summary.md").write_text(self.markdown(), encoding="utf-8")
        print(f"\n{verdict} stage {self.stage} @ {self.data.get('sha')}  ({len(self.problems)} problem(s))")
        print(f"summary: {self.out / 'gate-summary.md'}")
        return 0 if verdict == "ACCEPT" else 1

    def markdown(self) -> str:
        d = self.data
        out = [f"# Stage {self.stage} gate: {d['verdict']}", "",
               f"- commit: `{d.get('sha')}` {d.get('subject', '')}",
               f"- RUN.md command: `{d.get('run_md_command')}`",
               f"- executed: `{d.get('run_command_executed')}`",
               f"- health after: {d.get('health_seconds')} s", ""]
        for key, title in (("official", "Official suites"), ("overshoot_probe", "Overshoot probe")):
            for s, r in (d.get(key) or {}).get("stages", {}).items():
                out.append(f"- {title} stage {s}: **{r['status']}** {r['counts']}")
        if "project_suites" in d:
            out.append(f"- project suites: {d['project_suites']['summary']}")
        if "server_log" in d:
            sl = d["server_log"]
            out.append(f"- server log: {sl['access_lines']} access lines, {len(sl['5xx_lines'])} 5xx, {sl['tracebacks']} tracebacks")
        out.append(f"- secret scan: {len(d.get('secret_scan', {}).get('hits', []))} hits "
                   f"({d.get('secret_scan', {}).get('fixture_password_literals_ignored', 0)} fixture literals ignored)")
        out += ["", "## Problems", *([f"- {p}" for p in self.problems] or ["- none"]),
                "", "## Notes", *[f"- {n}" for n in self.notes],
                "", "## Commands", "```", *self.commands, "```", ""]
        return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--stage", type=int, required=True, choices=(1, 2, 3, 4))
    p.add_argument("--sha", required=True, help="committed revision to gate")
    p.add_argument("--out", help=f"new output directory (default {CHECKS}\\gate-s<N>-<sha7>-<utc>)")
    p.add_argument("--run-cmd", help="override the RUN.md non-Docker command (recorded as a note)")
    p.add_argument("--skip-project", action="store_true", help="skip pytest tests/")
    a = p.parse_args(argv)
    if not PYTHON.is_file() or not (HARNESS / "harness").is_dir():
        print(f"gate setup error: python {PYTHON} or harness {HARNESS} missing", file=sys.stderr)
        return 2
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(a.out) if a.out else CHECKS / f"gate-s{a.stage}-{a.sha[:7]}-{stamp}"
    return Gate(a.stage, a.sha, out.resolve()).run(a.run_cmd, a.skip_project)


if __name__ == "__main__":
    raise SystemExit(main())
