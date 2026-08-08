# Prompt, Recovery, QA, and Security Design

## Goal

Remove the production blockers proven by the June 27 runs without adding a new controller or compatibility path.

## Design

The existing authorities remain in place. `ImageTaskV5` owns immutable task intent, `CandidateManifest` owns generated candidates, `job_state.json` owns runtime status, `QAEvidenceV4` owns automatic evidence, and ReleaseManifest owns publishing. The repair separates content identity from execution provenance so provider order, credentials, and revision text cannot invalidate a successful candidate.

Prompt v16 compiles each semantic instruction once. It retains the validated family style and per-role visual execution, but removes duplicated family, composition, graphic, preservation, and forbidden blocks. Compiled prompts target 7,200 characters; enabled image providers declare the already exercised 12,000-character ceiling. Prompt text is never blindly truncated.

Candidate manifests store both the base task prompt fingerprint and the exact request prompt fingerprint. A revised candidate remains current for the same ImageTask even though its revision request differs. Provider capability changes unlock failed work but never invalidate successful candidate bytes.

Measurements are separated into confirmed product facts, source-visible labels, render-authorized US labels, and labels to remove. A dual-unit source such as `5.91 ft / 1.8 m` renders `5.91 ft` for the US marketplace while retaining the metric label only in audit evidence.

QA-lite stops pretending that unobserved structure and count gates passed. It keeps deterministic local gates and reports non-local visual facts as inconclusive for human review. Scene count semantics preserve source composition; a source scene containing two beds is not treated as a one-unit package violation.

Copy asks the model for bullets no longer than 120 characters and accepts results through 150 characters. Results beyond 150 receive one model repair and then fail closed. Template Item Highlight remains independently limited to 125 characters.

Visual planning provenance is redacted before persistence. Style and task content fingerprints exclude provider provenance. Destructive StyleSystem substitutions are removed; model output is validated or repaired, and category main/scene policies override conflicting visual prose before prompt compilation. A family uses one photo provider affinity and one infographic provider affinity, with other providers used only after failure.

## Deletions

- Prompt v15 duplicate family/composition/graphic/preservation compiler paths.
- Exact revised-request prompt hash as candidate-currentness authority.
- Raw visual-planning client dictionaries in artifacts and task fingerprints.
- QA-lite default `pass` for unevaluated structure, count, components, and drift.
- Destructive quoted-text and font-size substitutions in StyleSystem.
- The shared 125-character model-and-audit bullet limit.

## Verification

Targeted tests cover prompt size and content, secret redaction, revised candidate reuse, error resolution, dual-unit US rendering, source-scene multiplicity, Copy 120/150 behavior, bed-frame category style enforcement, and provider family affinity. The canonical production suite runs once at the end and must remain at or below 100 cases and 60 seconds.
