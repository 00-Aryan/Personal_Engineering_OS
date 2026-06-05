---
name: fix-and-continue
description: "Apply fixes flagged by audit and resume. Use when user says fix this, apply fixes, fix and continue, or pastes an error."
---

# Fix and Continue

1. Read the issue description provided
2. Read the affected files completely before touching anything
3. Apply minimal fix — do not refactor unrelated code
4. Run full test suite
5. Confirm all previously passing tests still pass
6. Report: what was fixed, test count before and after
