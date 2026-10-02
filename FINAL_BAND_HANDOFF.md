# Final Band handoff — Pocketful

Prepared 2026-09-29 in a Claude Code cloud session. This is **development and audit
evidence only**. It is not Agent Teamwork evidence and not a submission.

This repository (`arulmuruganmcse2024-tech/pocketful-dark-factory`) must **not** be
submitted as the judged result:
- Commit `5ee1380` changed code under `stage-N/` from outside any Band room. The guide
  says "anything you commit there yourself is code the band did not write".
- It has no authentic `room.json`.
- Its mandates break the mandate rules (§13).

The judged run needs a fresh Band room and a fresh result repository.

---

## 1. Sources read

All read as plain text from the public `band-ai/dark-factory-wearedevs` repository
(`main`, fetched 2026-09-29) through `raw.githubusercontent.com`. Nothing was executed.
Cloning was blocked by this session's permission rules.

| File | Verified against `kickoff-manifest.json` sha256 |
|---|---|
| `docs/participant-guide.md` | **differs**: the guide on `main` has changed since the manifest was generated. This handoff follows the current `main` text |
| `pocketful/spec/stage-1.md` … `stage-4.md` | match |
| `pocketful/test/conftest.py`, `fixtures.py`, all 9 test files | match |
| `harness/check.py`, `vocabulary.py`, `cli.py`, `report.py`, `provenance.py` | match |
| `README.md` | match |

Not read: the tablekeeper and toy specs, `harness/http.py`, `harness/concurrent.py`,
`harness/plugin.py`, `harness/artifacts.py`, `harness/docker_driver.py` (only a grep for
limits), and the scaffold. The hackathon website (lablab.ai) was not reachable from this
session: WEBSITE_ACCESS_UNVERIFIED.

---

## 2. Band Desktop teamwork requirements (participant guide)

1. **Seats.** At least three distinct Band Desktop seat identities that you configured.
   Seats may share a harness and model.
2. **Mandates.** One `mandates/<seat>.md` per seat, named after the seat as the room shows
   it, ignoring case and punctuation (`delivery-manager.md` for "Delivery Manager").
   `harness check` matches every agent `senderName` in `room.json` to a file stem, after
   lowercasing and stripping non-alphanumerics.
3. **Mandate header.** Each mandate starts with the harness **as Band Desktop shows it**
   (Claude Code, Codex, OpenCode, …) and the **exact model id**:
   ```
   Harness: Claude Code
   Model: <exact model id the seat runs>
   ```
   "Harness" is the seat's agent runtime, not the event harness.
4. **Generic mandates** (disqualifying if broken). No endpoint paths, field names, error
   codes, test ids or fixture ids. Nothing may tell a reader which track you entered. The
   exact banned token list is `harness/vocabulary.py` `TRACK_VOCABULARY['pocketful']` (§4).
   The test to apply: could a team building something else use these mandates unchanged?
5. **Reciprocal @handles** (gate 2). Two of your seats address each other with a typed
   `@handle` (stored as `@[[participant-id]]`) in `text` messages, with a reply in each
   direction. A mention inside a tool call or its output does not count.
6. **Code comes from the room.** A stage counts only if the code passing its tests came
   out of the room's collaboration. Hand-built code does not count.
7. **Fresh run.** Iterate as much as you like, then run the chosen factory in a **fresh
   room and a fresh result repository**. Only that run is judged for Agent Teamwork.
8. **Dark-factory run.** Per stage, the dispatched task is the only human input. No
   steering, approvals, confirmations, debugging hints or reruns. No seat may ask you
   anything or wait on you. "looks good, continue" is steering, and dispatching a stage
   twice is a rerun. You may dispatch stage by stage or all four at once, and send nothing
   in between. Resolve spec questions before starting.
9. **Handoffs.** The coordinator adds every configured seat to the room before its first
   handoff, and retries if Jam reports the seat absent. Every delegated handoff pastes the
   **complete task and spec** (numbered parts are fine). A message id or "read the room"
   is not a handoff. The implementer posts the full committed revision. The reviewer runs
   the checks independently, from a handoff that also carries the full requirements.
10. **Stage progression.** `stage-2/` is `stage-1/` copied forward and widened, and so on.
    Delete any copied `.git`. Do not copy the final answer back into earlier folders.
11. **History.** Push the seats' history without amending, rebasing or squashing. Configure
    a Git name and email per seat. Give seats the **absolute** path of the result repo.
12. **Evidence judges read.** Work split between seats, review that changed something,
    rejections that say what failed with the fix returning through the room, and commits
    traceable to the discussion. Chat volume and seat count are not scored.
13. **Room download.** Band console → room ⋮ → Download → **Download full session**, never
    filtered. Save unchanged as `room.json` at the repo root; rename only. Read it for
    secrets first; if one is found, rotate it and replace the value with `[REDACTED]`.

---

## 3. Submission gates and repository shape

Fail any gate and the entry is not ranked:
1. Three or more seats, each with a named mandate carrying `Harness:` and `Model:` lines.
2. Reciprocal `@handle` messages between two of your seats.
3. `stage-1/` builds and serves from a clean container by following its `RUN.md`.
4. Mandates are generic, and the code is written to the spec, not the tests. This is
   enforced after submissions close, using the same vocabulary list.

Required layout:
```
README.md    team, track, how to read the repo (written, not a placeholder)
FACTORY.md   seats, setup, design choices and why, what failed, measured time and model
             spend, how bad work is caught and recovered
mandates/    >= 3 files, one per seat
room.json    unedited full-session download
stage-1/ .. stage-4/   each: Dockerfile, RUN.md, source; only the stages completed
```

Other eligibility requirements: a presentation, a video showing the factory working (the
room, a handoff, the result), and a **public** GitHub repo cloneable without Band membership.

`harness check <repo> --track pocketful` validates offline:
- README.md and FACTORY.md exist; `stage-1/` exists.
- Stage folders are named `stage-1`..`stage-4`; none contains its own `.git`; each has
  `Dockerfile` and `RUN.md`.
- `mandates/` has at least 3 `*.md` files, each with a line matching `^Harness:` and
  `^Model:` followed by a value.
- No mandate line contains a vocabulary token.
- `room.json` has `messages[]`, `scope` absent or `"full"`, at least 3 agent senders, and a
  reciprocal `@[[id]]` pair; every agent sender has a mandate file.
- Credential scan over every text file, `room.json` included. Patterns: `bearer <20+
  chars containing a digit>`, `sk-…`, `AKIA…`, `gh[pousr]_…`, `url user:pass@`, and in
  config files, Dockerfile and `.json` other than `room.json`,
  `NAME(KEY|TOKEN|SECRET|PASSWORD)=value` (case-insensitive).

Scoring mechanics (`harness/report.py`, `cli.py`):
- **PASS_BAR = 0.5.** `stage-N/` claims N only if each of suites 1..N passes at least 50%
  of its checks.
- **Overshoot.** `stage-N/` (N < 4) is also run against suite N+1. If it passes every
  check there, it claims nothing. This includes `stage-2/` against suite 3.
- **Chain.** A folder counts only if every earlier folder counts.
- **Upgrade source.** With `--repo`, upgrade tests import exports from the repo's own
  preceding stage folder.
- **Shipped vs full suite.** Shipped: stage 1 = 147 collected tests (79% of the suite),
  stage 2 = 35 (35%), stage 3 = 6 (9%), stage 4 = 5 (16%). Judging runs the full suites.
- Rubric: Factory 50%, App 25%, Agent Teamwork 25%.
- Timeline: kickoff Sat Sep 26 09:00 PDT; **submissions close Mon Oct 5 23:59 PDT**.

Pre-submit list (guide "Before you submit"):
1. Fresh clone, then `harness check`.
2. `harness run --repo <clone> --all --mode isolated`.
3. Follow every `RUN.md` by hand in a clean environment and use the UI.
4. Read `room.json` for the reciprocal exchange and for rewritten history.
5. README.md and FACTORY.md are real documents.
6. Re-read mandates for track vocabulary.
7. Secret skim; rotate anything found.
8. Submit repo URL, presentation and video; keep the receipt.

---

## 4. Banned mandate vocabulary (pocketful)

These tokens must not appear in any mandate line. They are matched as identifier shapes:
`/path`, `snake_case`, `kebab-case`.

Endpoints: `/activity` `/auth/login` `/auth/signup` `/authorizations`
`/authorizations/{id}/capture` `/authorizations/{id}/void` `/correction-batches` `/payments`
`/payments/{payment_id}/corrections` `/payments/{payment_id}/refunds`
`/payments/{payment_id}/revisions` `/requests` `/requests/rq_4/pay` `/requests/{id}/cancel`
`/requests/{id}/decline` `/requests/{id}/pay` `/settlements` `/split` `/splits` `/statement`.

Identifiers and test ids: every data-testid in stage 2, every error code, and the field
names `as_of` `known_at` `effective_at` `recorded_at` `expected_revision` `minor_units`
`from_handle` `to_handle` `payer_handle` `requester_handle` `participant_handles`
`payment_id` `payment_ids` `request_id` `authorization_id` `settlement_id` `refund_of`
`split_id` `correction_batch_id` `settlement_operator_ids` `authorization_ttl_seconds`
`captured_amount` `remaining_amount` `closed_at` `expires_at` `committed_at`
`opening_balance` `closing_balance` `balance_after` `format_version` `from_user_id`
`to_user_id` `payer_id` `requester_id` `data-amount` `data-status` `data-visibility`
`u_ada` `u_bob` `rq_1` `rq_4` `sp_2`.

The authoritative list is `harness/vocabulary.py`. Prose words like "wallet", "payment" and
"balance" are not scanned, but the guide still says a mandate must not reveal the track.

---

## 5. Deployment requirements (stage 1 §2–§3, guide)

- The HTTP service is built from `stage-N/Dockerfile`. Any language. Judges talk HTTP only
  and never import the source.
- Start: `docker run -e PORT=<port> -p ...`. Listen on `0.0.0.0:$PORT`, default `8080`. The
  harness uses container port 8080. Compose is never used.
- `GET /health` → `200 {"status":"ok"}` within **60 s** of start.
- Isolated grading: internal Docker network, **no outbound network at run time**
  (available during `docker build`), **2 vCPU, 2 GiB**.
- Up to **50 concurrent requests**; per-request timeout **5 s**, **10 s** for
  `POST /_test/reset`.
- All runtime assets (fonts, scripts, styles) inside the image; no CDN.
- Disk is ephemeral; state need not survive a restart. `RUN.md` must build and start
  without manual setup.
- No submodules or symlinks. `.git` inside a stage folder yields an empty folder for judges.

---

## 6. Stage 1 requirements (`pocketful/spec/stage-1.md`)

**Invariants, under concurrency and retries.**
1. The sum of balances equals the total seeded by the last reset.
2. No balance is ever negative, even transiently.
3. A request moves money at most once.

All amounts are integer minor units. Money moves only between existing wallets.

**Conventions (§3.4).**
- Requests and responses are JSON `utf-8`.
- Response timestamps are RFC 3339 with an explicit offset.
- Unknown body fields and unknown query parameters are ignored.
- IDs are opaque, ≤ 64 characters.

**Reset (§3.3).**
- `POST /_test/reset` with the fixture → `204`, replacing all state.
- Unauthenticated, enabled in the shipped image, repeatable.

**Fixture (§4).**
- Fields: `currency` (EUR / JPY / BHD), `minor_units` (2 / 0 / 3), `users[]` (id, email,
  password, display_name, handle, balance), `payments[]` (id, from_user_id, to_user_id,
  amount, note, visibility), `requests[]` (id, requester_id, payer_id, amount, note,
  status), and `settlement_operator_ids` (default `[]`).
- Seeded users log in immediately.
- `balance` is the balance **after** seeded payments; do not replay them.
- A negative seeded balance → `422 validation_failed`, with nothing changed.

**Amounts (§4, §5).**
- `1000`, `1000.0` and `1e3` are the same valid amount.
- Booleans, strings, fractions, values < 1 and values > 1,000,000,000 → `422
  validation_failed`.
- No balance may leave ±2^53, and arithmetic is exact.

**Handles.**
- Handles match `^[a-z0-9_]{1,20}$`, are unique and never change.
- Signup derives the handle from the email local part: lowercase it, replace every char
  outside `[a-z0-9_]` with `_`, then truncate to 20 characters.
- New users start at 0 and can receive money and requests at once.

**Errors (§5).**
- Every 4xx/5xx body is `{"error":{"code","message"}}`.

| Status | Code | When |
|---|---|---|
| 400 | `malformed_request` | Unparseable body, or a **field of the wrong JSON type** |
| 400 | `missing_idempotency_key` | Header absent or empty |
| 401 | `unauthenticated` | Missing, malformed or unknown token |
| 403 | `forbidden` | Authenticated but not permitted |
| 404 | `not_found` | Missing, or not visible to the caller |
| 409 | `idempotency_key_reuse` | Same key, different body |
| 422 | `validation_failed` | Missing required field, bad format or range, or a rule with no more specific code |

- Endpoint rules override the 400 rule: invalid `amount` (including strings and booleans),
  a non-string `note` (including `null`) and a bad `visibility` are 422.
- Integer query parameters must be plain digits: `1e9`, `4.0` and `+4` → 422.
- `Idempotency-Key` 1..255 chars, `limit` 1..200, `offset` ≥ 0, otherwise 422.
- **No 5xx ever**, including under load.

**Auth (§6).**
- `POST /auth/signup {email,password,display_name}` → `201 {user_id,display_name,token}`.
- `POST /auth/login` → `200` with the same shape.
- Errors:
  - `409 email_taken`.
  - `422` for a password under 8 characters.
  - `422` for an email not of the form `local@domain`.
  - `401` for a wrong password or unknown email.
  - `409 handle_taken`, with no account created.
- Every other endpoint needs `Authorization: Bearer`, except `/health`, `/_test/*` and
  the two auth endpoints.
- Tokens never expire, and one account may hold multiple tokens.
- Passwords use a real password hash (bcrypt, scrypt, Argon2 or equivalent).

**Idempotency (§7).** Five paths need a key: `POST /payments`, `/requests`,
`/requests/{id}/pay`, `/splits` and `/settlements`.
- Scope is per user, and a replay is the same method + path + body (parsed JSON equality).
- First use → 201. Replay → **200** with an identical body. Different body → 409.
- A key whose request failed with a 4xx is a first use again.
- Concurrent identical first uses: exactly one 201, the rest 200 with the same body,
  and the effect happens once.
- A replay returns the original even after the resource changed, and makes no changes.
- **Precedence:** once the body parses as an object and the caller is authenticated, a
  claimed key is resolved before field validation or resource checks. An invalid body on
  a used key → 409.

**Endpoints (§8).**
- `GET /me` → `{user_id, display_name, handle, balance, currency, minor_units}`.
- `POST /payments {to_handle, amount, note?="", visibility?="public"}` → 201 with
  `{payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note,
  visibility, request_id:null, created_at}`.
  - Errors: 409 `insufficient_funds`; 422 amount; 422 `self_payment`; 422 note over 200
    **characters** (not bytes); 422 visibility; 404 unknown handle.
  - Debit and credit are atomic, and a failure leaves no trace.
  - `note` is verbatim: no trim, escaping or normalisation, and emoji survive.
- `POST /requests {payer_handle, amount, note?}` → 201 with the request shape.
  - Errors: 422 amount, 422 `self_request`, 422 note, 404 unknown.
  - **The payer's balance is not checked.**
- `POST /requests/{id}/pay {visibility?}` → 201 payment with `request_id` set; the request
  becomes `paid` with its `payment_id`.
  - Errors: 409 `request_not_pending`, 409 `insufficient_funds`, 403 non-payer, 404
    unknown.
  - `{}` and `{"visibility":"public"}` are different bodies.
  - A replay after paid → 200 with the original body, never 409.
- `POST /requests/{id}/decline` (payer) and `/cancel` (requester) take **no key** and
  return 200 with the request. Repeating the same action → 200. Otherwise-closed → 409
  `request_not_pending`. Wrong party → 403.
- `GET /requests?direction&status&limit&offset`:
  - Only requests where the caller is requester or payer, newest first.
  - Unknown `direction` or `status` → 422.
  - Response `{"requests":[...],"has_more":bool}`.
- `POST /splits {amount, participant_handles, note?}` → 201 `{split_id, amount, currency,
  note, shares[{handle,amount}], requests[], created_at}`.
  - `shares` cover everyone in the given order and sum to `amount`.
  - `requests` go to everyone except the caller, in order.
  - Empty or duplicate list → 422; unknown handle → 404.
  - A caller-only split is valid with `requests: []`.
  - A 0 share still creates a request. No balance is checked.
- `GET /activity?limit&offset` → `{"payments":[...],"has_more":bool}`.
  - Payments only, newest first.
  - Visible iff `public`, or the caller is sender or receiver.
  - Same-second order is unspecified.

**Rounding (§9).** `base = amount // n`; the first `amount % n` participants in the
given order get +1.

**Export/import (§10).**
- `GET /_test/export` → 200 `{track:"pocketful", format_version:1, state:{...}}`, an
  atomic read-only snapshot.
- `POST /_test/import` of that object replaces state atomically → 204.
- Wrong track or version, missing fields or an invalid state → 422, with the destination
  unchanged. Malformed JSON → 400.
- Must preserve: accounts, password login, **existing tokens**, currency, balances,
  payments, requests, permissions, every completed idempotent body and response, and
  settlement membership.
- Nothing is regenerated or replayed. Failed keys stay reusable.
- Import removes all previous data; reset clears imported state. No dependency on the
  source process, files or network.

**Settlements (§11).**
- `POST /settlements {transfers:[{from_handle,to_handle,amount,note?,visibility?}]}`
  needs an operator and a key: no token → 401, non-operator → 403.
- 1..32 transfers.
- Per-entry errors: 404 unknown handle, 422 `self_payment`; a malformed shape → 422.
  Entry errors take precedence **in input order**, before funds.
- Affordable iff every wallet's **net** result is ≥ 0; otherwise 409 `insufficient_funds`.
- All or nothing. A failure claims no key and creates nothing.
- 201 `{settlement_id, committed_at, payments[]}` in input order:
  - Every member carries `settlement_id`, `request_id:null`, and `created_at ==
    committed_at`.
  - Non-members expose `settlement_id: null`.
- Replay → 200 with the original. Operator permission grants no access to others' requests
  or private items.

---

## 7. Stage 2 requirements (`stage-2.md`)

**Routes.**
- `/` (balance, pay form, request form, feed), `/requests`, `/split`, `/signup`, `/login`
  and `/authorizations`.
- `/requests` and `/authorizations` serve HTML only for `Accept: text/html`, JSON
  otherwise.
- Other screens are reachable through the UI.

**Product quality (App score).**
- A coherent, calm consumer-finance look.
- **`available` is the headline number** once holds exist; total and held are secondary.
- Distinct visual states: available, held, pending, loading, success, refused, uncertain.
- Human-first formatting of people, amounts and times.
- Usable at **375 px** and desktop with no horizontal scroll.
- Visible labels, visible focus, sufficient contrast.
- Considered empty, loading and error states, and consistent navigation.

**Testids, each with exact semantics.**
- Auth:
  - `signup-email/-password/-display-name`, `signup-submit`, `login-email/-password`,
    `login-submit`.
  - `auth-error` is **present only when there is an error**.
  - `current-user` appears on every screen when signed in and contains the display name.
  - `current-handle` text is exactly the handle, with no `@`.
  - `logout-button`.
- Wallet:
  - `wallet-balance` text is exactly the formatted `total`, e.g. `100.00 EUR` or
    `1200 JPY`, with `data-amount`.
  - `wallet-available` carries `data-amount` and is the headline.
  - `wallet-held` carries `data-amount` and is **absent when held is 0**.
- Pay form:
  - `pay-handle`, `pay-amount` (decimal string), `pay-note`, `pay-visibility` (option
    values `public`/`private`), `pay-submit`.
  - `pay-error` appears when refused, including insufficient funds.
  - `pay-uncertain` holds nonempty text when the outcome is unknown.
- Request form: `request-handle/-amount/-note/-submit`, and `request-error`.
- Feed:
  - `activity-list`, whose children are newest first in the DOM.
  - `activity-item-{id}` with `data-visibility`.
  - `activity-parties-{id}` contains both handles.
  - `activity-amount-{id}` text is exactly the formatted amount.
  - `activity-note-{id}` text is exactly the note, and is present even when empty.
  - `empty-activity` replaces the list when nothing is visible.
- Requests:
  - `incoming-list` and `outgoing-list`.
  - `request-item-{id}` with `data-status`.
  - `request-amount-{id}`.
  - `request-pay-{id}` and `request-decline-{id}` only on pending incoming requests.
  - `request-cancel-{id}` only on pending outgoing requests.
  - `request-error`, and `empty-requests` when both lists are empty.
- Split:
  - `split-amount`, `split-handles` (comma separated, in order), `split-note`,
    `split-submit`, `split-error`.
  - `split-preview` holds one `split-share-{handle}` per participant, whose text is
    **exactly** the formatted share.
  - The preview uses the §9 rule and matches the server exactly.
- Authorizations:
  - Form: `authorize-handle/-amount/-note/-visibility/-submit`, `authorize-error`.
  - `authorization-list` children are newest first.
  - `authorization-item-{id}` carries `data-status`.
  - `authorization-amount-{id}`.
  - `authorization-captured-{id}` only when captured.
  - `authorization-expires-{id}` text is the RFC 3339 `expires_at`.
  - `authorization-capture-amount-{id}` is prefilled with the remainder, and it and
    `authorization-capture-{id}` appear only on incoming open authorizations.
  - `authorization-void-{id}` only on outgoing open authorizations.
  - `authorization-error`, and `empty-authorizations`.

**Behaviour.**
- Decimal input:
  - With 2 minor units, `15` and `15.00` → 1500 and `15.5` → 1550.
  - Non-numeric input or too many places (`15.005`) shows the form's error and sends
    **nothing**.
- The pay form keeps its values after success. Resubmitting unchanged is a replay (same
  key and body): the balance falls once, one feed item, `pay-error` absent. Changing any
  field starts a new payment with a new key.
- After any successful action the page shows the new balance, feed and lists with no
  manual reload; refresh happens after the write succeeds.
- `wallet-refresh` refreshes balance and feed without clearing the form. **Latest refresh
  wins**, even when responses arrive out of order.
- A refused payment shows `pay-error`, **refreshes balance and feed**, and keeps all
  inputs.
- A request cancelled elsewhere, then paid here → `request-error`, and the list refreshes
  so the stale pay button goes.
- Lost response (even after commit) → `pay-uncertain`, not `pay-error`. The unchanged form
  retries with the **same key and body**. A successful retry removes both elements,
  refreshes, and moves money once.
- Upgrade:
  - A stage-2 service accepts a stage-1 export.
  - A browser signed in before the import stays signed in.
  - Pending requests stay payable.
  - A payment whose response was lost before export is retryable after import with the
    same key and body; the UI recovers the original payment and refreshes.
  - No reload is needed.

**Authorizations model.**
- Fixture fields: `authorization_ttl_seconds` (default 600; positive integer) and
  `authorizations[]` (id, from_user_id, to_user_id, amount, note, visibility, status
  open/captured/voided/expired, absolute `expires_at`).
- `available` is derived, never seeded.
- Seeded unexpired open holds above a user's balance → reset 422, with nothing changed.
- An authorization with `expires_at <= now` is `expired` and holds nothing; this must show
  on reads with no write at the deadline.
- Invariants:
  - The sum of `total` equals the seed.
  - `available = total − held ≥ 0` always.
  - Held funds cannot fund payments, authorizations or settlement net debits.
  - Captures may spend their own reserve.
  - Cumulative captures ≤ authorized.
  - Each capture moves money once, and a closed hold cannot be captured.

**API.**
- `GET /me` adds `total` (== `balance`), `available` and `held`.
- All stage-1 `insufficient_funds` checks now use `available`.
- There are seven idempotent paths (+ authorizations, + captures).
- `POST /authorizations {to_handle, amount, note?, visibility?}` → 201 `{authorization_id,
  from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount:0, currency,
  note, visibility, status:"open", expires_at, payment_id:null, created_at}`.
  - `expires_at` must **equal** `created_at + ttl`.
  - Errors: 409 on available funds, 422 amount, 422 `self_payment`, 422 note/visibility,
    404.
  - It is not a feed item.
- `POST /authorizations/{id}/capture {amount?, final?=true}` (receiver only) → 201 with a
  payment in the `POST /payments` shape: `authorization_id` set, `request_id:null`, and the
  note and visibility copied.
  - Default: `captured`, with the remainder released at once.
  - `final:false` keeps the remainder held and the status `open`. Capturing the whole
    remainder closes it.
  - `captured_amount` is cumulative, `payment_id` is the latest capture, and `payment_ids`
    lists every capture in order.
  - Every authorization response includes `remaining_amount` (0 when closed).
  - Errors: 409 `authorization_not_open`, 409 `authorization_expired`, 422
    `capture_exceeds_authorization` (against the remainder), 422 amount, 403, 404.
  - `{}` and `{"amount":N}` are different bodies.
- `POST /authorizations/{id}/void` (payer only, no key) → 200 `voided`, hold released.
  - Voiding again → 200. Captured or expired → 409 `authorization_not_open`.
- Anyone else, including non-parties, gets 403 on capture or void.
- `GET /authorizations?direction(outgoing|incoming)&status&limit&offset`:
  - Only authorizations involving the caller, newest first.
  - A clock-expired one matches `expired`, never `open`.
- Concurrency: results are serializable, and the invariants hold at every read.

---

## 8. Stage 3 requirements (`stage-3.md`)

**Payments and fixture.**
- Every payment's `created_at` is an RFC 3339 instant with an offset, and every payment
  response includes it. `/activity` stays ordered by it.
- Seeded `created_at` is optional (default: reset time, before later API payments). A
  future value → reset 422, with nothing changed.
- Loading seeded payments never changes balances.

**`GET /me?as_of=T`.**
- `T` must be RFC 3339 with an offset. Naive, date-only or empty → 422.
- The balance counts every payment with an effective time ≤ T (inclusive).
- T after the last payment gives the current balance; T before the first gives the opening
  balance.
- `as_of` is echoed exactly.
- Without temporal parameters, the response is unchanged: no `as_of` key and current
  corrected values.

**`GET /statement?from&to&limit&offset`.**
- `from` defaults to the wallet's opening, `to` to now.
- The window is half-open `[from, to)` and lists only payments the caller sent or
  received (public payments between others are excluded), **oldest first**.
- Ordering is by selected `effective_at`, then payment id.
- Each entry has `payment`, `delta` (sent negative) and `balance_after`, plus the
  selected `revision`, `effective_at` and `recorded_at`. `payment.amount` is the selected
  amount.
- `opening_balance` is the balance just before `from`; `closing_balance` the balance just
  before `to`.
- `opening_balance` + Σ deltas over the full window = `closing_balance`.
- Paging never changes `balance_after`, opening or closing. `has_more` is correct, even
  past the end.

**Revisions.**
- Revision 1 is the original amount, with `effective_at = recorded_at = created_at`.
- Opening balances are the seeded ending balance minus the net of seeded originals.
  Corrections never change them, and new accounts open at 0.

**`POST /payments/{id}/corrections`** — key required, original sender only (else 403),
unknown → 404.
- Body `{expected_revision, amount 0..1e9, effective_at <= now, reason 1..200}`, all
  required; invalid → 422.
- Appends an immutable revision and returns 201 `{payment_id, revision, amount,
  effective_at, recorded_at, reason}`.
- `recorded_at` is strictly increasing per payment.
- Stale revision → 409 `stale_revision`. A replay → 200 with the original, even after
  newer revisions.
- The difference moves between the same two wallets: an increase debits the sender, a
  decrease the receiver.
- Currently unaffordable (against available) → 409 `insufficient_funds`. Otherwise, if any
  user's corrected **total or available** would be negative at any effective or event
  boundary → 409 `historical_overdraft`.
- Balances at a boundary include **all movements at that instant combined**.
- A failure changes nothing, idempotency included.
- The sum of balances equals the seed in every historical view.
- The original payment and every original idempotent response stay unchanged. Corrections
  are not feed items.
- `GET /payments/{id}/revisions` → `{"revisions":[...]}` in order, including revision 1
  (`reason:""`). Parties only: a third party gets 404 even on a public payment; no token →
  401.

**`known_at=K`** (on `/me` and `/statement`).
- Per payment, use the latest revision recorded ≤ K; if none, the payment contributes
  nothing.
- Omitted means everything known when the read begins.
- Apply the selected revisions by effective time. `as_of` stays inclusive and statements
  stay half-open.
- Both instants may be in the future. Invalid or empty → 422.
- `known_at` is echoed exactly. Zero-amount revisions appear as entries with delta 0.
- No correction is counted alongside the revision it replaces.

**Snapshots.**
- The first `/statement` response returns an opaque `snapshot`, freezing selected
  revisions, window, balances, entries and the default `to`.
- `?snapshot=&limit&offset` pages that exact result.
- `from`, `to` or `known_at` alongside a snapshot → 422.
- Unknown, another user's or pre-reset tokens → 404. Tokens last until reset.
- Snapshots stay unchanged under concurrent payments, corrections and lifecycle events.
- Concurrent corrections on the same expected revision cannot both succeed.

**Settlement and capture history.**
- A member's revision 1 uses `committed_at` for both times.
- Single corrections of settlement members or captures → 422 `linked_payment_immutable`.
- Must import stage-1 and stage-2 exports, accounting for authorizations and captures.

**Historical holds (`/me?as_of=T&known_at=K`).**
- All four money fields describe the same view.
- A hold starts at creation. A non-final capture reduces it at capture time. A final
  capture, void or expiry releases the remainder at that event's time. Expiry happens at
  `expires_at`.
- Non-expiry events are known at their server event time. Once creation is known, the
  deadline is known.
- For queries beyond now, an open hold expires at its deadline. Without `as_of`, use the
  instant the request began.
- Authorizations expose `closed_at` (null while open).
- Seeded open holds count as created at reset unless `created_at` is given.
- Statements contain money movements only; captures appear once.

---

## 9. Stage 4 requirements (`stage-4.md`)

There are ten idempotent paths (+ corrections, + refunds, + correction batches).

**`POST /payments/{id}/refunds {amount}`** — key required, original receiver only (else
403), unknown → 404.
- The target may be a direct payment, a request payment, a capture or a settlement member,
  **never a refund**: 422 `invalid_refund_target`. Invalid amount → 422.
- Cumulative refunds ≤ the **current corrected** amount, else 422 `refund_exceeds_payment`.
- A refund is a reverse payment with `refund_of` set, `request_id:null`,
  `authorization_id:null`, and the original note and visibility.
  - 201; a replay → 200 with the original.
  - It is paid from the receiver's **available** funds, else 409 `insufficient_funds`,
    atomically.
  - It never reopens a request or authorization, restores a hold, or changes settlement
    membership.
- Other payments carry `refund_of: null`.

**Corrections, extended.**
- Captures and refunds are immutable: 422 `linked_payment_immutable`.
- **A correction may not reduce a payment below its refunded total: 422
  `refund_exceeds_payment`.**
- Correction debits are checked against available funds.

**`POST /correction-batches {corrections:[{payment_id, expected_revision, amount,
effective_at, reason}]}`** — operator plus key; 401/403 as for settlements.
- 1..32 items with distinct `payment_id`s, else 422. Each item gets the ordinary
  correction validation. Unknown → 404; stale → 409.
- Ordinary, request and settlement payments are allowed; captures and refunds are
  immutable.
- Any settlement member requires **every** member of that settlement, else 422
  `incomplete_settlement`. Members need an identical effective **instant** (offset
  spellings may differ), else 422.
- **Precedence:** item errors in input order → settlement completeness → current available
  funds → historical total and available at every boundary. Codes:
  `linked_payment_immutable`, `refund_exceeds_payment`, `insufficient_funds`,
  `historical_overdraft`. Affordability uses the combined effect of all proposed
  revisions.
- A rejection changes nothing.
- 201 `{correction_batch_id, recorded_at, revisions[]}` in input order:
  - One shared `recorded_at`, strictly later than every member's previous `recorded_at`.
  - Each revision exposes `correction_batch_id`.
- Original receipts and settlement retries are unchanged. New statements reflect the
  batch; old snapshots stay frozen. A replay → 200 with the original.
- Concurrent corrections sharing any expected revision cannot both succeed.
- Must import stage 1–3 exports, keeping settlement membership, corrections and snapshots.

---

## 10. Edge cases the shipped tests do not reach (spec-derived)

The shipped files test each surface once (stage 3 ships 6 tests, stage 4 ships 5). Each
of these is written in the spec, and each is a likely hidden check:
1. **Wrong JSON type → 400 `malformed_request`.** Applies to fields such as `to_handle`,
   `payer_handle`, `participant_handles`, `email`, `password`, `display_name` and
   `final`. Amount, note and visibility are 422. Correction fields are 422 too: stage 3
   says "Invalid input is 422" for corrections, and that endpoint rule takes precedence.
2. **Key precedence:** an invalid body on a used key → 409, not 422. The body must parse
   and auth must succeed first.
3. A key reused after a 4xx is a first use on **every** idempotent path, including
   settlements, captures, corrections, refunds and batches.
4. Export/import round-trips tokens, idempotency records, settlement membership,
   authorizations, revisions and snapshots. An invalid state → 422 and leaves the
   destination untouched.
5. Settlements: entry errors in input order before funds; a 32/33 boundary; a net-zero
   ring that is affordable although one leg alone is not.
6. Split: n = 1000 handles, 0 shares producing requests, and a caller-only split.
7. Email `local@domain` with no dot is valid.
8. BHD (3 places) and JPY (0 places) formatting and decimal input in the UI.
9. **UI error elements absent from the DOM when there is no error.** The shipped tests
   use `query_selector(...) is None`.
10. **One element per testid per page.** Strict Playwright locators fail on duplicates.
11. **Latest-refresh-wins** with out-of-order responses; a lost response after commit →
    `pay-uncertain` → retry with the same key.
12. A refused payment refreshes the balance and feed; a stale pay button is removed after
    a refusal.
13. **Upgrade:** a browser signed in on stage N stays signed in after import into N+1,
    and a pending retry identity survives.
14. `expires_at == created_at + ttl` exactly (a single clock read); expiry at exactly
    `expires_at`; expiry visible on reads without any write.
15. `as_of` before a seeded payment gives the opening balance; statement opening on page 2
    covers the whole window; public third-party payments are excluded from statements.
16. `known_at` alone on `/me` (with `as_of` defaulting to the request instant);
    `known_at` between creation and void → still held.
17. Historical overdraft uses **per-instant netting**. Settlement members share one
    instant; checking one event at a time falsely rejects.
18. Historical overdraft includes **available** (holds), not only totals.
19. Correction or batch below the refunded total → 422 `refund_exceeds_payment`.
20. A batch shared `recorded_at` strictly after every member's previous one; effective
    instants compared as instants, not strings.
21. Concurrency at 50 in flight under 2 vCPU: no 5xx, every response within 5 s (password
    hashing cost matters), and serializable results.
22. `stage-2/` must fail suite 3 and `stage-1/` must fail suite 2 (overshoot), while
    remaining genuine carry-forward copies.

---

## 11. Current development implementation — findings

The code audited is this repository at `5ee1380`: a Python FastAPI service, one JSON-blob
SQLite store, identical `core.py`/`server.py` in every stage folder, gated by `stage.py`.

### 11.1 Fixed this session (commit `5ee1380`, reproduced before and after)
- The stage-2 pay form threw a TypeError and never submitted.
- Integral floats (`500.0`) were stored and returned as floats in authorizations,
  captures, corrections and batches.
- Historical `held` counted an expired hold whose expiry had not been persisted yet.
- Lists were sorted by timestamp string; mixed ISO formats came out out of order.
- Non-object batch items → 500 (now 422).
- The statement snapshot overwrote the whole state; it now writes atomically.
- UI: added `logout-button`; `split-share-{h}` text is now exactly the amount, which
  matches spec and shipped tests; the Reserve link is hidden before stage 2.

### 11.2 Still open — reproduced against the `5ee1380` Docker image (2 vCPU / 2 GiB)
| # | Spec | Expected | Observed |
|---|---|---|---|
| 1 | S1 §5 | `to_handle: 123` → 400 `malformed_request` | 422 `validation_failed` |
| 2 | S1 §5 | `participant_handles: "ada,bob"` → 400 | 422 |
| 3 | S1 §5 | signup `display_name: 7` → 400 | 422 |
| 4 | S1 §6 | signup `dee@localhost` → 201 | 422 (the regex requires a dot) |
| 5 | S2 | `expires_at − created_at` = 600 s exactly | 600.000065 s (two clock reads) |
| 6 | S3 | `/me?known_at=K` alone shows the balance known at K | known_at ignored (9600 instead of 9000) |
| 7 | S3 | unrelated correction after a same-instant settlement succeeds | 5/8 runs → 409 `historical_overdraft` (per-event, not per-instant) |
| 8 | S3 | held at `known_at` before a void = 700 | 0 (the void is applied regardless of `known_at`) |
| 9 | S4 | single correction below the refunded total → 422 `refund_exceeds_payment` | 201 |
| 10 | S4 | batch correction below the refunded total → 422 | 201 |
| 11 | S2 UI | `pay-error` absent after a successful pay/replay (shipped `test_submitting_the_pay_form_twice_moves_the_money_once`, `test_changing_the_form_first_is_a_different_payment`) | present in the DOM, hidden |
| 12 | S2 UI | `pay-uncertain` absent when the outcome is known | present, hidden |
| 13 | S2 UI | `auth-error` present only when there is an error | present, hidden |
| 14 | S2 UI | one `request-error` on `/requests` | 2 elements (strict-locator failure) |
| 15 | S2 UI | a refused payment refreshes the balance | balance not refreshed (500 shown, 200 actual) |
| 16 | S2 UI | `wallet-held` visible when held > 0 | populated but hidden (the parent stays `display:none`) |
| 17 | S2 UI | available is the headline | total at 42 px, available at 18 px |

Passed in the same probe runs:
- 50 concurrent logins: worst response 4.06 s against a 5 s budget. That margin is thin.
  PBKDF2 at 180k rounds runs inside the global lock on the event loop.
- No horizontal scroll at 375 px.

### 11.3 Design risks found by reading, not yet reproduced
- Historical overdraft ignores holds (spec: total **and available**).
- Import validates only track, version and a `users` dict; an incomplete state is
  accepted and can produce 5xx later.
- Reset rejects fixtures whose derived opening balance is negative. The spec says seeded
  history is consistent, so this is probably harmless, but it is not a stated rule.
- `from >= to` on `/statement` → 422. The spec says nothing about `from == to`.
- A request for a 0 share cannot be paid: the amount validator requires ≥ 1. The spec
  says nothing about paying it.
- Every write rewrites the whole state blob. Latency grows with state under 50-way load.
- Identical gated code in every folder passes the mechanical overshoot probe. It
  contradicts the guide's intent ("copying your final answer back into every folder
  defeats that"), and it cannot come from a genuine per-stage Band run.

### 11.4 Evidence limits
- The official harness and suites have **not been executed** against this code in this
  session. The table above comes from my own probes that replicate spec statements and
  shipped assertions.
- The historical "147 / 10+25 / 6 / 5 passed" figures equal the **shipped** test counts
  exactly, i.e. 79% / 35% / 9% / 16% of the graded suites.

---

## 12. What the current code is useful for

It is a reference, not a submission. Lessons for the band's own implementation:
- Serialize every mutation through one transaction.
- Treat an idempotent replay as a lookup before validation.
- Make revision selection a pure function of `(known_at, as_of)`.
- Fold expiry into every read.
- Put the UI key in memory and derive it from the form signature.

The band must write its own code from the spec, in the room.

---

## 13. Problems in this repository's non-code artifacts

These matter if anything is reused.
- **Mandates** (`mandates/*.md`):
  - Scanned against `harness/vocabulary.py`: 0 banned-token hits.
  - All 7 files say `Harness: official Pocketful harness`. That names the track and is
    the wrong field meaning: it should be the seat runtime, e.g. `Claude Code` or `Codex`.
  - The model lines are unverified. `forgefreshbuilderclaude.md` gives a descriptive
    string, not an exact id.
  - Seat names must match the fresh room's `senderName`s.
  - Write new generic mandates for the fresh run.
- **FACTORY.md** contradicts the mandates: GPT-5.5 is named for the builder, and it says
  "Claude Code fallback unavailable" while a Claude mandate exists. It has no measured
  time or cost.
- **README.md** historical counts are shipped-only.
- **`room.json`** is absent. It must come only from the fresh run's full-session download.
- **History:** `5ee1380` and `c9f48db` were authored outside Band. Do not carry this
  history into the result repository.

---

## 14. Unverified

- Hackathon website rules, submission form fields and current announcements
  (WEBSITE_ACCESS_UNVERIFIED).
- Public spec clarifications posted in the BAND Discord.
- Official harness results for any code, in host or isolated mode.
- Why the guide on `main` differs from `kickoff-manifest.json`, and what changed.
- Band Desktop seat names, harness labels and exact model ids for the fresh run.
- Hidden-suite behaviour for the ambiguous items in §11.3.

---

## 15. Prioritized checklist for the fresh Band run

**Before dispatch (human, allowed):**
1. Pull the latest kickoff repo. Re-read the participant guide diff and check the BAND
   Discord for clarifications. Resolve every spec question now; none may be asked
   mid-run.
2. Configure ≥ 3 Band Desktop seats, e.g. coordinator, implementer and reviewer; a
   separate UI implementer and an adversarial tester are optional. Verify `@handle`
   delivery both ways.
3. Write **generic** mandates named after the seats, each starting with `Harness: <as Band
   shows it>` / `Model: <exact id>`. Run `harness check` against a scratch repo holding
   just the mandates and README/FACTORY stubs to catch vocabulary hits.
4. Build generic factory rules into the mandates, with no track words:
   - The reviewer turns every normative sentence of the supplied spec into a numbered
     checklist and tests each item, beyond the shipped checks.
   - Reject without a passing isolated harness run.
   - Every error element appears only on error; one element per test id.
   - Every stage folder is a copy of the previous one, widened, with no `.git`.
   - Post the full commit SHA with each handoff.
   - Never amend or rebase.
5. Create the fresh result repo, e.g. `band-work/result`, with Git identities per seat.
   Give seats its absolute path. Ensure Docker, Python 3.12+ and the Playwright Chromium
   are available to the reviewer.
6. Prepare the dispatch text: the complete spec for each stage (verbatim), result repo
   path, harness commands, and the stage folder rule. Do not include this handoff's §10
   or §11 as hints. They are debugging knowledge from a development run, and pasting
   them risks being judged as steering. Let the factory's generic review rules find them.

**Dispatch** (once, per stage or all four): then no human input until the coordinator's
final report.

**What the band's work must satisfy** (use this to judge the factory's design and to
verify after the run, not to steer):
- P0 stage 1: the 400 vs 422 type rule; key precedence; per-user keys scoped by path;
  the failed-key rule; atomic settlements with input-order errors; export/import
  preserving tokens and idempotency; no 5xx at 50-way load in 2 vCPU; fast password
  hashing off the critical lock.
- P0 stage 2: exact testid semantics (absent vs hidden, one per page); available as the
  headline; `wallet-held` visible or absent; decimal parsing; stable pay key with a replay
  on resubmit; latest refresh wins; refusal refresh; `pay-uncertain` on a lost response;
  upgrade from a stage-1 export with the browser still signed in; exact `expires_at`;
  expiry on read.
- P0 stage 3: revision selection; half-open statements with a frozen snapshot;
  per-instant, holds-aware historical overdraft; historical holds honouring `known_at`
  for every event; `/me?known_at` alone.
- P0 stage 4: refund rules; correction not below refunds; batch precedence order; one
  shared `recorded_at`; settlement completeness with instant equality; imports from
  stages 1–3.
- Packaging: each folder builds from a clean clone; `RUN.md` works by hand; no runtime
  network or CDN; `stage-N` fails suite N+1.

**After the run (human):**
1. Download the full-session `room.json`, read it, and check it for secrets.
2. Write README.md and FACTORY.md, including measured time and cost and what failed.
3. `git clone` fresh, then `harness check` and `harness run --all --mode isolated`.
4. Follow every RUN.md by hand and use the UI at 375 px and on desktop.
5. Push to a public repo; submit the URL, presentation and video before **Mon Oct 5 23:59
   PDT**.
