# Pocketful — Dark Factory

This repository is the submission result for the **Pocketful** track of the WeAreDevelopers x BAND Dark Factory hackathon.

It contains the factory description, the recorded Band room, and the four cumulative service stages.

## Repository map

- `FACTORY.md` — factory design, seat ownership, handoffs, review gates, and measured verification.
- `VERIFICATION.md` — final audit record with official and project-owned test evidence and environment limitations.
- `mandates/` — one generic mandate for each seat represented in the submitted room.
- `room.json` — the full-room Band session record used as collaboration evidence.
- `stage-1/` — HTTP API and atomic/idempotent money movement.
- `stage-2/` — browser product and authorization/hold lifecycle.
- `stage-3/` — historical views, revisions, corrections, and snapshots.
- `stage-4/` — refunds and atomic correction batches.
- `tests/` — project-owned regression/adversarial checks; these are supplemental and are not the organizer's hidden suite.

Each stage is independently runnable and contains its own `Dockerfile` and `RUN.md`.

## Verification performed

The final working tree was checked against the organizer-provided participant suites:

- Stage 1 suite: 147 passed.
- Stage 2 suite: 35 passed, including browser checks.
- Stage 3 suite: 6 passed.
- Stage 4 suite: 5 passed.

The project-owned red-team suite passed cleanly after the final hardening changes: Stage 1 `70 passed`, Stage 2 `14 passed`, Stage 3 `17 passed`, and Stage 4 `11 passed`. The focused Stage-1 check for auth-before-idempotency and 50 concurrent logins also passed `2 passed in 10.05s`.

See `VERIFICATION.md` for the complete final audit record and the distinction between official participant checks and project-owned adversarial checks.

The official isolated Docker run could not be certified on the Windows workstation used for the final local audit because Docker Desktop required WSL and WSL was not installed/configured there. The repository therefore does not claim an isolated-container pass that was not actually observed.

## Running a stage

See the `RUN.md` inside each stage folder. The service is self-contained at runtime and does not require an external banking integration.

For local regression checks from the repository root:

```text
python -m pytest tests -q
```

For organizer harness checks, use the supplied `harness` from the participant repository and point it at the desired stage folder.

## Notes on provenance

The Band room contains the factory's staged planning, implementation, adversarial testing, and verification conversation. The stage source is kept as ordinary files inside this repository rather than nested Git repositories.

No credentials or live provider tokens are intentionally stored in this repository.
