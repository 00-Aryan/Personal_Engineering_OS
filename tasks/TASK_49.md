# TASK_49: Phase 7 Verification — Clean Install Test

## Engineering Context

This is the final verification task before the open source launch.
It simulates exactly what a new developer would experience when
finding ProjectOS on GitHub for the first time.

The test is simple: does everything work from a clean state?

## Pre-conditions
Read TASK_45 through TASK_48 result files.
Read install.py completely.
Read README.md — this is what the user will read.

## Deliverables

### 1. scripts/clean_install_test.sh

Simulates a clean install in a temporary directory:

```bash
#!/bin/bash
set -e

TMPDIR=$(mktemp -d)
echo "Testing clean install in $TMPDIR"

# Clone
git clone . $TMPDIR/projectos_test
cd $TMPDIR/projectos_test

# Install non-interactively
python install.py --no-prompt

# Verify CLI works
uv run --no-sync projectos --help
uv run --no-sync projectos config validate
uv run --no-sync projectos template list

# Run smoke test
python smoke_test.py --ci

# Cleanup
cd /
rm -rf $TMPDIR

echo "CLEAN INSTALL TEST: PASSED"
```

### 2. Run the clean install test

```bash
bash scripts/clean_install_test.sh
```

Document the output in TASK_49_RESULT.md.
If it fails: fix the issue before marking TASK_49 done.

### 3. Final metrics collection

Run and record:
```bash
# Test count
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30 | tail -3

# Install time
time python install.py --no-prompt

# CLI startup time
time uv run --no-sync projectos --help

# Smoke tests
python smoke_test.py --ci
python scripts/evaluation_smoke.py
python scripts/intelligence_smoke.py
python scripts/observability_smoke.py
```

### 4. Update pyproject.toml
Bump version to 0.5.0.

### 5. Update tasks/PHASES.md
Mark Phase 7 COMPLETE.
Add Phase 8 section:
  Phase 8: Open Source Launch (TASK_50-53) — PENDING

### 6. Write docs/RELEASE_NOTES_v0.5.0.md

# ProjectOS v0.5.0 Release Notes

## What's New
- One-command install via install.py
- Project templates: ds_project, rag_pipeline, web_api, cli_tool
- AGY and Codex plugin packaging
- External-audience README and documentation
- GitHub issue and PR templates

## Improvements
[List key fixes from Phase 6]

## Known Limitations
[Honest list from production readiness report]

## Upgrade from v0.4.0
[Migration steps if any]

### 7. Commit and tag
```bash
git add .
git commit -m "feat: Phase 7 complete — developer experience, v0.5.0"
git tag v0.5.0
git push origin main --tags
```

### 8. Write TASK_49_RESULT.md
- Clean install test: PASSED or FAILED with details
- Final test count
- All 4 smoke tests
- Install time in seconds
- CLI startup time
- What Phase 8 (launch) requires

## Constraints
- clean_install_test.sh must complete in < 5 minutes
- If clean install fails: fix the root cause, don't skip
- Version bump must be reflected in test_open_source_hygiene.py

## Verification
clean_install_test.sh exits 0.
Full test suite passes.
All 4 smoke tests pass.
Write TASK_49_RESULT.md. Update tasks/README.md.
