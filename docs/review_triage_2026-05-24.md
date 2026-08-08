# Historical Review Triage 2026-05-24

This note records issues found before the bed-frame workflow was migrated into the core `amazon_listing_factory` pipeline. It is not a description of the current execution path.

## Verdict

The review is directionally correct. The project is useful but not yet production-stable without gate fixes.

## Confirmed

- `config.local.env` has a UTF-8 BOM and the loader previously used `utf-8`, which could hide the first key.
- QA artifacts mixed full QA rows and publishable accepted rows.
- Failed QA rows could still appear production-ready if a later smoke manifest marked them accepted.
- Gemini vision calls had no retry.
- API exceptions were downgraded into non-failing review rows.
- The factory is tightly coupled to BED_FRAME and should be pluginized before adding more categories.

## Corrected

- `load_env()` now reads `utf-8-sig`.
- The old QA script split full QA results into `vision_acceptance_manifest.csv` and accepted-only rows into `accepted_manifest.csv`.
- QA exceptions now become `error` and return a non-zero exit code.
- `run_full_pipeline.ps1` fails before upscale/upload if QA has non-accepted rows.
- `run_full_pipeline.ps1` verifies the selected Python executable before running.
- `gemini_vision_client.py` now retries transient request failures.
- `.gitignore` excludes `.xlsm` workbooks.

## Partly Corrected Interpretation

The current `run_full_pipeline.ps1` did not always overwrite QA via `build_acceptance_manifest.py` after VisionQA. That branch only runs when VisionQA is disabled. The real defect was artifact semantics: a file named `accepted_manifest.csv` could contain non-accepted rows, and smoke-test manifests could later mark failed images as accepted.
