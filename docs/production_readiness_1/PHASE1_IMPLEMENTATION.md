# Phase 1 — Four-part workflow implementation record

**Baseline:** Phase 0 commit `0b2e18cb8bd6283774bda028c883ca28b85fa544`  
**Implementation commit:** `8ea909baf2011b11278fda9e58f4a8d996936139`.  
**Scope:** safe partial draft visibility and accurate partial-success reporting. No production controller or state authority added.

## Change 1 — Partial CopyV1 is visible to draft templates

Before this change, `template_engine._load_copy_v1` always called `read_copy_artifact(require_complete=True)`, and every row lookup required a present AI-provenance copy row. This made the draft path share the formal submit-ready completeness gate.

The revised behavior is deliberately asymmetric:
- `draft`: accepts an incomplete but current CopyV1 artifact; known rows are validated normally; missing child/parent rows remain blank and are exposed by existing field/listing-data audits.
- `submit_ready`: still requires a complete CopyV1, exact family row inventory, parent row and existing provenance/quality checks.
- Unexpected row identities, malformed present rows, stale fingerprints and provenance errors still fail closed.
- Draft output is not promoted to publish/release/delivery eligibility.

This does not create synthetic copy, infer missing facts, or weaken Amazon submission rules.

## Change 2 — Do not report success when the selected family run had failures

A family release can be complete while a selected stage had a recorded failure (notably a draft-only run where release readiness and copy completeness are separate). The final workflow projection now requires both order-release completion and no unresolved run failures before returning `success`; otherwise it reports `partial_success`. The detailed task/stage evidence remains available.

## Tests added without increasing the default case count

Assertions were added inside existing default-suite test methods:
- incomplete CopyV1 can be read for draft inspection but is rejected by the complete reader;
- missing copy row is represented as blank only when the caller explicitly allows draft behavior;
- the same missing row remains an error by default;
- family-release completion cannot mask a recorded run failure in the workflow status.

The curated suite's declared case count remains 100 (the runner limit is 100); the test assertions were folded into existing test methods. This was checked statically from the module AST/method inventory, not by executing the suite.

## Verification boundary

The GitHub-connected editing environment cannot execute the repository's Python suite or inspect generated workbooks. The targeted tests and prescribed `scripts/run_production_tests.py` have **not been run here**. Codex must run the targeted tests and the prescribed suite before this phase is accepted. No real API call, paid request, upload, production ledger operation, or generated-image quality claim was made.

## Remaining Phase 1 work

- Prove child/role-local currentness for all Brief sub-owners under partial planning failures.
- Prove copy-group retry does not re-run successful fragments under mixed work-unit scheduling.
- Prove image candidates/QA/publication continue for unaffected roles when one role fails.
- Add integration fixtures for one incomplete child and one incomplete copy group across the actual template builder, not only the copy reader/helper.
