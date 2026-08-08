# Image Pipeline Error Taxonomy and Response System

Date: 2026-06-17

## Clear Conclusion

The recurring failures were not caused by one weak model or one missing rule.
They came from mixed authority: facts, creative planning, generation, QA, cache,
and provider routing could each reinterpret the same image task.

The durable fix is to classify every issue by authority and gate type before
changing code. A rule is correct only when it is strict at hard factual gates and
flexible at creative or diagnostic gates.

## Gate Classes

### Hard Fact Gates

These may block generation, rerun, or publishing.

- Product structure changed.
- Product color, material, accessory, component count, or visible identity changed.
- Required size value is missing or numerically wrong.
- Required function claim has no visible product part or verified product fact.
- Main image background violates Amazon white-background rule.
- Generated image is corrupt, non-image, or unusable.
- Visible text contains forbidden text, garbled text, Chinese text for US assets, or unsupported claim.
- Role contract is missing or conflicts with verified product truth.

Hard fact gates require structured evidence:

- entity
- expected
- observed
- confidence
- source artifact
- contract id
- rerun instruction, when rerun is possible

If these fields are absent, the system must not hard reject.

### Soft Design Gates

These may guide planning, candidate ranking, or prompt improvement, but must not
block publishing by themselves.

- Composition is ordinary.
- Palette is not premium enough.
- Lighting is weak.
- Background is boring.
- Typography is not elegant.
- Layout is too similar to reference.
- Visual system is less polished than expected.

Soft gates belong in Gemini visual planning and visual selection, not QA hard
decision.

### Inconclusive Gates

These must never be converted into hard failure.

- OCR returns empty text.
- OCR confidence is low.
- Model says "may be missing" without concrete entity evidence.
- Reference image is cropped and a component is not visible.
- A scene uses reasonable environmental quantity different from package quantity.
- A size image shows one unit to explain dimensions while listing sells a pack.

Inconclusive output should trigger evidence collection or manual review only when
the role is truly publish-critical.

## Strictness Matrix

| Area | Must Be Strict | Must Be Flexible |
|---|---|---|
| Classification | one main per child, role evidence retained | non-main role can be reassigned by child-level arbitration |
| Product truth | verified facts, explicit conflicts | not visible is not confirmed absent |
| Size image | exact numbers, units, all required measurements | font, color, line style, title, background |
| Function image | claim must bind to fact and visible product part | wording, layout, callout style, room staging |
| Scene image | product identity and structure | room, bedding, props, lighting, camera angle |
| QA | hard facts and publish blockers | aesthetics, creativity, palette, ordinary composition |
| Provider | forbidden providers, missing token, bad response | one provider failure should not consume content candidate |
| Cache | schema/contract/prompt fingerprint mismatch | no migration from historical jobs |

## Repeated Error Classes

### 1. Validation Strict, Runtime Loose

Symptom: config validation rejects an entry, but runtime still routes to it.

Root cause: validation and execution used separate predicates.

Response:

- Move the predicate into the runtime router.
- Add a default production test that proves invalid config is not routed.
- Do not rely on validation alone.

Recent fix:

- `vision_qa` runtime now requires GPT-5.5 with responses protocol, matching registry validation.

### 2. Prompt Says Preserve and Redesign at the Same Time

Symptom: size and func images become new product renders instead of reference edits.

Root cause: role contract says preserve product/reference layout, while generic
Gemini prompt says redesign the whole image.

Response:

- Size and func are reference-image edit tasks.
- The product subject, core measurements, product-bound lines, and verified callouts are locked.
- Only background, title, text style, line style, icon style, and layout polish are creative.
- Scene can change camera/environment but must preserve product semantic structure.

### 3. Model Output Too Large or Too Free-Form

Symptom: long JSON is truncated, schema names drift, fields are missing, and
later stages patch them inconsistently.

Root cause: too many repeated facts and too little schema authority.

Response:

- Use compact stage-specific input.
- Generate prompt and validator from the same schema.
- Reject missing required fields; do not repair them silently.
- Store raw model response and parsed artifact separately.
- Large text returns must be parsed by strict envelope first, then content fields.

### 4. OCR Treated as Intelligence

Symptom: OCR text decides role or blocks images even though it is only raw evidence.

Root cause: OCR evidence was promoted into final judgment.

Response:

- OCR provides raw text lines, numbers, and confidence.
- GPT-5.5 visual observer classifies and extracts image facts.
- Program arbitrates role and fact conflicts.
- QA must not hard reject from OCR alone unless high-confidence OCR agrees with visual evidence.

### 5. Product Count Rules Applied Uniformly

Symptom: scene or size image rejected because object count differs from package count.

Root cause: package quantity and scene quantity were treated as one rule.

Response:

- Main: strict package/sale quantity.
- Size: one unit is valid for dimensions.
- Func/detail: depends on contract.
- Scene: reasonable staging quantity allowed if it does not imply wrong package count.

### 6. Provider Failure Treated as Content Failure

Symptom: token/timeout/500/504 consumes candidates and triggers prompt changes.

Root cause: transport state and content state were mixed.

Response:

- Transport failures switch provider within same attempt.
- Content failures create candidate feedback.
- Provider health is project-level, role-aware, and time-windowed.
- A provider smoke test must exist for every added endpoint.

### 7. Historical Compatibility Re-Enables Old Behavior

Symptom: old manifests, provider lists, prompt builders, or fallback paths continue
to affect current runs.

Root cause: replacements were added without deleting old authorities.

Response:

- Delete superseded runtime paths in the same task.
- No default-off old path.
- No compatibility branch that silently repairs obsolete schema.
- Default tests cover current reachable production chain only.

## Model Output Handling Rules

Large model outputs must use a two-layer contract:

1. A small required envelope:
   - schema_version
   - artifact_type
   - child_asin
   - contract_id
   - role
   - status
   - errors

2. Bounded content arrays:
   - observations
   - product_parts
   - measurements
   - function_claims
   - visual_plan_items

Each array item must have an id and a source reference. Free text is allowed only
inside bounded fields; it cannot decide pass/fail.

## Work Rules for Future Fixes

Before changing code, classify the issue:

- Is it a hard fact, soft design, inconclusive signal, provider transport, cache,
  schema drift, or historical path issue?
- Which module owns the decision?
- Is the current problem caused by another module overriding that owner?
- Which old path becomes obsolete after the fix?
- Which default production test proves the old path is gone?

After changing code:

- Search for the old behavior keywords.
- Remove the old runtime path and old tests.
- Run targeted tests.
- Run the default production suite once.
- Do not claim image quality is fixed without inspecting real generated images.

## Current Operating Principle

The system should be strict about truth and loose about design.

It should be strict when a fact can be verified, loose when the model is choosing
a visual style, and inconclusive when evidence is weak.

Most previous failures violated this principle in one of two ways:

- strictness was applied to aesthetics or weak OCR;
- looseness was applied to product identity, model routing, schema compliance,
  or cache validity.
