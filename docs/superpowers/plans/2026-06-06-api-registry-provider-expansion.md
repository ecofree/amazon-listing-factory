# API Registry Provider Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified API Registry so Gemini 2.5 classification/QA endpoints, Gemini 3.5 visual-planner endpoints, and GPT Image 2 generation providers can be added from one config surface and automatically routed into the correct runtime pools.

**Architecture:** Add `core/api_registry.py` as the single parser, normalizer, scope inferencer, and validator for registry entries. Existing env configs remain authoritative and are merged with registry-derived entries in `core/vision_qa.py` and `core/image_generation.py`. `scripts/factory.py validate` reports malformed registry entries and missing token env names without exposing secret values.

**Tech Stack:** Python 3.12, existing `unittest`, JSON env/file config, existing Gemini client code in `core/vision_qa.py`, image provider code in `core/image_generation.py`.

---

### Task 1: Registry Parser

**Files:**
- Create: `core/api_registry.py`
- Test: `tests/test_core.py`

- [ ] Write tests proving JSON env and file registries load a list of entries.
- [ ] Implement parsing for `AMAZON_FACTORY_API_REGISTRY` and `AMAZON_FACTORY_API_REGISTRY_FILE`.
- [ ] Normalize `scope`, `family`, `model`, `base_url`, `url`, `key_env`, `api_key`, `bearer_env`, and `enabled`.
- [ ] Infer scope when absent: `gemini-3.5*` -> `visual_planner`, `gemini-*` -> `vision_qa`, `gpt-image-2*` -> `image_generation`.

### Task 2: Gemini Runtime Merge

**Files:**
- Modify: `core/vision_qa.py`
- Test: `tests/test_core.py`

- [ ] Write tests proving registry Gemini 2.5 entries appear in `_gemini_clients()`.
- [ ] Write tests proving registry Gemini 3.5 entries appear only for `client_scope="visual_planner"`.
- [ ] Merge registry clients after explicit env clients and before optional VIP/Xiaomi clients, with de-duping.

### Task 3: Image Generation Dynamic Providers

**Files:**
- Modify: `core/image_generation.py`
- Test: `tests/test_core.py`

- [ ] Write tests proving registry GPT Image 2 providers are built-in image providers.
- [ ] Write tests proving registry image providers are auto-added to `_provider_order()`.
- [ ] Support provider `api_type` values `highwayapi` and `async_image_generation`.
- [ ] Keep existing HighwayAPI request contract and provider-specific env overrides intact.

### Task 4: Validation And Docs

**Files:**
- Modify: `scripts/factory.py`
- Modify: `config.example.env`
- Create: `configs/api_registry.example.json`
- Modify: `README.md`
- Modify: `docs/operator_runbook.md`
- Test: `tests/test_core.py`

- [ ] Add validation warnings for missing `key_env` env values and errors for malformed entries.
- [ ] Document the API Registry schema and examples.
- [ ] Keep secrets out of example files.

### Task 5: Verification

**Files:**
- All changed files

- [ ] Run focused tests: `python -m unittest tests.test_core`
- [ ] Run fast production checks: `powershell -ExecutionPolicy Bypass -File .\scripts\run_fast_checks.ps1`
- [ ] Run `scripts/factory.py validate`
- [ ] Run full suite if focused tests reveal broad integration risk.
