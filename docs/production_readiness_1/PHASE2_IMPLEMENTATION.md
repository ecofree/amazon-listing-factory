# Phase 2 — Request lifecycle and recovery implementation record

**Baseline:** Phase 1 branch head before this change.  
**Scope:** safely distinguish a worker crash before the durable transport checkpoint from a request whose external outcome may be unknown.

## Confirmed gap

`core/service_response.py:perform_request` writes a durable receipt with `status=submitted` and `submission_stage=preparation` before the request owner enters its transport. The transport then calls `start_submission()`, whose observer persists `submission_call_started` before the HTTP library is entered.

Before this change, `_records()` recovered saved response bytes but did not settle a dead worker's receipt that remained at `preparation`. It therefore appeared as pending/unknown and fenced the logical owner, even though the persisted lifecycle proved no transport call had started.

## Implemented behavior

When reading relevant receipts with recovery enabled, the owner now changes a receipt to `known_failure` / `known_not_executed=true` only when all conditions hold:
- status is `submitted`;
- no response file exists;
- `submission_stage` is exactly `preparation`;
- a PID and process start time are bound to the receipt;
- that exact process is confirmed dead.

The receipt is marked `not_sent`; no new request or spending permission is created by reconciliation. `retry_authorized()` now uses the same recovery path before deciding whether an original owner is safely retryable.

A receipt at `submission_call_started`, `unknown`, or with saved response bytes is not converted to known-unsent. Existing no-duplicate rules remain in force.

## Test coverage added

Assertions were added to the existing `verify_retry_grant` fixture (no new default test method):
- orphaned pre-submission receipt is recognized as known-unsent;
- the same logical owner can perform one new attempt through the normal request owner;
- existing received/unknown authorization behavior remains covered by the surrounding fixture.

The default suite case count is unchanged. Tests were not executed in this environment.

## Safety assumptions and verification boundary

All current `perform_request` owners must persist `start_submission()` before entering their external transport. Current inspected owners: Apify, copy writer, OCR scanner and visual semantics via the Gemini transport. This must remain a code-review invariant for any future owner.

The Python test suite and real process-kill test have not been run here. Codex must kill a worker both before and after the checkpoint and inspect the exact receipt/ledger state. No real API call, paid request, production ledger mutation or upload was performed.

## Remaining Phase 2 work

- Inject crashes after reservation, after checkpoint, after headers, during body receipt, after response save, and before artifact/task-state commit.
- Audit native image generation receipts and QA receipts for the same lifecycle guarantees.
- Audit object-store PUT and URL receipt recovery across the remote/local commit boundary.
- Prove stale worker fencing after lease expiry and dispatcher restart.
