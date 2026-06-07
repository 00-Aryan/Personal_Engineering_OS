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
