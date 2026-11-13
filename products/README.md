# Product Plugins

A product plugin describes how one Amazon category should be processed.

Minimal files:

```text
products/<category>/
  manifest.yaml
```

Category-specific `extractors.py` modules are retired. Apify-like source parsing is owned by
`products/generic_extractors.py`; categories declare field labels, variation dimensions, and
derived flags in `manifest.yaml` under `extractors`.

If a category appears to need custom parsing, first adapt the upstream source into the common
Apify-like raw shape, then extend the manifest extractor labels. Do not copy title, bullets,
description, image URL, attributes, or variation parsing into a category plugin.

The goal is to add categories by adding plugins, not by copying the whole pipeline. Required roles, main-image policy, replaceable staging, and structural constraints live in `manifest.yaml`; FinalSourceIntentV2 owns source-role decisions and ImageTaskV13 owns immutable image-edit execution. Effective visual_context and role_visual_direction are sent once to the current child planner and bind its design-input authorization.

`manifest.yaml` is the plugin entrypoint. Legacy `product.yaml` files are intentionally not part of the active contract because keeping two rule sources makes it unclear which one drives the pipeline.

For template-capable categories, `manifest.yaml` may declare `template.default_path` relative to the factory root plus an optional `template.path_env` override.
Template fields are compiled only by `TemplateFieldPlan`; category-level template mappings are retired because they duplicated and could overwrite the same cells.
`template.allowed_item_type_hints`, `search_terms`, and optional
`recovery_fact_policy` contain category semantics; core consumers do not keep
parallel category tables. Shared search database buckets do not imply identical
category filters. Search references never authorize product facts.

`planning_guidance` is non-retroactive advice for unfinished/future planning;
changing it does not revoke old accepts. Hard structure/role policy still binds
currentness. Typed staging IDs apply only to non-sold content; all registered
product/included/disputed instances are excluded from staging edits regardless of
their descriptive names. Generic dimension parsing requires explicit value or
source-field axes and units, never category-based ordering or largest-number
height guesses. Genuine variation labels (e.g. `6 FT`, `Queen`) remain separate
from physical and package dimensions and are validated against the real template.

`image_generation.statement_measurements` declares eligible structured product
fields, object/axis meaning, declared-label wording and exact raw attribute labels.
Optional `tuple_fields` names eligible product attributes whose value or field
must explicitly identify axes and units; it never supplies an inferred axis order.
This declaration alone is NOT permission to use listing text instead of image
measurements. A separate explicit child/size-role input decision is required.
Current declarations cover frame/tree height, tree width and cabinet depth. Title-only
numbers, variation Size labels, package dimensions, conflicts and ambiguous scope
conditions remain ineligible; add supported fields through the same declaration
and fact authority, never through a second extractor or synthetic image evidence.

Current plugins:

- `bed_frame`, `artificial_tree`, `bathroom_cabinet`, and `medicine_cabinet`: engineering-integrated Apify, copy, image, QA, publish, and template plugins. The existing `lifecycle: production_ready` label declares integration support, not proof of real images, formal QA, full-family delivery, or unattended acceptance.
- `office_chair`: unsupported until its listing template and a real acceptance ASIN are supplied; validation, job creation, and production reject it.
