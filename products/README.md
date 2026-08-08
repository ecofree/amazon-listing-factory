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

The goal is to add categories by adding plugins, not by copying the whole pipeline. Required roles, main-image policy, replaceable staging, and structural constraints live in `manifest.yaml`; FinalSourceIntentV1 owns the one-role source decision and ImageTaskV7 owns immutable image-edit execution.

`manifest.yaml` is the plugin entrypoint. Legacy `product.yaml` files are intentionally not part of the active contract because keeping two rule sources makes it unclear which one drives the pipeline.

For template-capable categories, `manifest.yaml` may declare `template.default_path` relative to the factory root plus an optional `template.path_env` override.
Template fields are compiled only by `TemplateFieldPlan`; category-level template mappings are retired because they duplicated and could overwrite the same cells.

Current plugins:

- `bed_frame`, `artificial_tree`, `bathroom_cabinet`, and `medicine_cabinet`: production-ready Apify, copy, image, QA, publish, and template plugins.
- `office_chair`: unsupported until its listing template and a real acceptance ASIN are supplied; validation, job creation, and production reject it.
