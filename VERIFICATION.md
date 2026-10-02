# Final Verification Record

Audit date: 2026-10-02

## Official participant suites

| Surface | Result |
|---|---:|
| Stage 1 | 147 passed |
| Stage 2 | 34 passed in the ordinary run; the required preceding-stage upgrade check also passed separately (1 passed) |
| Stage 3 | 6 passed |
| Stage 4 | 5 passed |

The Stage-2 isolated upgrade check was run with a preceding Stage-1 base URL because the organizer sample intentionally requires that input.

## Project-owned red-team suite

| Surface | Result |
|---|---:|
| Stage 1 | 70 passed |
| Stage 2 | 14 passed |
| Stage 3 | 17 passed |
| Stage 4 | 11 passed |

Additional focused check: unauthenticated write with a missing idempotency key and 50 concurrent login attempts both passed in the final Stage-1 hardening run (2 passed in 10.05s). The full Stage-1 red-team suite also passed afterward.

## Final hardening covered

- Authentication is resolved before the idempotency-key requirement on keyed writes.
- Wrong JSON value types return the documented malformed-request error rather than being silently coerced.
- known_at-only historical reads select revisions by recorded time.
- Statements preserve exact empty [from,to) windows and echo known_at.
- Normal payment creation timestamps are monotonic under rapid/concurrent writes, avoiding ambiguous historical ordering.
- Non-open authorizations expose zero remaining amount.
- Historical corrections are checked against historical nonnegative totals and available funds.
- Seeded payment history that would produce a negative opening balance is rejected.
- PBKDF2 login verification uses 60,000 rounds after an observed concurrency audit so the final focused 50-login check stays within the organizer timeout on this workstation.

## Repository integrity

- git diff --check was clean during the final audit before the release commit.
- Stage 1-4 folders contain ordinary source trees; no nested Git repositories are intentionally used.
- The final submission keeps the Band room export in room.json.
- No provider credentials or live access tokens are intentionally stored in the repository.

## Container note

Docker was not available on the audit workstation (docker was not present), and WSL was not configured for Docker Desktop. Therefore no Docker-isolated pass is claimed in this record.

## Release

The public repository is:

https://github.com/arulmuruganmcse2024-tech/pocketful-dark-factory-final
