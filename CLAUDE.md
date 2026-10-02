# Claude continuation state — Pocketful (Dark Factory, Track 2)

Read this file, then CONTINUATION.md, then `git status` / `git log -5` before doing anything.

## Purpose
Development and audit repository for the Pocketful track of the WeAreDevelopers x BAND
Dark Factory hackathon (submissions close Mon Oct 5 2026, 23:59 PDT).

**This repository is NOT the judged submission.** Its stage code was changed outside a
Band room (commit `5ee1380`), it has no authentic `room.json`, and its mandates break the
mandate rules. The judged run must be a fresh Band Desktop room and a fresh result
repository. See `FINAL_BAND_HANDOFF.md` for the complete official requirements, the
defects found here, and the checklist for that run.

## Architecture
- `stage-1/` .. `stage-4/`: cumulative stage folders. `core.py` and `server.py` are
  byte-identical in all four (a regression test enforces this). `stage.py` differs per
  folder and sets the default stage; `POCKETFUL_STAGE` overrides it.
- `core.py`: `Store` — the whole state is one JSON blob in SQLite (`POCKETFUL_DB`).
  Every write goes through `Store.mutate()` (threading lock + `BEGIN IMMEDIATE`), so a
  write is atomic and an exception rolls back everything. Money is integer minor units.
- `server.py`: FastAPI app. Endpoints: `/health`, `/_test/reset|export|import`,
  `/auth/signup|login`, `/me`, `/payments`, `/requests` (+pay/decline/cancel), `/splits`,
  `/activity`, `/settlements` (stage 1); `/authorizations` (+capture/void) (stage 2);
  `/statement`, `/payments/{id}/revisions|corrections`, `as_of`/`known_at` (stage 3);
  `/payments/{id}/refunds`, `/correction-batches` (stage 4). `require_stage(n)` → 404.
  Browser UI is one inline HTML/JS page served for `/`, `/login`, `/signup`, `/split`,
  and `/requests` / `/authorizations` when `Accept: text/html`.
- `tests/`: project-owned regression suite (NOT the official suite).
- `mandates/`, `FACTORY.md`: Band factory seat documentation.

## Commands
- Install: `pip install -r stage-4/requirements.txt -r tests/requirements.txt`
- Regression suite: `python -m pytest tests -q -p no:cacheprovider`
  (set `PYTHONDONTWRITEBYTECODE=1` to avoid `__pycache__`)
- Against running services: `POCKETFUL_TARGET_<n>=http://host:port python -m pytest tests`
- Run one stage on host: `cd stage-N && uvicorn server:app --host 0.0.0.0 --port 8080`
- Docker: see each `stage-N/RUN.md`.
- Official harness (from the kickoff checkout, not in this repo; per the participant guide):
  `python -m harness check <repo> --track pocketful` (offline gates 1, 2, mandate vocabulary,
  secrets) and `python -m harness run --track pocketful --repo <repo> --stage N|--all
  --mode isolated --out <new dir>` (2 vCPU, 2 GiB, no runtime network; claims need ≥50% of
  every suite up to N and must fail suite N+1).

## Key invariants (as implemented)
- Balances never negative; available = total − open holds; holds expire at `expires_at`
  (expired when `expires_at <= now`).
- Writes needing `Idempotency-Key`: payments, requests, request pay, splits, settlements,
  authorizations, captures, corrections, refunds, correction batches. Replay key =
  (user, key, method, path); same key + different body → 409 `idempotency_key_reuse`.
- Settlements and correction batches: 1..32 items, operator-only, all-or-nothing.
- Revisions are append-only; `known_at` selects the latest revision with `recorded_at <= known_at`.

## Rules
- Never modify official tests. Never add hidden-test hacks. Never claim an unrun test passed.
- Remove local databases, caches, logs, credentials and temporary files before release.
- Preserve exact test counts and commit SHAs in CONTINUATION.md.
- Never put passwords, tokens, cookies or secrets in this file.
- Do not edit Dockerfiles to work around the cloud sandbox's TLS proxy; shim the local base
  image instead (see CONTINUATION.md).

- This repo is development evidence only. Do not present it, its tests or its history as
  Agent Teamwork evidence. Never fabricate `room.json`, seats, model ids or harness results.
- Commit only audit/handoff documentation here unless the user asks otherwise.

## Official sources
- Official kickoff repo: https://github.com/band-ai/dark-factory-wearedevs. On
  2026-09-29 these were read as plain text from `raw.githubusercontent.com`, on the user's
  instruction: `docs/participant-guide.md`, `pocketful/spec/stage-1..4.md`, every shipped
  `pocketful/test` file, and `harness/check.py`, `vocabulary.py`, `cli.py`, `report.py`.
  Downloads were verified against `kickoff-manifest.json` sha256; the guide on `main`
  differs from the manifest. Cloning is blocked by the session permission classifier; the
  GitHub API is blocked for this unattached repo. The official harness has never been
  executed here.
- Developer machine copy: `C:\Users\arulm\FORGE\OFFICIAL_DARK_FACTORY` (not reachable from
  the cloud session).
- The requirements digest is `FINAL_BAND_HANDOFF.md` §2–§9.

See CONTINUATION.md for session state and next actions.
