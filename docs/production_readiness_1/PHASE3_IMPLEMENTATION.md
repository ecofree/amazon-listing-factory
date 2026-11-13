# Phase 3 — Resource accounting implementation record

**Baseline:** commit `10cc3e93db8d0ac83c26b1faaa32a15e7d00a7ce`.  
**Scope:** keep long-running host image-resource accounting bounded without deleting audit evidence.

## Confirmed issue

`core/image_resources.py:_pending_response_bytes` excluded terminal native `.bin` bytes for `finalized/rejected_content`, but still counted terminal `.http` and `.partial` envelopes. Once a worker exited, `_reservations()` could retain a zero-memory stale reservation indefinitely because its terminal envelope remained on disk. This did not delete data, but caused the shared reservation JSON to grow and repeatedly inspect already-finalized work.

## Implemented behavior

- Read the matching response receipt for each `.bin`, `.http` and `.partial` file.
- Exclude payload bytes from pending-resource reservations when the bound receipt is terminal: `finalized`, `rejected_content`, `known_failure`, `output_rejected` or `superseded`.
- Preserve every terminal receipt and payload file as immutable audit evidence.
- Continue counting `prepared/submitted/received/resend_authorized` response bytes as pending.
- Continue using actual filesystem free space as the final disk admission check.

## Test coverage

Added assertions to the existing default-suite root-cause fixture:
- finalized native and HTTP envelope bytes do not remain pending reservations;
- received native/envelope bytes remain counted.

No new default test method was added. Tests were not run in this environment.

## Remaining Phase 3 work

- 10+ mixed-order fairness and worker saturation test.
- Dispatcher restart, simultaneous dispatcher and stale worker fencing.
- 72-hour disk/memory/SAM resource measurement.
- Verify cleanup never removes referenced source, receipt, candidate, QA or delivery evidence.
