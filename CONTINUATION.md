# Continuation

Last update: 2026-09-29 (Claude Code cloud session, second pass)
Branch: `claude/lucid-mccarthy-14whqy`
Code revision audited: `5ee1380` (no code changed in this pass)
Docs commits: `c9f48db`, then this pass's handoff commit (see `git log`)

## Status in one line
Development and audit evidence only. **Not submission-ready, and this repository must
not be the judged submission.** The judged run needs a fresh Band Desktop room and a fresh
result repository. See `FINAL_BAND_HANDOFF.md`.

## Completed in this pass
1. Read the official participant guide, all four Pocketful specs, all 11 shipped Pocketful
   test files, and the harness checker, vocabulary, CLI and report modules. Read as plain
   text from `raw.githubusercontent.com`; nothing executed. 21 of 22 files match
   `kickoff-manifest.json` sha256. The guide on `main` differs from the manifest (revised
   after kickoff).
2. Wrote `FINAL_BAND_HANDOFF.md`:
   - requirements for each stage;
   - deployment limits;
   - gates, the claim/overshoot/chain rules and the banned mandate vocabulary;
   - Band teamwork rules;
   - edge cases missing from the shipped tests;
   - current defects;
   - artifact problems;
   - a prioritized checklist for the fresh run.
3. Reproduced 17 spec-derived defects in the `5ee1380` code using scratch probes against
   the Docker image at 2 vCPU / 2 GiB. Nothing was fixed, per instruction. See handoff
   §11.2.

## Exact evidence (this pass)
- Shipped Pocketful test counts (collected, AST-counted from the official files): stage 1
  = 147, stage 2 = 35 (10 sample + 25 UI), stage 3 = 6, stage 4 = 5. The historical
  "147 / 10+25 / 6 / 5 passed" figures therefore covered the shipped subset only (79% /
  35% / 9% / 16% of each graded suite, per the guide).
- Spec API probe on the stage-4 image: 10 DEFECT, 1 PASS (50 concurrent logins; worst
  4.06 s against the 5 s budget). Plus 1 DEFECT from a batch-only recheck.
- UI probe on the stage-2 image: 7 DEFECT, 2 PASS (`wallet-held` absent at zero; no
  horizontal scroll at 375 px).
- Correction to the previous pass: the stage-2 pay-form repair in `5ee1380` leaves
  `pay-error` hidden in the DOM. Two shipped UI tests assert it is absent
  (`test_submitting_the_pay_form_twice_moves_the_money_once`,
  `test_changing_the_form_first_is_a_different_payment`). The project's own
  `tests/test_regression.py` did not catch this.
- Previous pass, unchanged: `tests/` 28 passed locally and against the containers.
- Official harness or suites: **NOT RUN** (the official code is not executed in this
  session).

## Blockers
1. The judged run must happen in Band Desktop with ≥ 3 seats. It cannot be done from this
   session.
2. `room.json` must be the authentic full-session download of that fresh run.
3. WEBSITE_ACCESS_UNVERIFIED: the lablab.ai hackathon page has not been inspected.
4. The official harness has not been executed against any revision here.

## Unverified
- Website submission form fields and announcements; BAND Discord clarifications.
- What changed in the participant guide since the kickoff manifest.
- Seat names, Band harness labels and exact model ids for the fresh run.
- Hidden-suite behaviour on the ambiguous items in handoff §11.3.

## Files being edited
None. The tree is clean after the handoff commit.

## Next three actions (human, before the fresh run)
1. Pull the latest kickoff repo, read the participant-guide diff and the Discord
   clarifications, and settle spec questions before dispatch.
2. Configure ≥ 3 Band Desktop seats and write fresh **generic** mandates (`Harness:` as
   Band shows it, `Model:` exact id, no track vocabulary). Run `harness check` on a scratch
   repo.
3. Create a fresh result repo and dispatch the verbatim stage specs once, with no further
   input. Afterwards: download `room.json`, write README.md and FACTORY.md, clone fresh,
   run `harness check` and `harness run --all --mode isolated`, then submit before Mon
   Oct 5 23:59 PDT.

## State
- Repository stable: yes (docs-only changes in this pass).
- Safe to resume tomorrow: yes.
- Mechanically ready for submission: NO.
