# Child Design Inputs and Reference Authority

This extends the existing observation -> child planning -> prompt -> generation
-> QA -> template chain. No new stage, controller, aesthetic QA, feature flag,
automatic candidate experiment, or default reference pack is introduced.

## Input Contract

`scripts/factory.py new-job --design-pack PATH --brand-brief PATH` accepts
explicit optional local inputs. Omitting them keeps autonomous Gemini planning.
The brand brief accepts audience, positioning, design_priorities and avoid.
Seller defaults, source facts and category main-image policies do not change.

The only current pack schema is `design-pack-v4`. Approval scope is explicit:
`production` requires `production_ready=true`; `evaluation` requires
`production_ready=false` and explicit child IDs (no wildcard). Assistant review
for a limited test is not project-owner or commercial approval. Neither scope
is auto-discovered or required when running without an external reference.
A production pack needs:
pack_id, version, status=approved, production_ready=true, compatibility.categories,
design_system and assets. Every asset needs:

- asset_id, local_path, sha256, roles and children.
- purpose: transferable design principles, not product facts.
- reference_region: normalized [left, top, right, bottom] reviewed on that asset.
- source_url, author and asset_license.
- rights_review: status, approved_by, approved_at, license_evidence,
  allowed_uses including image_generation_reference.
- visual_review: status, approved_by, approved_at, product_clarity,
  information_hierarchy, evidence_fit, series_cohesion and transfer_scope.

Full-frame [0,0,1,1] is appropriate only when that entire image is reviewed as
suitable reference input. The program cannot verify a signature or a legal
approval merely from a nonempty field. Never invent the reviewer's approval.
In particular, avoid an unrelated headboard or multi-view product in a reference
for a headboard-free, single-view bed. A text disclaimer is not pixel isolation.

Import validates the original bytes and reviewed region, then saves only that
lossless RGB/RGBA region into inputs/design. Its derived hash/path is the actual
planner and generation attachment. Original hash, region, pack hash and review
remain provenance. There is no old full-reference import fallback or pack-v2
migration. Existing job artifacts are evidence only, not silently upgraded inputs.
Transparency is retained instead of exposing hidden RGB pixels by dropping alpha;
prefer opaque references where the surrounding canvas is part of the design.

The test-owned Sep 11 pack is now draft, with its false project-owner approval
withdrawn. Its high-headboard lifestyle image, placeholder function graphic and
multi-view chair size graphic are not approved production standards. Historical
job copies were not edited. Replacement real assets and actual review remain open.

## Single Design Authority

Observation records product objects separately from staging. A product object's
state describes only its count, assembly/operating state, visible extent and
occlusion, not the quilt or wall's color. Planning/prompt projection omits loose
staging decoration but preserves occluding object identities and relationships.

Gemini owns the shared child palette, typography and graphic assignments.
Role creative_brief owns composition; design_transfer owns use of reviewed
reference features. Both reference shared names instead of assigning colors again.
Product evidence alone owns structure, finish, demonstrated state and measurements.
A design reference cannot authorize a new product, hidden surface or camera view.
Function and size remain reference edits, not new product renders.

The existing text-only planning verification request batches factual copy checks
and explicit design-binding conflicts. Natural-language colors and font assignments
are compared against the same named child design, not against an aesthetic score.
Design inconclusive/unavailable does not create a new aesthetic gate. An explicit
binding contradiction enters the existing bounded brief repair. Factual copy
still needs its existing evidence support.

All known claim failures and design findings reach that repair together.
The repair may correct conflicting shared prose (environment_and_staging,
photography_direction, cohesion_rule); it may not replace palette, typography,
graphics or unrelated source briefs. Only changed bindings are reviewed again,
within the existing deadlines and one-repair limit. Already-ready role work is
not regenerated to repair a failed brief. No indefinite retry loop is added.

Palette diagnostics measure Gemini's actual choices without selecting, recoloring
or vetoing. Reports now include opacity and composited backing contrast against
possible opaque scene surfaces. Missing underlays remain unresolved, not silently
assumed white. Pairings are planning diagnostics, not observed image colors or
proof of good aesthetics.

## Prompt Projection

The compiler keeps ROLE, REFERENCE, STYLE, TEXT and OUTPUT. Each evidence view's
source region, optional target region and disposition appear together. Shared
cohesion rationale stays in the planning artifact rather than repeating styling in
the generation prompt. Exact authored function copy appears in one text block.
Product/mattress state, partial-view boundaries, graphic role colors, US-unit
measurements, measured objects and endpoints remain part of the current contract.

Local prompt projections of the previous 16 canary tasks were audited without
changing their manifests or invoking providers. This is not a migration and does
not constitute a fresh Gemini plan or real-image acceptance.

| Role | Prior characters | Revised compiler projection |
| --- | --- | --- |
| main | 4241-5018 | 3948-4615 |
| scene | 4139-4763 | 3846-4413 |
| func | 5283-6737 | 4821-6124 |
| size | 5139-5767 | 4783-5354 |

These numbers precede any new planning and reference curation. Shorter is not a
release criterion; the generated pixels must still be inspected.

## Execution and Evidence

Existing provider assignment/capacity logic is retained. AICOST Sunburst and CXK
Sunburst may serve func/size; model aliases or smoke success are not quality proof.
Paid smoke checks should use the existing --write-result option so their actual
result is retained. No success record is fabricated for an earlier unsaved check.

Request audit separates provider queue time, provider execution (including worker
startup/encoding) and upscaling. Existing progress records also expose local
finalization time, including upscale/commit; these intervals overlap and must not
be summed as disjoint durations. Publication still uses the existing upscaler.
Generation without QA reports automatic_decision=not_run; stale evidence is stale;
a completed observation with uncertainty remains inconclusive. No acceptance
rules are relaxed and QA has not been run merely because a candidate exists.

## Bounded Real Validation Still Required

After actual replacement reference approval, freeze code, source facts, copy,
reference bytes and route settings. The known two-child inventory is 17 valid
tasks after excluding the white-child natural-color source conflict. Generate all
valid roles, with at most two additional same-input cross-provider func/size
comparisons (19 intended successful initial outputs). Automatic transport retries
can consume additional requests under existing bounds; inspect request counts and
current pricing before starting. There is no implied fixed-price or zero-retry
promise.

Inspect structural fidelity early before spending the remaining image budget.
Then inspect every role per child and run existing QA through template generation.
Compare old/new structure, measured endpoints, unique functional evidence,
bedding/environment consistency, type/icon roles and reference influence. Existing
source-vs-generated sheets are not a controlled with/without-reference A/B study.

This code revision alone does not establish improved image quality or final
production readiness. No new paid generation is included in the offline checks.

## Verification of This Revision

Interpreter: D:\anaconda\python.exe. Final targeted command:

```text
-W ignore -m unittest tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_provider_runtime_v1 tests.test_generation_state_contract tests.test_qa_lite_v1 tests.test_flow_regressions tests.test_status_revision_contract -q
```

52 cases passed in 5.900 seconds. Earlier focused runs exposed two obsolete
prompt-text assertions and a test indentation error; these were corrected before
the final run. No production quality requirement was relaxed to satisfy them.

Final production command: `-W ignore scripts/run_production_tests.py`.
Run once after code edits: 100 cases passed in 7.170 seconds (100/60-second budget
unchanged). No historical/full-discovery suite was run. Normal repository
`git diff --check` passed; overriding Git's CRLF interpretation produced spurious
whitespace warnings, so no repository-wide line-ending rewrite was performed.

This turn modified 11 existing production files, adding/deleting no production
modules: design_reference_library.py, visual_design_kit.py,
visual_design_kit_compiler.py, visual_semantics.py, image_reference_context.py,
image_prompt_compiler.py, palette_registry.py, release_manifest.py,
image_provider_routing.py, candidate_state.py, image_generation_executor.py.
Approximate incremental production edit volume: 210 added / 65 removed lines;
pre-existing uncommitted work is excluded from that estimate.

Physically replaced: whole-asset pack-v2 import, first-claim-only failure handling,
claim-only review entry point, duplicate view-position prompt paragraphs, repeated
cohesion prose in generation prompts, all-pairs opaque-only palette diagnostics,
and the missing-QA-as-unavailable default. Corresponding fixtures/assertions were
updated in place, with no extra/skipped test cases or legacy runtime switch.

Still unverified: replacement reference curation/approval, a new complete Gemini
plan on real sources, actual structural fidelity/color consistency, real planning
latency after widening the existing binding check, two-provider complex-image
comparison, and the fresh QA-to-template canary. In a child without non-verbatim
func claims, the existing planning review used to be empty and may now make one
bounded text-only request; this is not zero added inference work. Neither offline
test success nor prompt shortening is reported as real image quality acceptance.
