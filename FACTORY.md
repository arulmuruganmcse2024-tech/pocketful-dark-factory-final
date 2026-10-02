# Factory

## Purpose

The factory is a domain-independent multi-seat software-production workflow. A coordinator decomposes the supplied specification, an implementation seat turns scoped work into committed changes, specialist seats attack different classes of failure, and an independent verifier makes the release decision from reproducible evidence.

The mandates are intentionally written without product-specific endpoints, fields, test IDs, or domain vocabulary so the same seats can be pointed at a different software problem.

## Submitted seats

| Seat | Role | Harness | Model |
|---|---|---|---|
| PocketfulLead | coordination, architecture, stage gates | Band Desktop + Claude Code CLI | Claude Code default |
| PocketfulBuilder | implementation and integration | Band Desktop + Claude Code CLI | Claude Code default |
| PocketfulRedTeam | adversarial and concurrency review | Band Desktop + Claude Code CLI | Claude Code default |
| PocketfulHistorian | temporal/state-history specialist | Band Desktop + Claude Code CLI | Claude Code default |
| PocketfulUIReviewer | browser/recovery review | Band Desktop + Claude Code CLI | Claude Code default |
| PocketfulVerifier | independent release verification | Band Desktop + Claude Code CLI | Claude Code default |

The model/harness labels above describe the seats represented in the submitted Band room. The room record is the source of truth for the actual collaboration trace.

## Work allocation

The coordinator owns decomposition and sequencing, not product implementation. The Builder owns product-source integration. RedTeam, Historian, and UIReviewer work as independent challenge seats and return reproducible findings. The Verifier is the release gate and is expected to test the committed tree rather than relying on another seat's claims.

The result repository is cumulative: each later stage is copied from the accepted previous stage and then extended. Earlier stage behavior remains independently runnable.

## Handoff protocol

Every delegated handoff names the receiving seat and carries the complete scoped requirements needed to act without inferring missing details from chat history. The implementer returns a concrete revision plus the exact verification commands and observed results. Reviewers report defects with enough evidence to reproduce them. A repair is accepted only after the relevant check is rerun.

## Failure handling

The factory treats a passing visible test as evidence, not proof. Specialist review specifically targets concurrency, retries, malformed input, exact time boundaries, stale state, historical views, immutable records, atomic multi-item operations, and interactions between independent invariants.

When a failure is found, the workflow preserves the evidence, repairs the smallest necessary surface, and reruns the affected checks. Release claims are made only from observed results.

## Verification evidence

The final local audit established:

- 147 Stage-1 checks passed.
- 35 Stage-2 checks passed, including Playwright browser behavior.
- 6 Stage-3 checks passed.
- 5 Stage-4 checks passed.
- 33 project regression checks passed after final hardening.
- 4 focused hardening checks passed.
- `git diff --check` reported no whitespace errors.

The final audit also checked that the four stage folders have matching source revisions and that the stage-specific runtime gate prevents later-stage behavior from being exposed in earlier folders.

## Environment limitation

The Windows machine used for the final audit did not have WSL installed. Docker Desktop was installed and started, but the Docker engine could not become usable without that prerequisite. Because of that environment constraint, isolated Docker execution is not represented as a passed result in this file.

## Reproducibility

Build and execution instructions are inside each `stage-N/RUN.md`. The submitted tree is intended to be clonable by a judge without requiring membership in the Band room.
