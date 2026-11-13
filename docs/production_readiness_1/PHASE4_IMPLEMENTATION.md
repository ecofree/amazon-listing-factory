# Phase 4 — Provider health and recovery implementation record

**Scope:** make existing provider health/cooldown state actionable across isolated order workers without introducing a new health service or scheduler.

## Confirmed gap

Image and visual model health is already recorded in the project-level `model_call_health_ledger.json`; image routing and Gemini client selection consult persisted cooldowns. However, `production_batch.review_revision()` only included provider configuration/credential semantics in its wake fingerprint. When an order exhausted automatic retries during a provider cooldown, the cooldown could expire without any new request or configuration change. The exception therefore remained unchanged and the dispatcher did not requeue the original order.

## Implemented behavior

For retryable failures owned by provider-dependent stages (`classify`, `brief`, `generate`, `qa`):
- read health entries for configured providers in the relevant scopes;
- include the current `cooldown_active` bit (and last status) in the existing order review revision;
- when a cooldown expires, the review revision changes and the existing dispatcher requeues the same order once;
- no new order, budget, receipt, provider request or retry permission is created by this wake.

Unknown remote outcomes, local commit pending, contract blockers, budget blockers and local tool failures remain excluded from this automatic wake path. Existing provider priority, role policy, fallback-only routing, per-provider concurrency and request admission are unchanged.

## Test coverage

Added an assertion to the existing root-cause test path with a synthetic provider registry and patched cooldown state:
- same failed order revision while cooldown is active;
- changed revision when that provider cooldown expires.

No new default test method was added. Tests were not run in this environment.

## Remaining Phase 4 work

- Exercise 429/403/5xx/timeout and disabled-route behavior across separate worker processes.
- Verify fallback routes have matching role, reference-count, protocol and output capabilities.
- Verify provider-wide outage does not consume repeated paid calls from multiple orders.
- Verify recovery wakes the original order and does not retry unknown requests.
- Run authorized provider smoke tests separately; registry presence and synthetic circuits do not prove live connectivity.
