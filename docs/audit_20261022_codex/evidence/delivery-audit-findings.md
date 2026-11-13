# Delivery audit, current source, 2026-10-22

Scope: read-only source review of fetch/product facts/copy/publish/release/template/summary. No historical jobs were read. No remote requests, production-suite execution, source or test changes. Three isolated pure-function probes ran with D:\anaconda\python.exe -B; evidence is delivery-probes.jsonl and the rerunnable delivery-probes.py in this directory.

## Confirmed defects

1. P1: Non-material contradictory raw facts are overwritten before the single fact authority can detect conflict. products/generic_extractors.py:24-34 overlays attributes/manufacturerAttributes/productOverview onto productDetails, and 37-45 picks the first matching alias. core/plugin.py:114-122 constructs specs and product_specific from this same collapsed result. core/source_fetch/apify.py:644-695 then declares color/drawer facts confirmed. Probe: productDetails Color=Black, Drawers=2 plus attributes Color=White, Drawers=4 yields confirmed White and 4, with no Black/2 evidence. This is different from a deliberate evidence priority: the losing observations and disagreement disappear. Effective facts propagate at core/product_family.py:58-85, copy_polish.py:510-517 and template_engine.py:1440-1442. Repair by extending existing ProductFamily extraction provenance to all identity/measurement/count facts and preserving conflicts before projection, deleting lossy collapse for those facts. Accept contradictory observations as conflicted with source paths; exclude unresolved values consistently from copy, images, templates.

2. P1: Shipping/carton dimensions become product dimensions when structured dimensions are absent. products/generic_extractors.py:166-177 scans all searchable listing prose without ownership; searchable_text at 190-201 includes description and bullets. Probe with only description 'Shipping carton dimensions: 40 x 20 x 10 inches. Product assembly required.' yields length=40 in,width=20 in,height=10,height_unit=Inches. Downstream effective_product_facts and template_engine.py:1440-1442 admit these as product facts; template_field_values.py:14-55 projects to product dimensions. Repair existing extractor to carry measurement owner/source and accept product-owned dimensions only; missing dimensions are missing. Accept packaging/assembled/individual-component examples with distinct owners, no cross-use.

## Confirmed design limitations / recommendations, not mislabeled implementation bugs

3. Every image requires manual approval even if automatic QA passes: core/release_manifest.py:117-134 yields approved only for human==approve, else awaiting_review. This cannot satisfy user's clarified automatic complete-listing-package, exceptions-only-human target. Keep one release authority, define versioned automatic release eligibility from hard factual/publishing gates; inconclusive/conflicting/failed/unknown cases use existing human authority. Do not add another model reviewer or aesthetics judge.

4. Discovery ambiguity is intentionally resolved conservatively by selecting display-data inventory, not expanding to variantAsins. products/generic_extractors.py:303-338; test_root_cause_remediation.py:68-71 explicitly tests this. Probe shows provided inventory B1/B2/B3 becomes B1. Do not call the conservative selection itself a bug and do not auto-expand frozen families. Remaining design gap: persist ambiguity/excluded observations and explicit discovered-vs-frozen scope so expected_child_count (apify.py:272) and full-family claims cannot be misread as proof of externally exhaustive discovery.

5. Whole-family submit-ready is intentionally strict: template_engine.py:248-254,288-292 and run_scope.py:38,102-103 require complete frozen family and no unresolved fetch errors; release_manifest.py:593-600 aggregates children. Preserve this meaning. Good children may finish work independently, but completed package requires frozen family fully resolved. Use separate batch/item/package status, never silently omit failed children.

6. Delivery files are individually atomic, not a single committed package transaction: publish.py:294-319 exports Final_pics before final public URL verification; template_engine.py:483-498 writes plan state before workbook/export and then writes receipt. template_package.py:23-59 and template_engine.py:650-671 use temporary+replace. template_contract.py:94-173 correctly checks fingerprints and output/export hashes, reducing false reuse. Recommendation: extend existing release/package authority with an immutable deliverable revision and final committed pointer containing copy/image URLs/template hashes; current Final_* folders must not be treated as completion signals. No need for a competing manifest/controller.

## Mechanisms worth preserving

- Requested/returned ASIN exact ownership: apify_client.py:81-89; apify.py:415-422.
- Current family/source raw SHA/request identity validation and explicit stale invalidation: apify.py:44-68; product_family.py:204-245.
- Child-owned price, resolved size/color/material propagation, material component ownership. Current material conflict handling is stronger than non-material facts.
- Source-bound copy request and fragment receipts; no blind token-burning retries: copy_polish.py:88-151,318-381.
- Candidate-SHA upload object identity, durable partial publish rows, public body SHA and PNG verification: publish.py:98-149,502-562,666-716,972-976.
- Current candidate/QA/human review fingerprint binding and required-role usability selection: release_manifest.py:99-115,569-590.
- Preserved XLSM ZIP package validation and exact workbook/export hash checks: template_package.py:23-59,107-155; template_contract.py:158-172.

Unverified: actual provider fetch completeness, actual generated visual quality, live object-storage upload and public reads, current real output artifacts, Excel UI/macros, Amazon acceptance. Amazon submission is outside the clarified product endpoint. No active SP-API submission path was found in reviewed core/scripts.
