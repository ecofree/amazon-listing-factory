# Production Readiness 1.0 — Architecture Baseline

**Baseline branch:** `codex/model-native-image-refactor`  
**Baseline commit:** `a74dc61542360ca1ae8ccb30194380d2921cafc9`  
**Status:** Phase 0 architecture specification; not a live-production acceptance.

## 1. Product objective

The system accepts an explicitly authorized listing order (seed ASIN, seller/brand identity, marketplace, category, business facts, target family and spending policy), executes independent work that is ready, preserves successful artifacts, recovers only when safe, escalates decisions that require human authority, and delivers a verified listing package. A blocked order must not stop unrelated orders. An uncertain paid request must never be treated as unsent.

“Unattended” does not mean forcing every order to success. It means the system autonomously advances safe work, isolates failures, waits on external uncertainty, and asks a human only for decisions that require authority or unavailable evidence.

## 2. Baseline implementation and owners

The current repository already has one production stage controller and one batch dispatcher. Preserve these authorities; do not add parallel controllers.

| Responsibility | Existing authority |
|---|---|
| Order admission / initialization | `core/production_batch.py:create_batch`, `core/job.py` |
| Batch leases, order identity, spending admission, completion holds | `core/batch_ledger.py` |
| Stage execution, job lock, stage sequencing and run summary | `core/production.py:run_job` |
| Product identity and catalog facts | `ProductFamilyV3`, `core/product_family.py` |
| Frozen family/child scope | `RunScopeV5`, `core/run_scope.py` |
| Copy generation and copy artifact | `core/copy_polish.py`, `core/copy_writer.py`, `CopyV1` |
| Downloaded source bytes | `core/asset_manager.py`, `DownloadManifestV2` |
| Source role observations | `core/final_source_intents.py`, `FinalSourceIntentV2` |
| Child visual plan and planning operations | `core/visual_design_kit.py`, `Planning Journal`, `VisualDesignKitV20` |
| Image edit task and immutable prompt | `core/image_tasks.py`, `core/image_prompt_compiler.py` |
| Provider execution and native response | `core/image_generation.py`, `core/image_generation_executor.py`, `core/image_provider_*` |
| Candidate identity and pixels | `CandidateManifestV9`, `core/candidate_state.py` |
| Hard-fact QA and evidence | `core/image_qa.py`, `QAEvidenceV5` |
| Human visual/factual decisions | `HumanReviewV5` |
| Release eligibility | `core/release_manifest.py`, `ReleaseManifestV6` |
| Image publication and URL verification | `core/publish.py` |
| Amazon workbook plan and writing | `core/template_engine.py`, `core/template_*` |
| Immutable delivery package | `core/delivery_package.py` |
| Operator view and review actions | `core/batch_console.py`, `core/assets/batch_console.html` |

The artifact authorities above are not interchangeable. Job State records execution state; it does not prove candidate identity, QA approval, release eligibility, or delivery.

## 3. Target execution model

Keep `production.py` as the only stage controller and `production_batch.py` as the only persistent order dispatcher. The stage list remains the public maintenance interface. Internally, each owner exposes independently settleable work units and explicit dependency/currentness checks. Do not add a second DAG engine or duplicate artifact authority.

The target is dependency-aware progression across the existing owners:

- Fetch establishes the known family and catalog facts.
- Copy can run when its fact/source contract is sufficient.
- Source-image download can run independently once source URLs are known.
- Classification depends on downloaded source bytes.
- Visual planning depends on current facts and required source observations.
- ImageTask/Prompt compilation depends on accepted planning output.
- Generation depends on one current executable task and prompt.
- QA depends on a specific candidate plus bound same-child facts/references.
- Publish depends on current release eligibility and approval.
- Submit-ready template depends on complete family/business/copy/image/URL/template contracts.
- Delivery depends on a current verified workbook and current delivery assets.

Copy and image production are independent branches until template assembly. Within each branch, child/group/role/candidate work must retain its own identity and terminal state. A sibling failure may prevent a family-level deliverable, but must not erase or re-run successful sibling work.

## 4. Completion is a projection, not one boolean

Expose separate states/counts for:
1. order accepted and authorized;
2. known family inventory / facts;
3. copy group and child copy readiness;
4. image planning, generated candidates, QA and publication by child/role;
5. listing-ready (all required family, business, copy, template, image URL gates);
6. all-frozen-output/order complete;
7. delivery package committed and verifiable;
8. platform submission/acceptance, if ever implemented as a separate explicit capability.

A completed selected stage range is not a delivered order. A candidate file is not a QA pass. A QA pass is not a release approval unless currentness rules say so. An uploaded object is not a current verified URL. A workbook is not an accepted Amazon submission.

## 5. Failure containment principles

- Scope failures to the smallest owner: source, child, copy group, image role/task, candidate, URL, workbook field or order.
- Keep immutable source bytes, request/response receipts, accepted candidates, human decisions and delivery revisions.
- Retry only errors whose owner proves the original request was not sent or whose provider contract makes retry safe.
- Unknown POST outcomes remain fenced to their original logical owner and request identity until reconciled.
- Waiting for human input or an external response consumes no worker slot.
- Service outage pauses only work requiring that service; already prepared work on independent services may proceed.
- Never lower hard-fact, QA, release, template or delivery gates to increase throughput.
- Never reduce frozen family/role goals to make a batch appear complete.

## 6. Operational boundaries

The production workspace, order leases, budget policy and durable receipts remain mandatory. No code path may bypass the fixed ledger or create a new spending domain to escape an unknown outcome. Configuration changes that alter execution semantics require explicit reconciliation; credential rotation alone must not invalidate unrelated factual approvals.

The console should report task-level blockers and actionable owner/reason, not invent a second status authority. It may issue only existing scoped review/reconciliation actions.

## 7. Phase 0 decision

Architecture direction is to converge the current implementation, not replace it. The first engineering changes must be selected from the gap audit and failure matrix, one owner at a time, with obsolete paths/tests removed in the same change. This document does not certify that the current implementation already satisfies the target.
