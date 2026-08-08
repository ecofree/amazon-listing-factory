# Image Generation Quality Baseline - 2026-06-12

Historical replay job: `jobs/B0C9HV9Z84_20260612T050917410651`

This file is the frozen P0 baseline for the prompt/planner/provider upgrade. It records the defects that the new implementation must not reproduce.

## Workload

- 8 child variants
- 64 image slots
- 8 main, 20 scene, 8 size, 28 func
- 68 generated images for 64 slots
- 62 slots generated once, 1 slot generated twice, 1 slot generated four times

## Historical Prompt Defects

| Role | Slots | Historical prompt length | Exact limit hits |
|---|---:|---:|---:|
| main | 8 | 14,000 | 8 |
| scene | 20 | 13,993-14,000 | 14 |
| size | 8 | 11,999-12,000 | 7 |
| func | 28 | 11,996-12,000 | 21 |

Historical size/func prompts could begin with an isolated `I`, followed by `Retained hard prompt contract excerpts`, a middle-omission marker, and a detached JSON tail. This is a structural prompt failure, not a model-capability result.

Representative duplicated-line overhead:

- main: 8.1%
- scene: 13.9%
- size: 10.2%
- func01: 7.4%

## Planner Defects

Representative size brief length: 35,301 characters.

- family master plan: 12,130 characters
- visual system profile: 5,583 characters
- per-image design spec: 1,401 characters
- measurement overlay plan: 182 characters

The brief was large but the role-specific geometry was vague. It did not reliably bind each dimension to a visible product edge, define information priority, or prevent duplicate overall/component dimension labels.

## Generation and QA Defects

- The historical default for size/func was two cross-provider image candidates.
- The job produced 61 QA passes and 7 first-pass failures, but the final manifests accepted all 64 slots.
- QA acceptance therefore measured factual hard-gate completion, not visual quality.
- Scene outputs often preserved the source camera, bedding arrangement, wall-art placement, and room structure too closely.
- Size output omitted useful verified information and repeated overall dimensions as component labels.
- Func output became cleaner but less informative because supporting values and visible feature evidence were removed.

## P0 Exit Criteria

The upgraded path must satisfy all of the following during replay:

- No retained-excerpt or middle-omission markers in production prompts.
- No fixed pixel size in the model prompt; the requested composition is square `1:1`.
- One generated image per slot by default.
- Provider transport fallback does not create an additional content candidate.
- Gemini role plans preserve concrete scene-change axes, size dimension bindings, and func feature bindings.
- QA does not reject an image merely for its pixel aspect-ratio metadata.

