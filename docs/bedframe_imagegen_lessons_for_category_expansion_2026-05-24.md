# Bed Frame Image Generation Lessons For Category Expansion

Date: 2026-05-24

Purpose: summarize the hard-earned lessons from the bed-frame image-generation workflow so future Amazon categories can start from a stronger baseline instead of repeating the same failures.

This review is based on historical bed-frame production notes, prior QA observations, current review triage, migration status, and the current core image-generation rules in `amazon_listing_factory`.

## Executive Summary

The bed-frame workflow did not become stable because of one better prompt. It became stable because the system learned five deeper lessons:

1. Image-to-image generation must be isolated from polluted context and unrelated prior images.
2. Product preservation and scene change must be separated by role, not mixed into one generic prompt.
3. Style must be derived from the product, audience, and category, not from weak source-background color blocks.
4. Quality gates must block publish/upload, not merely create advisory reports.
5. Category knowledge must live in a plugin, not inside the generic execution engine.

The most important takeaway for new categories:

> Do not start by bulk-generating a full catalog. Start by defining the category plugin, invariants, role rules, style package, QA rules, and one golden child ASIN. Only scale after the golden sample passes.

## Evolution Timeline

### Phase 1: Manual Image Generation And Context Pollution

Early generation used the active image-generation context heavily. After many bed-frame/function-image examples accumulated, the model began producing unrelated outputs such as health, wellbeing, education, or poster-like images even when the current source was a bed frame.

Observed symptoms:

- unrelated poster or infographic output;
- model ignored the bed-frame source image;
- function images became generic educational graphics;
- repeated retries in the same context made failures worse;
- high-risk `func*` images were especially unstable.

Root cause:

- the generation context was polluted;
- too many source examples and previous outputs were active at once;
- function images combined product, text, panels, claims, and layout, which made them more fragile than lifestyle images.

Fix that worked:

- use clean/new generation contexts;
- for high-risk function images, use one isolated worker per source image;
- reject unrelated outputs immediately;
- keep only accepted model outputs;
- do not use local compositing or local text overlay as final image generation.

New-category rule:

> For any new category, treat text-heavy or function-heavy images as high risk from day one. Use isolated source binding and role-specific prompts.

### Phase 2: Product Preservation Versus Meaningful Change

The next major tension was: the product must remain unchanged, but the generated image must look clearly new.

Observed symptoms:

- some images preserved too much and looked nearly identical to the source;
- some images changed the room but also changed the bed structure;
- some function images became plain lifestyle images;
- some lifestyle images changed only colors, not the environment;
- repeated angle/camera position made the full set look monotonous.

User correction:

- "除床架保持不变外，其它都可以改变"
- "构图可以改变"
- "只要保持床架主体不变，视角少部分图出现差异也不是很大问题"

Important lesson:

Product preservation does not mean source-image preservation. The product is locked. The environment, textile, wall, props, lighting, and graphic style should be actively changed.

Role-level solution:

- `main`: product-first lifestyle image, no text, strong room refresh.
- `scene`: lived-in room use case, modest camera variation allowed.
- `size`: lock product angle, all numbers, arrows, and attachment points.
- `func*`: lock product count, function meaning, claims, numbers, panels, and demonstration logic.

New-category rule:

> Before generating images, write a category-specific preservation matrix: what must never change, what should change, and what depends on role.

Example for bed frames:

| Area | Lock | Change |
|---|---|---|
| Product geometry | rails, guardrails, ladder, slide, slats, legs, screws | none |
| Product finish | color, material, texture | none |
| Lifestyle scene | bed frame | wall, floor, bedding, pillows, rug, decor, lighting |
| Size image | dimension values, lines, arrows, product angle | background, typography, banner, line style |
| Function image | claim meaning, numbers, detail panels, product count | layout, palette, font, card spacing |

Example for office chairs:

| Area | Lock | Change |
|---|---|---|
| Product geometry | backrest curve, armrests, gas lift, caster count, wheel base | none |
| Material | mesh/leather/fabric texture, chair color | none |
| Lifestyle scene | chair | desk, wall, floor, monitor, plant, lighting |
| Size image | dimension values, arrows, attachment points | background and graphic system |
| Function image | adjustment claims, mechanism, hard values | layout and visual styling |

### Phase 3: Local Redraw And Overlay Was Rejected

At one point, local scripts or local composition-style thinking entered the process. This created outputs where text, dimensions, or callouts looked like artificial overlays rather than true model-generated image-to-image results.

User correction:

- "我需要的是图生图，不是你调用本地垃圾的覆盖"
- "我不需要你重建流程，我需要的是调用模型图生图"
- "必须彻底把调用本地作图的这种垃圾清除"

Final rule:

> Final product images must be model image-to-image outputs. Local scripts may inventory, copy, create contact sheets, run OCR, upscale, upload, and audit only. They must not redraw, patch, overlay, or locally rebuild final images.

This rule should be universal for every category.

Allowed local operations:

- scan folders;
- build task manifests;
- create contact sheets;
- run OCR or VLM QA;
- upscale accepted outputs;
- upload to R2;
- write template image URLs;
- store audit reports.

Forbidden local operations for final images:

- manual text overlay;
- PIL/canvas reconstruction;
- local dimension-line redraw;
- local badge replacement;
- screenshot assembly;
- compositing generated product onto local background as a final publish image.

### Phase 4: Style Quality Was The Biggest Visual Upgrade

The B0B7B43C4K full run proved the technical chain could work, but the visual quality was weak.

Observed problems:

- typography stayed too close to source images;
- palette inherited poor source color blocks;
- room changes were shallow;
- bedding, duvet, throws, and pillows were sparse;
- function layouts looked lightly restyled rather than redesigned;
- banner colors clashed with the room style;
- wall backgrounds differed too much between images in a set;
- text and badge colors varied randomly, including unrelated greens.

Root cause:

- the batch was run without a strong `style_profile.json`;
- the prompt preserved the product correctly, but did not force enough environment, textile, typography, and palette change;
- style was sometimes influenced by source background blocks instead of the product color and target audience.

Stable fix:

- build `style_profile.json` before generation;
- include product color, material, type, audience, and role;
- use competitor/source images as evidence only, not as style authority;
- define wall, floor, bedding, props, lighting, composition, and infographic palette;
- define exact typography colors for size/function images;
- ban weak source colors and source-like typography.

Important bed-frame style rule:

> The bed frame product decides the style. Source-background color blocks do not decide the style.

For the caramel-brown bed frame, the successful style direction was:

- warm ivory, cream, linen gray;
- warm taupe, honey oak, soft olive textiles;
- light oak or natural wood floor;
- warm daylight;
- restrained infographic panels;
- avoid all-brown layout, dark orange dominance, cold metallic styling, neon accents.

New-category rule:

> Every category plugin must define a product-adaptive style package before generation. The package must include both lifestyle style and infographic style.

Minimum style profile fields:

```json
{
  "product_profile": {
    "product_type": "",
    "color_name": "",
    "material_hint": "",
    "audience": "",
    "positioning": ""
  },
  "style_direction": {
    "mood": [],
    "primary_palette": [],
    "accent_palette": [],
    "avoid_colors": []
  },
  "typography_palette": {
    "heading": "",
    "body": "",
    "reversed": "",
    "accent": "",
    "line": "",
    "badge_fill": "",
    "panel_bg": ""
  },
  "scene_rules": {
    "wall": "",
    "floor": "",
    "props": [],
    "lighting": "",
    "composition": ""
  }
}
```

### Phase 5: Size And Function Images Need Separate Discipline

Text-heavy images caused the most quality problems.

Size-image failures:

- numbers changed or became unreadable;
- arrows detached from the correct part;
- dimension labels ghosted or doubled;
- visual noise around text reduced legibility;
- text colors did not match the folder palette.

Function-image failures:

- model deleted detail panels;
- function image became lifestyle-only;
- product count changed;
- source claims were lost or rephrased incorrectly;
- badges or icons were invented;
- wall-poster text was mirrored or garbled;
- layouts over-copied cheap source graphics.

Stable fix:

- explicitly list all important numbers in prompts;
- require each dimension arrow to remain attached to the same part;
- distinguish source type before prompting:
  - textless detail image: do not invent labels;
  - claim/callout image: preserve exact meaning and hard values;
  - decorative wall-poster text: remove or replace with abstract art;
- lock product count and product structure;
- allow graphic redesign but keep claim meaning;
- use a folder-level typography palette with no more than three text colors.

New-category rule:

> Do not use one generic "function image" rule. Define role subtypes: dimension, mechanism detail, material detail, package contents, comparison, compatibility, installation, and claim infographic.

For each role subtype define:

- must-preserve elements;
- allowed visual changes;
- OCR requirements;
- VLM scoring dimensions;
- examples of forbidden inventions.

### Phase 6: Provider And API Routing Became Production Infrastructure

The project moved from built-in generation to configured external image providers for speed and isolation.

Useful outcome:

- large batches could run faster;
- polluted built-in image context became less harmful;
- candidates could be generated through different providers;
- provider failure could be retried through another provider.

Problems discovered:

- one provider returned incomplete JSON once;
- batch command timed out after generating most images;
- child Python processes could remain alive after outer timeout;
- logs contained some mojibake;
- provider choice rules were initially informal;
- `apimart_official` must never be used.

Stable policy:

- allowed image providers: `apimart`, `dragoncode`;
- forbidden image provider: `apimart_official`;
- use provider policy, not memory;
- retry failed single roles, not whole folders;
- keep provider/candidate logs;
- add per-task timeout and heartbeat for future extraction.

New-category rule:

> Provider routing is part of the category plugin. Some categories may need stronger texture preservation, better text handling, or stricter product geometry than others.

Example plugin field:

```yaml
model_preferences:
  image_gen:
    preferred: dragoncode
    fallback: apimart
  visual_qa:
    model: gemini-3.5-flash
    temperature: 0.1
  text_copy:
    model: deepseek-v4-flash
  ocr:
    engine: PP-OCRv5
```

### Phase 7: Gemini Became Visual QA And Style Intelligence

Gemini was useful when assigned the right job.

Correct role:

- composition analysis;
- camera angle and framing checks;
- room setting and soft furnishing review;
- wall, floor, bedding, rug, decor, and lighting analysis;
- palette and product-color fit;
- source/output comparison;
- rerun prompt deltas.

Wrong role:

- title rewrite;
- bullet polishing;
- product description rewrite;
- Amazon template text fields.

Those text jobs belong to DeepSeek or another cheaper text model.

Important evolution:

- Gemini should not only judge after generation;
- Gemini should also help build `style_profile.json` before generation;
- QA must compare source and output, not output alone;
- QA must understand role differences.

Early issue:

- B0GG49KN64 initial Gemini QA rejected all 16 generated images.

Later result:

- final acceptance manifest reached 16 accepted images after targeted reruns and threshold/prompt/QA improvements.

New-category rule:

> Use VLM twice: before generation for style and risk analysis, after generation for QA and rerun deltas.

### Phase 8: OCR Was Needed, But The First Model Choice Was Too Heavy

OCR was added to catch garbled text, missing numbers, and unreadable function/size labels.

Initial problem:

- PaddleOCR-VL crashed in the Windows/GPU environment;
- it was too heavy and less stable for this use case;
- the task needed short English text and numeric-label detection, not full document understanding.

Final decision:

- remove PaddleOCR-VL;
- use PaddleOCR / PP-OCRv5;
- run it from a dedicated environment through `PADDLEOCR_PYTHON`;
- keep OCR audit-only;
- never use OCR output to locally redraw image text.

Observed final behavior:

- PP-OCRv5 produced mostly pass results;
- remaining warnings were mainly small dimension-token misses;
- OCR must be combined with VLM/manual review, not treated as perfect truth.

New-category rule:

> Choose the smallest OCR model that reliably catches the category's failure mode. Do not default to a large document model.

### Phase 9: Postprocess And Publish Needed Hard Gates

The pipeline eventually included upscaling, R2 upload, and template backfill.

Issues found:

- RealESRGAN 4x was too slow for batch throughput;
- 2x plus Lanczos was more practical;
- non-square images must not be forced into square;
- shortest side should be at least 1600 px;
- R2 public `GET` worked while `HEAD` returned 403 in the current setup;
- UTF-8 BOM in config could hide `R2_ACCESS_KEY_ID`;
- QA results and accepted publish manifests were initially semantically mixed.

Final rules:

- upload only accepted images;
- never upload `rerun`, `review`, or `error` rows by default;
- keep `vision_acceptance_manifest.csv` as full QA results;
- keep `accepted_manifest.csv` as publishable accepted-only rows;
- read `.env` as `utf-8-sig`;
- use `GET` or range `GET` to validate public R2 URLs, not `HEAD`;
- use fast Lanczos for review speed, RealESRGAN 2x for balanced production, 4x only for final high-quality selected images.

New-category rule:

> Publish is a privileged stage. It must be blocked by QA status, not controlled by whether files exist.

### Phase 10: Template And Copy Had To Stay Objective

The listing side introduced its own lessons.

Important separation:

- Apify/reference ASIN provides variation structure and observable facts;
- seller-owned facts must come from the user or remain blank;
- image URLs must come from accepted generated images after R2 upload;
- DeepSeek can polish copy, but cannot invent facts;
- Gemini should not handle template copy.

Copy lessons:

- five bullets should be concise but still readable;
- remove subjective or emotional terms;
- keep hard numbers and concrete facts;
- no semicolon-stuffed checklist sentences;
- each bullet should add unique information;
- title, bullets, and description require separate standards.

New-category rule:

> Each category plugin needs copy constraints as well as image constraints. Objective factual copy is part of quality, not a separate afterthought.

## Failure Taxonomy

Use this taxonomy when adding a new category.

| Failure Type | Symptoms | Root Cause | Prevention |
|---|---|---|---|
| Unrelated output | poster, people, education chart, wellness graphic | polluted context or weak source binding | isolate source, true i2i, reject immediately |
| Product mutation | changed structure, missing feature, invented feature | preservation rules too vague | category invariant matrix |
| Source over-lock | output looks almost identical | prompt preserved scene, not just product | explicitly require allowed scene changes |
| Scene under-change | only color changed | no style package | product-adaptive style profile |
| Palette drift | random green/orange badges, clashing banners | no folder typography palette | exact palette fields |
| Text ghosting | duplicated, blurry, unreadable labels | text-heavy role not constrained | role-specific prompt + OCR |
| Claim loss | missing function text or changed meaning | func prompt too lifestyle-like | classify function subtype |
| Product count mismatch | one bed becomes two beds, or vice versa | VLM/prompt did not lock count | product_count_preservation QA |
| Batch partial failure | timeout, orphan processes, missing role | no task heartbeat/timeout | per-task timeout and resumable manifest |
| False publish | rejected image reaches upscale/upload | QA manifest semantics wrong | accepted-only publish manifest |
| Config failure | hidden missing keys | BOM, path, env assumptions | utf-8-sig, preflight, explicit runtime |
| Tool mismatch | OCR crashes or too slow | overly heavy model | choose task-appropriate OCR |

## What Actually Made The Bed-Frame Workflow Stable

The stable bed-frame capability is the combination of these pieces:

1. True model image-to-image generation only.
2. No local final-image redraw or overlay.
3. Product-specific invariants for bed frames.
4. Role-specific prompts for `main`, `scene`, `size`, and `func`.
5. Product-adaptive `style_profile.json`.
6. Folder-level typography and badge color system.
7. External providers for speed and context isolation.
8. Gemini for style analysis and visual QA.
9. PP-OCRv5 for text-heavy audit.
10. Selective rerun manifests with `rerun_prompt_delta`.
11. Accepted-only publish manifest.
12. R2 upload after QA.
13. Template backfill from final image URLs only.
14. Pluginization into `amazon_listing_factory`.

No single piece is enough. Removing any of the following brings instability back:

- style profile;
- product invariants;
- role-specific QA;
- accepted-only manifest;
- true image-to-image generation;
- human-visible contact sheet review for high-risk sets.

## New Category Expansion Playbook

### Step 1: Define Category Invariants

Before generation, answer:

- What visible structures must never change?
- Which materials/textures are identity-critical?
- Which features are commonly invented by models?
- Which features are commonly removed by models?
- How many products should appear?
- Are labels, screens, packaging, or compliance marks visible?

Create:

```text
products/<category>/manifest.yaml
products/<category>/prompt_rules.md
products/<category>/qa_rules.py
```

### Step 2: Define Image Roles

Do not assume every product uses bed-frame roles.

Possible roles:

- `main`
- `scene`
- `size`
- `detail`
- `material`
- `package`
- `accessories`
- `installation`
- `compatibility`
- `comparison`
- `function`

Create:

```text
products/<category>/image_roles.yaml
```

Each role should specify:

- source index rule;
- prompt template;
- text allowed or forbidden;
- preserve numbers or not;
- QA profile;
- OCR required or not.

### Step 3: Build Product-Adaptive Style Rules

Style must come from:

1. product color;
2. material;
3. product type;
4. target audience;
5. use case;
6. category expectations;
7. competitor/source evidence only after the above.

Create:

```text
products/<category>/style_rules.yaml
```

Do not let source backgrounds define the final style.

### Step 4: Assign Model Routing

At minimum:

- image generation provider;
- visual QA model;
- text copy model;
- OCR engine;
- forbidden providers.

This must be plugin-aware.

### Step 5: Create One Golden Child ASIN

For the first run:

- one parent;
- one child ASIN;
- all expected roles;
- full style profile;
- full QA;
- contact sheet;
- no upload until accepted.

Do not batch a full family until the golden sample is approved.

### Step 6: Run QA As A Hard Gate

Every generated image must end as one of:

- `accepted`
- `rerun`
- `review`
- `error`

Only `accepted` may enter:

- upscale;
- R2 upload;
- template image URL fields.

### Step 7: Selective Rerun, Not Full Regeneration

When QA fails:

- use `vision_rerun_manifest.csv`;
- rerun only failed rows;
- pass `rerun_prompt_delta`;
- keep candidate lineage;
- re-run QA after rerun.

### Step 8: Promote Category Plugin Only After Regression

A category plugin is not production-ready until:

- one real job runs end to end;
- QA gates block bad outputs;
- template fields are correctly filled;
- R2 URLs are public;
- one contact sheet is visually approved;
- failure cases are documented.

## Minimum Category Plugin Contract

Every new category should include:

```text
products/<category>/
  manifest.yaml
  image_roles.yaml
  style_rules.yaml
  prompt_rules.md
  qa_rules.yaml
  qa_rules.py
  template_mapping.yaml
  extractors.py
```

Required questions for each file:

| File | Must Answer |
|---|---|
| `manifest.yaml` | What is this category, variation structure, model route, and forbidden providers? |
| `image_roles.yaml` | What image roles exist and how do source images map to them? |
| `style_rules.yaml` | What scene, palette, lighting, and forbidden styling rules apply? |
| `prompt_rules.md` | What should prompts preserve and change for each role? |
| `qa_rules.yaml` | What scores, OCR terms, and blocking flags matter? |
| `qa_rules.py` | How does this category programmatically decide pass/rerun/review/error? |
| `template_mapping.yaml` | How do facts map into Amazon template fields? |
| `extractors.py` | How does Apify raw data become category facts? |

## Category Launch Checklist

Use this checklist before the first real batch.

### Product Rules

- Product identity invariants are written.
- Allowed scene changes are written.
- Common model hallucinations are listed.
- Product count rule is explicit.
- Role-specific preservation matrix exists.

### Style Rules

- Product color drives style.
- Source background colors are not blindly copied.
- Wall/floor/props/light rules exist.
- Infographic typography palette exists.
- Badge/icon/line colors are constrained.

### Prompt Rules

- Main and scene prompts forbid text.
- Size prompts preserve every number and arrow.
- Function prompts preserve claim meaning.
- Textless detail images do not invent labels.
- Decorative background text is removed or abstracted.

### QA Rules

- VLM scoring dimensions are category-specific.
- OCR is enabled for text-heavy roles.
- Accepted-only publish manifest is enforced.
- QA exceptions become `error`.
- Empty QA task list fails.

### Pipeline Rules

- Provider policy forbids disallowed providers.
- API keys are loaded with BOM-safe env parsing.
- Python runtime is preflighted.
- Batch generation is resumable.
- Failed rows rerun selectively.
- R2 upload is after QA only.

### Template Rules

- Seller-owned facts are not copied from competitor ASINs.
- Missing business fields are audited.
- Final image URLs come from R2 accepted images.
- AI copy cannot invent facts or claims.

## Anti-Patterns To Ban

These should be treated as category-wide hard rules:

1. Bulk-generate a new category before one golden ASIN passes.
2. Use source-image color blocks as the final style authority.
3. Ask one generic prompt to handle all roles.
4. Locally redraw text, arrows, badges, or panels as final images.
5. Upload images just because files exist.
6. Use `accepted_manifest.csv` for anything except accepted-only rows.
7. Let VLM QA errors become harmless review rows.
8. Use OCR as an editing tool.
9. Use Gemini for listing copy when DeepSeek/text model should do it.
10. Keep provider bans as memory instead of configuration.
11. Copy BED_FRAME template mappings into another category.
12. Let a plugin pass validation without `qa_rules.py`.

## Practical Heuristics

The project learned several small but important heuristics:

- If an output is unrelated once, do not keep retrying in the same polluted context.
- If all images share one camera angle, loosen scene composition while locking product geometry.
- If a function image barely changes, reduce source-locking for background/layout but keep claims locked.
- If a function image becomes lifestyle-only, strengthen detail-panel and claim preservation.
- If a banner color feels wrong, the palette probably came from source blocks instead of product fit.
- If text colors vary image by image, the folder typography palette is missing or not being used.
- If OCR misses tiny numbers but VLM/manual review sees them, mark as warning, not automatic failure.
- If Gemini asks to preserve bad source wall-poster text, the QA prompt needs to distinguish decorative text from product claims.
- If an image is accepted manually but rejected by one score, inspect the threshold and score definition before weakening the whole QA system.

## What To Carry Into `office_chair`

The office-chair plugin should not copy bed-frame rules. It should copy the method.

Bed-frame invariants:

- rails;
- headboard;
- slats;
- legs;
- ladder/slide if present;
- wood or metal finish.

Office-chair invariants should instead be:

- backrest silhouette;
- armrest shape;
- seat cushion geometry;
- gas lift;
- wheel base;
- caster count;
- mesh/leather/fabric texture;
- adjustment levers;
- headrest/lumbar support if present.

Bed-frame scene changes:

- bedroom;
- bedding;
- pillows;
- rug;
- wall art;
- nightstand.

Office-chair scene changes:

- desk;
- monitor;
- lamp;
- plant;
- books;
- floor;
- office wall;
- cable-light workspace props.

The same architecture applies, but the plugin vocabulary must change.

## Final Operating Principle

The bed-frame project became stable when it stopped treating image generation as a single model call and started treating it as a controlled production system.

For every new category, build the system in this order:

1. Category invariants.
2. Image roles.
3. Product-adaptive style package.
4. Prompt compiler rules.
5. Model routing.
6. VLM and OCR quality gates.
7. Selective rerun.
8. Accepted-only publish.
9. Template mapping.
10. Regression fixture.

If a new category skips steps 1 to 4, the model will generate visually plausible but commercially unsafe images. If it skips steps 6 to 8, bad images will enter the Amazon template. If it skips step 10, every later improvement risks breaking what already worked.
