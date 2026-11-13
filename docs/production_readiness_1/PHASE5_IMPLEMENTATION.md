# Phase 5 — Quality and delivery gate audit

**Baseline:** branch after Phase 4 provider wake-up change.  
**Audit type:** static owner/contract review; no live images, paid provider calls, uploads or real workbook submissions.

## 1. Decision

No QA, release, template or delivery gate was weakened or replaced in this phase. Current code already has the correct high-level separation:
- QA records source-bound factual/publishing evidence, not aesthetic approval.
- Inconclusive evidence remains a human-review condition; uncertainty is not promoted to pass.
- Release eligibility consumes current candidate, QA and human-decision authorities.
- Publishing consumes approved release rows and verifies the exact uploaded bytes/URL policy.
- Submit-ready template generation requires current full-family copy, family/variation/business contracts and required current published images.
- Delivery commit requires a current submit-ready workbook, no blocking template audit, required current URLs, and a hash-bound package revision.
- Current delivery verification checks source hashes and required URL freshness; an archived package is not an Amazon acceptance receipt.

Relevant owners: `image_qa.py`, `qa_evidence.py`, `release_manifest.py`, `publish.py`, `template_engine.py`, `template_contract.py`, `template_package.py`, `delivery_package.py`.

## 2. Specific invariants retained

1. A candidate file alone never qualifies for release.
2. A candidate's QA result is bound to its bytes, task/prompt, facts, same-child references and policy.
3. Human rejection is not overwritten by a later transport or unrelated QA event.
4. A missing `vision_qa` route cannot auto-pass; it yields unresolved evidence/review.
5. A visual aesthetic judgement is not fabricated by the factual QA model. Real-output design quality still needs human inspection and adjudicated examples.
6. A required URL must be current under the publication policy and bound to the approved candidate SHA.
7. Draft template output can expose partial copy for inspection, but stays `draft_with_blockers`; submit-ready still requires complete family copy and all hard gates.
8. Template failure never triggers image or copy regeneration.
9. Delivery package failure retains original images/workbook and can rebuild from the same verified sources.
10. Package commit and URL verification are separate from Amazon accepting a feed/listing.

## 3. Existing offline coverage

- `tests.test_qa_lite_v1`: factual QA and saved response reuse.
- `tests.test_publish_storage`: storage-provider switching, verified URL reuse, and missing upload recovery.
- `tests/audit_delivery_fixture.py`: final image/template export version binding, hash integrity and URL byte verification.
- `tests.test_template_field_plan_contracts`: template field/enum/measurement contracts and partial draft copy behavior.
- `tests.test_generation_state_contract`: candidate receipt recovery and provider/request boundary contracts.

These are existing tests; they have not been executed in this editing environment.

## 4. Live acceptance blockers retained

The following cannot be certified from repository code or synthetic fixtures:
- four supported categories' real image factual pass/false-pass behavior;
- visual design quality and brand consistency on real outputs;
- real workbook opening/import validation in the supported Excel/Amazon template environment;
- R2/OCI actual upload, public URL bytes, retention and invoice reconciliation;
- final package download and hash verification against real family outputs;
- Amazon feed/listing acceptance.

These remain explicit Phase 7 live acceptance gates. No automatic aesthetic score or weakened fact threshold was introduced to conceal them.
