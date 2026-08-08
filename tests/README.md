# Test Suites

`scripts/run_production_tests.py` is the canonical production admission suite.
It lists representative contracts for the currently reachable production chain.
Large targeted regression files may contain additional current-chain tests, but
they are not release gates unless explicitly selected by that script.

Do not use `python -m unittest discover -s tests` as a release gate. Retired
runtime behavior and its tests must be physically deleted, not hidden behind
suite filters or moved to a legacy test area.

## Permanent Budget

- At most 75 current-chain cases and 60 seconds locally. The current admission
  suite intentionally stays well below that ceiling; a new regression replaces or merges
  overlapping coverage in the same task instead of increasing the count.
- Run targeted tests while editing and the production suite once at completion.
- Do not run historical/full discovery without explicit user instruction.
- Add only the smallest test reproducing a reachable production failure; merge
  or delete overlapping coverage in the same area.
- Do not add SP-API tests before SP-API is active in production.
