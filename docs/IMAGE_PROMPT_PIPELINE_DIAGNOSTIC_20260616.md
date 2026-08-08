# Image Prompt Pipeline Diagnostic - 2026-06-16

## Scope

Five requested parent ASINs were tested only through prompt generation:

- B082413JZW
- B0FHB4Y4V9
- B0GF2357FX
- B0F4KL1C4H
- B0GG3DF88S

No image-generation provider was called. No upload was attempted. Production
source code, configuration, and test code were not modified.

The production stop point was `core.image_generation.build_image_plan()`,
which performs:

1. source evidence construction;
2. product truth construction;
3. role contract construction;
4. Child-level Gemini visual planning;
5. visual-plan validation;
6. final GPT image prompt compilation.

## Result

### Production-path result

The unmodified production path completed prompt generation for:

- Jobs: 0 / 5
- Children: 0 / 16
- Prompt artifacts: 0 / 127

Every Job required one or more isolated diagnostic interventions before the
next stage could be observed.

### Diagnostic result

After using isolated Job copies and runtime-only diagnostic mappings:

- Jobs reaching PromptArtifact: 5 / 5
- Children reaching PromptArtifact: 16 / 16
- Prompt artifacts compiled: 127 / 127
- Generated images: 0

This is diagnostic coverage, not production success.

| Parent ASIN | Category | Children | Prompt tasks | Average chars | Max chars | Prompts over 8,000 |
|---|---:|---:|---:|---:|---:|---:|
| B082413JZW | bed_frame | 1 | 7 | 6,596 | 8,120 | 1 |
| B0FHB4Y4V9 | bathroom_cabinet | 1 | 8 | 7,278 | 8,759 | 1 |
| B0GF2357FX | medicine_cabinet | 5 | 40 | 7,009 | 9,141 | 8 |
| B0F4KL1C4H | bathroom_cabinet | 2 | 16 | 7,875 | 9,756 | 9 |
| B0GG3DF88S | artificial_tree | 7 | 56 | 7,252 | 9,121 | 14 |
| Total | 4 categories | 16 | 127 | 7,219 | 9,756 | 33 |

Role-level prompt results:

| Role family | Count | Average chars | Max chars | Over 8,000 |
|---|---:|---:|---:|---:|
| main | 16 | 5,708 | 6,596 | 0 |
| scene | 31 | 6,365 | 7,384 | 0 |
| size | 16 | 8,382 | 9,756 | 12 |
| func | 64 | 7,720 | 9,121 | 21 |

The current 8,000-character hard limit rejects 33 / 127 prompts (26.0%),
including 12 / 16 size prompts (75.0%).

## Stage Findings

### 1. Runtime entry point is not deterministic

The ordinary `python` command used a runtime without `jsonschema`, so all five
initial fetches failed before business logic. The bundled project Python had
the dependency and allowed the same commands to proceed.

The CLI does not perform an early dependency/runtime preflight. A wrong Python
can create partial Job state before failure.

### 2. Role classification is image-local, but acceptance is family-global

Three of five Jobs were blocked by multiple `main` assignments:

- B082413JZW: two mains;
- B0FHB4Y4V9: three mains;
- B0GF2357FX family: multiple children had three mains.

The observer often included the correct alternate role in `role_candidates`,
but the program selected each image independently and then hard-failed because
the final set did not contain exactly one main.

Examples of false mains included:

- furnished room scenes;
- bathroom lifestyle scenes;
- kitchen storage scenes;
- decorative cabinet scenes.

Selecting the highest non-main candidate is also unsafe. In the diagnostic
copy, some false mains were demoted to `func` even though they were visually
scene images. That immediately created required function roles without
function evidence.

### 3. Thumbnail rejection works, but artifact handling remains incomplete

B082413JZW contained a 300 x 166 thumbnail. It was correctly rejected by the
600-pixel minimum rule.

The remaining seven references were usable. The rejected row remained
unclassified, which is acceptable only if downstream completeness uses valid
assets rather than raw row count.

### 4. VisualObservationV2 is produced and then dropped

Full visual observations existed in per-image classification reports, but the
download manifest omitted `visual_observation`.

Downstream source evidence reads the manifest field, not the classification
report. Therefore every valid downloaded row arrived at ProductTruth without
the observation that had already been computed.

Observed affected rows:

- valid reference rows: 127;
- rows missing propagated VisualObservationV2: 127.

This is not a model-quality failure. It is an artifact ownership and
serialization failure between two adjacent stages.

### 5. Diagnostic observations are treated as hard factual conflicts

Some artificial-tree observations reported possible compositing or lighting
inconsistency. These entries had no severity.

The validator defaults a missing severity to `hard`, so an aesthetic or image
forensics note becomes a contract conflict and stops production.

Conflict severity must be explicit and enum-based. Missing severity must not
silently escalate to a hard factual conflict.

### 6. Function evidence contract is structurally too strict for observer output

Across the diagnostic dataset:

- function roles: 64;
- roles already containing accepted function evidence: 14;
- roles requiring diagnostic evidence binding: 50.

The observer frequently returned readable claim labels but no exact
`product_part`. Fact arbitration rejects those claims. The role contract then
requires every required func role to contain evidence-bound callouts, so the
pipeline stops.

This creates a closed failure loop:

1. classification creates a func role;
2. observer returns the visible copy but omits or varies the part label;
3. fact arbitration rejects it;
4. contract requires evidence for the role;
5. production stops.

The diagnostic bindings also showed why blind auto-healing is unsafe: a
misclassified scene can be assigned a long bullet sentence or an unrelated
part merely to satisfy the schema.

### 7. ProductAnchorGraph is verbose but lacks topology

Across 127 role contracts:

- average natural-language anchors per prompt: 18.2;
- average graph components per prompt: 12.0;
- graph relationships: 0;
- explicit forbidden product parts: 0.

The graph repeats synonymous components and image-specific observations while
omitting the relationships that define product topology.

Examples:

- the same daybed and trundle appeared multiple times as `main_frame`,
  `main_body`, `trundle_frame`, `trundle`, and `accessory`;
- artificial-tree scene props such as planter pot and faux soil could become
  product-owned components even when the product is stake-mounted and the
  planter is not included.

The graph therefore spends many characters without reliably expressing:

- which part is attached to which;
- which objects are included products versus replaceable staging;
- which parts are confirmed absent;
- which quantities and relative positions must remain invariant.

### 8. Every Child-level planner prompt violates the production limit

Planner prompts measured 49,722 to 66,529 characters. All 16 Child prompts
exceeded the 30,000-character production limit.

The production path therefore cannot call Gemini for any tested Child.

The planner input repeats:

- product truth;
- image feature map;
- role contracts;
- role source context;
- visual constraints;
- category rules;
- a long natural-language output schema;
- shared facts again for every role.

The architecture claims compact facts, but the serialized artifact remains
large and repetitive.

### 9. Default planner output budget truncates multi-role JSON

For the seven multi-Child planner calls first tested with the default 8,192
output-token budget:

- valid JSON: 2;
- truncated or invalid JSON: 5.

The two single-Child responses tested earlier were valid, giving a combined
default-budget result of 4 valid and 5 invalid unique Child responses.

Raising the diagnostic output budget to 16,000 produced complete JSON for all
retried Children. This is evidence of an oversized response schema, not a
recommendation to make 16,000 the production default.

The response repeats the complete category scene plan and many visual-system
fields inside every per-image plan. A compact plan should return shared data
once and role-specific deltas only.

### 10. Planner prompt and validator describe different schemas

Sixteen complete raw planner responses produced four different schema values:

- `visual-plan-v7`: 10;
- `VisualPlanV7`: 4;
- `listing-visual-token-v4`: 1;
- `listing-visual-master-plan-v7`: 1.

Only the first literal is accepted.

Five different visual-profile field shapes were observed. Common variations:

- `typography` versus `typography_hierarchy`;
- `icon_system` versus `icon_family` versus required `icon_style`;
- `line_system` versus required `line_style`;
- `spacing_grammar` versus required `layout_grammar`;
- `background_language` versus required `background_style`;
- `colors` versus required `palette`;
- string values where the validator requires objects.

Additional drift:

- generic role `func` used instead of `func01` to `func05`: 5 plans;
- scene plans missing four change axes: 17 plans;
- top-level duplicate measurement plans: 1;
- top-level duplicate callout layouts: 4;
- per-image visual Token mismatch: 7;
- visible-text drift from the contract: 6;
- missing lighting, camera, or negative-staging fields: 5 each;
- `visible_product_edge` returned where the validator requires
  `product_edge`;
- exact dimension text such as `30.5"` changed to `30.5""`.

The current prompt is a prose description of a schema. The validator is a
different executable schema. They are not generated from one source.

### 11. Shared scene design conflicts with preservation-heavy roles

The planner was told to share one category scene design across the family. It
copied the shared three-quarter camera plan into size and function roles.

The validator correctly requires size and func to preserve the source camera.
The planner instruction simultaneously requires each per-image spec to copy
the shared category plan.

This is a direct contract contradiction:

- family consistency says copy the shared camera plan;
- role preservation says keep the reference camera.

Size and func should inherit shared style tokens, not shared scene camera or
staging.

### 12. A valid family plan is invalidated by field placement

The family-plan conversion stores `category_scene_design_plan` under the nested
`family_visual_master_plan` object in each visual brief.

The later task validator reads `category_scene_design_plan` from the brief
top level. It therefore sees an empty object and rejects an otherwise valid
plan.

This is an internal artifact-shape defect independent of model output.

### 13. Final GPT prompt is dominated by an inefficient product lock

Average final prompt section size:

| Section | Average chars |
|---|---:|
| Product lock | 3,625 |
| Role objective | 1,353 |
| Visible text contract | 445 |
| Gemini design spec | 1,497 |
| Negative constraints | 300 |

The product lock consumes about half of the entire prompt. It repeats the
complete Child identity graph for every role, including parts that are not
visible or relevant to that role.

The longest prompts are size and func because they add dimension or function
facts on top of the same full graph. This is why the roles that should be the
most controlled are also the roles most frequently rejected by the prompt
length limit.

## Root Cause

The failures are not independent bugs. They come from five architectural
errors.

### A. The same facts are represented by multiple mutable artifacts

Classification reports, download manifests, SourceEvidence, ProductTruth,
RoleContract, VisualPlan, visual-brief cache, and PromptArtifact repeat or
rename the same data.

Fields are copied manually, so a fact can be present in one artifact and absent
in the next.

### B. Model-owned and program-owned fields are mixed

Gemini is asked to return:

- schema versions;
- role IDs;
- contract IDs;
- visual Token IDs;
- exact visible text;
- exact dimensions;
- exact evidence IDs;
- creative design decisions.

Only the last item is a model decision. The rest must be injected
deterministically by the program.

### C. The schema has no single source of truth

The prompt describes field names in prose. The validator independently encodes
different field names and types. Runtime cache validation adds more placement
rules.

The model is being blamed for violating a schema it was never shown exactly.

### D. "Unified visual system" is implemented as duplicated full plans

Shared palette and typography are useful. Shared camera, room layout, and
staging are not valid for size and func reference-edit roles.

The response repeats shared data per image, which increases latency,
truncation, and inconsistency.

### E. Product locking is text-heavy but geometry-light

The prompt contains many names, synonyms, positions, and repeated warnings,
but no reliable canonical topology or object-ownership graph.

More words have not produced more control.

## Required Repair Strategy

The repair must replace and delete superseded paths in the same task. It must
not add another synchronization or fallback layer.

### R0. Freeze the evidence set

Use these 16 Children and 127 roles as the prompt-stage regression set.

Do not generate images while repairing classification, artifact contracts,
planner schema, and prompt compilation.

Acceptance:

- every failure is represented by a stage, error code, expected value,
  observed value, and artifact ID;
- no historical Job is used as a production cache input.

### R1. One ReferenceObservation artifact and one global role resolver

The visual observer should return observations and role candidates only.

A deterministic Child-level resolver must assign the final role set using:

- exactly one qualified main;
- size requires a measurement graph with product-edge bindings, normally
  multiple geometric dimensions;
- one under-bed clearance value in a feature graphic remains func, not size;
- scene requires environmental staging without a product measurement graph;
- func requires evidence-backed feature communication;
- detail requires a bounded product-part close-up.

The resolver must optimize the full Child role set, not choose each image
independently.

The download manifest must store the accepted `ReferenceObservationV3` object
and its fingerprint. Downstream stages read only that object.

Acceptance:

- all 127 valid references carry current observations;
- one and only one main per Child;
- no scene is silently demoted to func;
- no second observation copy exists in classification side files for
  production consumption.

### R2. Canonical ProductAnchorGraph

Build a compact, canonical graph from main identity plus cross-image evidence.

Required nodes:

- canonical product components;
- sold-unit quantity;
- material and color identity;
- included accessories;
- explicitly non-included staging objects.

Required edges:

- attached-to;
- contained-in;
- above/below;
- left/right;
- slides-under or folds-into;
- count relationship.

Scene props must be stored under object ownership, not product components.

Prompt serialization must use a role-specific graph slice:

- main: complete sold-product silhouette and count;
- scene: complete visible product topology, no infographic-only parts;
- size: components and edges touched by measurements;
- func: components bound to selected callouts.

Acceptance:

- zero duplicate canonical components;
- at least one topology relationship for every multi-part product;
- no planter, pillow, bedding, towel, decor, faux soil, or room object becomes
  product-owned unless verified as included;
- product-lock section target: 1,500 to 2,200 characters.

### R3. Evidence binding before role contracts

The observer returns atomic observations:

- claim text;
- visible target region;
- candidate component ID;
- confidence.

The program maps observations to canonical components and verified facts.
Gemini does not choose fact IDs.

If a classified func image has no bindable visible function, the resolver must
reconsider the role before the contract is created. It must not create a
required func role and then fail downstream.

Acceptance:

- function evidence binding rate: 100%;
- no diagnostic or arbitrary binding;
- every callout has one verified fact and one visible canonical component;
- no full bullet sentence is used as a callout.

### R4. Program-owned plan envelope, Gemini-owned creative payload

The program constructs and owns:

- `schema_version`;
- `brief_id`;
- `role`;
- `contract_id`;
- `change_mode`;
- `visual_token_id`;
- exact visible text;
- exact dimensions;
- exact function labels and evidence bindings.

Gemini returns only:

- one shared visual-system payload;
- one category scene payload;
- per-role creative deltas.

Per-role deltas must not repeat the shared profile or category plan.

For size and func, Gemini receives fixed preservation policies and must not
return a new camera policy. They inherit shared palette, typography, icon, line,
and spacing tokens only.

Use an actual JSON Schema or provider structured-output mode. The prompt and
validator must be generated from the same schema definition.

Acceptance:

- planner input target: at most 15,000 characters;
- planner output target: at most 6,000 characters;
- exact schema-valid first response: at least 95%;
- no schema-version, role, Token, text, dimension, or evidence field is
  authored by Gemini;
- no production normalization that repairs model facts.

### R5. Compact role-specific GPT prompt compiler

Keep the five-section priority structure, but remove repetition.

Rules:

- send human-readable facts, not hashes or internal IDs;
- send only role-visible graph components;
- do not repeat full Child anchors and full graph;
- do not repeat the same product-lock warning in multiple sections;
- size sends immutable measurements and measured edges only;
- func sends exact callouts and bound visible parts only;
- scene sends the product topology and the creative environment plan;
- Gemini visual-system data is referenced once and reduced to the fields used
  by the current role.

Targets:

- main: 3,000 to 4,500 characters;
- scene: 4,000 to 6,000 characters;
- size: 5,000 to 7,000 characters;
- func: 4,500 to 6,500 characters;
- hard maximum: 8,000 characters;
- 127 / 127 prompts compile without truncation or diagnostic overrides.

### R6. Planner response validation at the provider boundary

Pass a response validator into the visual-planner client.

A syntactically incomplete or schema-invalid response must be rejected before
it becomes a cache artifact. Retry the same planning attempt with another
healthy planner provider; do not let downstream code discover truncation.

Do not solve the current bloat by permanently raising output tokens. Compact
the schema first. The normal output budget should then be sufficient.

Acceptance:

- truncated JSON never enters visual-plan cache;
- provider transport failures and invalid structured responses are recorded
  separately;
- one bad planner provider does not block the Child;
- no silent single-image planning fallback.

### R7. Current-chain test and production admission

After implementation:

1. run targeted unit tests for resolver, observation propagation, anchor
   ownership, evidence binding, planner schema, and prompt budgets;
2. run this frozen 127-role prompt-stage dataset with no diagnostic patching;
3. run the current production suite once;
4. only then generate images for one approved Child.

Prompt-stage admission:

- Jobs reaching PromptArtifact: 5 / 5;
- Children reaching PromptArtifact: 16 / 16;
- role-set conflicts: 0;
- missing observations: 0;
- arbitrary function bindings: 0;
- planner prompts over 15,000 chars: 0;
- invalid first planner responses: no more than 5%;
- final prompts over 8,000 chars: 0;
- exact visible-text drift: 0;
- single-image visual-planning fallback: unreachable and deleted.

## Final Conclusion

The current pipeline is not blocked by one weak model or one bad prompt. It is
blocked by an unstable contract architecture:

- image-local role choices are validated as a family;
- observations are dropped between artifacts;
- model and program share ownership of deterministic fields;
- planner prompt, validator, and cache expect different schemas;
- shared visual planning incorrectly shares camera and staging with
  preservation-heavy roles;
- product locks are verbose but lack topology;
- final prompts exceed their own production budget.

The next change should not add more repair mappings. It should make program
fields immutable, reduce Gemini to creative decisions, generate prompt and
validator contracts from one schema, compact the shared plan, and physically
delete the superseded paths and tests.
