# Pocketful — Dark Factory Final Package

This repository contains the cumulative Pocketful implementation for the Dark Factory challenge.

**Status: development and audit repository, not the judged submission.** See
`FINAL_BAND_HANDOFF.md` for the official requirements, the audit findings and the plan
for the fresh Band Desktop run.

## Repository shape

- stage-1/ through stage-4/: cumulative, independently runnable services.
- Each stage contains Dockerfile, RUN.md, core.py, server.py, stage.py and requirements.txt.
- core.py and server.py are byte-identical in every stage folder. stage.py sets the folder's
  stage (POCKETFUL_STAGE overrides it), so later-stage endpoints return 404 in earlier stages.
- tests/: project-owned regression and adversarial tests (not the official participant suite).

## Verification

Official participant suite results are recorded in CONTINUATION.md together with the commit
they were run against. Results from earlier revisions are historical only:

- Stage 1 official participant suite: 147 passed (earlier revision).
- Stage 2 official sample suite: 10 passed; official UI suite: 25 passed (earlier revision).
- Stage 3 official sample suite: 6 passed (earlier revision).
- Stage 4 official sample suite: 5 passed (earlier revision).

Project regression suite:

    pip install -r stage-4/requirements.txt -r tests/requirements.txt
    python -m pytest tests -q

The suite starts each stage folder's service itself. To target running services instead
(for example the Docker images), set POCKETFUL_TARGET_1 .. POCKETFUL_TARGET_4 to their base URLs.
The browser test uses Playwright's Chromium; set POCKETFUL_CHROMIUM to use another binary.

## Reproducibility

Run a stage by following its RUN.md. The service is self-contained at runtime and does not require outbound network access.

For the official event submission, the final Band Desktop full-session download must be saved unchanged as room.json at the repository root before upload.
