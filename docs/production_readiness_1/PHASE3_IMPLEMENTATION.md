# Phase 3 — Batch scheduling and resource management implementation record

**Scope:** queue fairness without a new scheduler, state store or schema migration.

## Confirmed issue

The jobs table has no explicit `created_at`/queue-age column. `BatchLedger.claim()` previously selected eligible `queued/retry` rows using `ORDER BY due,id`. New jobs are initialized with `due=0`; retry jobs have a future due timestamp. Once retries became eligible, a continuous arrival of new due=0 orders could keep those older retries behind newer admissions.

## Implemented change

- `due <= now` remains the eligibility condition.
- Eligible jobs are selected by SQLite admission row order (`ORDER BY rowid`).
- A future retry is excluded and cannot block a new eligible order.
- Once an older retry becomes due, it is considered before later admissions.
- Existing worker limit, lease fencing, retry limits, order budgets and completion holds are unchanged.
- No schema migration or additional scheduler was introduced.

This is FIFO among currently eligible enrolled production orders, not priority by order size or category. Retry attempts remain bounded by the existing policy.

## Test coverage

Assertions were added to the existing `test_dns_resolution_failure_is_retryable` path via `verify_batch_queue_fairness`:
1. An older retry whose due time is in the future does not block a newer queued order.
2. Once that retry is due, it is claimed before a later new order.

No new default test method was added; the suite case count remains unchanged. The Python test suite has not been executed here.

## Remaining Phase 3 work

- Measure queue wait and per-order service time under 10+ mixed synthetic orders.
- Prove a repeated retrying order cannot occupy every worker indefinitely (existing max attempts must be included).
- Test dispatcher restart, expired lease, stale worker process tree termination and simultaneous dispatchers.
- Measure memory/disk/SAM process pressure and safe cache cleanup.
- Decide whether persisted enqueue timestamps are needed before any future schema migration; current implementation intentionally avoids schema version change.
