# Core Layer

`production.py` owns the only production control flow. Core stages consume
immutable, fingerprinted artifacts in one direction:

```text
ProductFamilyV3 -> CopyV1 -> DownloadManifestV2 -> FinalSourceIntentV1
-> VisualDesignKitV10 -> ImageTaskV8 -> ImagePromptV2 -> generated pixels
-> QAEvidenceV4 -> HumanReviewV4 -> ReleaseManifestV5 -> publish -> template
```

Category-specific facts and role rules live in `products/<category>` and its
manifest. Core code must not branch on category names or preserve obsolete
schemas, cache readers, controllers, or fallbacks.

Each stage has one authority:

- `source_fetch` and `schema`: strict ProductFamilyV3 input and raw Apify evidence.
- `copy_polish`: exact source-copy grouping and CopyV1 provenance.
- `asset_manager`: validated, job-relative DownloadManifestV2.
- `final_source_intents`: final per-source intent plus child-level size arbitration; source_00 is main.
- `required_role_policy`: required image roles used by every downstream gate.
- `visual_design_kit`: one model-authored product diagnosis, shared family art direction, and immutable source brief per confirmed non-main source.
- `image_tasks`: deterministic immutable reference-edit contracts, one per confirmed child/source role.
- `image_prompt_compiler`: brief-stage lossless projection of each task into immutable ImagePromptV2; generation never recompiles it.
- `image_generation`: one initial candidate; only an explicit human `revise` request creates another candidate.
- `image_qa`: generated-pixel observations only; it never generates images.
- `qa_evidence`: QAEvidenceV4 automatic hard-gate result.
- `release_manifest`: automatic and human release decisions.
- `publish`: approved-image upload only.
- `template_engine`: complete-family template generation only.

Resume reruns only retryable tasks. Blocked tasks remain terminal until their
input fingerprint changes; marking a stage complete never resolves an error.
