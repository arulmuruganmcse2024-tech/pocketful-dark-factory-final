# FACTORY.md

## Factory intent

The factory uses dedicated roles for specification decomposition, implementation, adversarial review, release criticism, repair and independent verification.

## Seats used in the development room

ForgeFreshArchitect — decomposes the official specification and invariants.
ForgeFreshBuilder — primary implementation seat.
ForgeFreshAdversary — independent failure/concurrency/edge-case reviewer.
ForgeFreshCritic — release blocker and evidence reviewer.
ForgeFreshRepairer — smallest verified defect repair.
ForgeFreshVerifier — independent final verification.

## Collaboration rules

Requirements are handed off between named seats with Band @handle mentions. Implementation is reviewed from committed revisions. Repairs are made only after an independently observed failure. Verification is performed against the post-repair revision.

## Harness

Harness: official Dark Factory Pocketful participant harness.

## Model configuration

The primary Codex seat was configured for GPT-5.5 after the default Codex runtime hit its account usage limit. Other seats were created with Band-managed Codex defaults. The fresh Claude Code fallback was unavailable because Claude Code was not signed in on the workstation.

## Runtime constraints

Docker Desktop was not available on the workstation, so isolated Docker execution could not be honestly certified locally. Host-mode official participant tests were executed and the Dockerfiles were prepared for the judge environment.

## Public-release hygiene

The release tree excludes local databases, caches, Python bytecode, debug scripts, secrets and nested .git folders.
