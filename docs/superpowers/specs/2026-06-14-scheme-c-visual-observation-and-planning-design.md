# Scheme C Visual Observation And Planning Design

## Goal

Build one production control chain in which Gemini 3.5 performs visual observation and child-level art direction, OCR owns exact characters and coordinates, deterministic code owns product truth and permissions, and GPT Image only executes a validated role-specific edit contract.

## Non-Negotiable Control Order

```text
reference images + OCR
-> VisualObservationV2
-> ProductIdentityGraphV2 + ProductStateGraphV1 + ObjectOwnershipV1
-> ImageRoleContractV4 + RoleChangeBudgetV1
-> VisualPlanV6
-> PromptArtifactV4
-> image generation
-> output observations
-> deterministic QA decision
```

Each stage may read only upstream immutable artifacts. A later model may not rewrite product facts, role permissions, exact text, dimensions, or valid product states.

## 1. Visual Observer

### Model routing

- Primary: a Gemini 3.5 Flash endpoint that passes a real image probe.
- Fallback: Gemini 2.5 Flash/Lite observation only.
- Text-only endpoints are never eligible for visual observation or visual planning with reference images.
- Endpoint health is recorded by capability, not only by HTTP success.

### Output

`VisualObservationV2` contains observations only:

- multi-label role evidence;
- visible product components and their spatial relations;
- visible product states and visible instance count;
- product-adjacent objects;
- environment and graphic overlays;
- raw visible text candidates;
- numeric candidates and geometric bindings;
- composition;
- uncertainty and conflict evidence.

It does not contain:

- final role;
- editable permissions;
- product truth;
- pass/fail;
- QA error codes;
- invented fact IDs.

### Request sizing

Each image is observed independently. Cross-image reconciliation is a separate compact request. This prevents six-image outputs from growing until JSON truncation.

## 2. OCR Character Authority

OCR is authoritative for exact visible characters, numeric values, units, and text boxes when confidence is sufficient. Gemini explains semantic meaning and binds text to product parts.

The merger:

- canonicalizes comparison symbols to ASCII (`<=`, `>=`);
- retains raw OCR and normalized text separately;
- never lets OCR decide image role;
- never lets Gemini silently replace an OCR value;
- marks unresolved disagreements as conflicts.

## 3. Deterministic Product Truth

### ProductIdentityGraphV2

Components contain:

- stable component ID;
- part type;
- quantity or unknown;
- material, color, finish;
- spatial position;
- parent/child and attachment relationships;
- evidence image IDs;
- confidence and verification status.

Unknown quantity, position, or relation remains unknown. Defaults such as quantity `1` are forbidden.

### ProductStateGraphV1

The graph records valid visible configurations, for example:

```text
stacked_bunk -> separated_twin_beds
```

Each state contains component presence, visible product instance count, and evidence. QA compares an output against the role's allowed state, not against one universal reference pose.

### ObjectOwnershipV1

Every observed object is classified as:

- `core_product`
- `included_accessory`
- `optional_product_component`
- `replaceable_staging`
- `environment`
- `graphic_overlay`
- `unknown`

Only deterministic evidence intersections may promote an object to product ownership. `unknown` is never automatically editable or locked as a confirmed product part.

## 4. Role Change Budget

`RoleChangeBudgetV1` is the permission boundary consumed by planning, prompting, and QA.

### Main

- preserve product state, geometry, color, material, parts, count, and view;
- replace background with the contracted catalog background;
- prohibit text and staging.

### Scene

- preserve product identity and one allowed product state;
- permit bounded camera change and semantic rerendering;
- permit replacement of bedding, props, room, floor, wall, lighting, and decor;
- prohibit product component changes.

### Size

Use `preserve_and_restyle`:

- lock product geometry, viewpoint, perspective, numeric values, measurement targets, and semantic line-to-edge bindings;
- allow background, title, typography, label placement, line color, line weight, solid/dashed style, badge appearance, and non-product layout;
- prohibit dimension invention, deletion, duplication, or rebinding.

### Func/Detail

Use `preserve_product_recompose_graphics`:

- lock product identity, demonstrated part, fact meaning, and hard numbers;
- allow non-product staging, panel layout, typography, icons, connectors, and concise evidence-backed wording;
- permit bounded camera/crop change only when the demonstrated component remains visible.

## 5. Gemini Child-Level Visual Planning

Gemini 3.5 receives only:

- compact product identity and valid states;
- role contracts and change budgets;
- compact observations;
- category design grammar;
- target market and brand tone.

It does not receive full title, bullets, description, raw OCR dumps, QA implementation, or provider mechanics.

`VisualPlanV6` outputs:

- one shared visual system;
- product-derived palette proposal;
- typography, icons, cards, connectors, and spacing;
- category scene plan;
- per-role composition and change selections;
- exact size bindings or function bindings copied from contracts.

The program validates the plan but never repairs missing design facts. Invalid plans may be replanned once at child level. There is no single-image planning fallback.

## 6. Visual Token Freedom

Tokens are divided into:

- hard tokens: product color truth, shared font family class, shared icon family, connector grammar, spacing and safety constraints;
- proposed tokens: exact palette, room style, background treatment, lighting, textile palette, card treatment, and image-specific composition.

Gemini proposes soft tokens from product identity. The program validates color syntax, contrast, role consistency, and contract compliance. A fixed brown palette is not forced onto every bed frame.

## 7. Prompt Compilation

The only prompt compiler emits:

1. reference priority and immutable product identity;
2. allowed product state;
3. role change budget;
4. exact text and numeric contract;
5. Gemini design instructions;
6. prohibited changes and one targeted rerun correction.

Size and function prompts explicitly describe what must remain and what may change. Global wording such as "redesign everything" is prohibited for preservation-heavy roles.

## 8. QA

QA remains split:

- local output validator;
- OCR text/dimension comparator;
- product identity/state comparator;
- role contract validator;
- visual selector.

Gemini returns entity observations only. Deterministic code maps them to hard failures. Aesthetic diagnostics rank passing candidates and never reject.

## 9. Failure Handling

- A transport failure does not create a candidate.
- An endpoint that returns `image_received=false` is capability-failed and temporarily removed from visual routing.
- Malformed or incomplete observation output is retried once using another capable endpoint.
- Missing evidence is not auto-filled.
- Cross-image conflicts block the affected role before generation.
- Child-level planning failure blocks the child; it never becomes a local preset or single-image plan.

## 10. Admission Criteria

- visual observer endpoint image-receipt rate: 100% on probe set;
- mixed-role recall: at least 95%;
- required size-number recall: at least 99%;
- OCR/Gemini unresolved numeric conflict: 0 at generation time;
- product ownership contradiction: 0;
- contract/plan permission conflict: 0;
- single-image planner fallback: 0;
- model-created QA error code: 0;
- size product-state and measurement-binding preservation: at least 98%;
- func evidence binding: 100%.

