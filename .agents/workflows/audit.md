---
name: audit
description: Generate an audit report for the most recently completed task
---

1. Find the most recent TASK_XX_RESULT.md file
2. Read it completely
3. Verify every file it claims to have created actually exists
4. Run test suite and compare count against claimed count
5. Run all smoke tests that exist in scripts/
6. Check all new imports resolve correctly
7. Output structured report:
   TASK: [task name]
   FILES: [claimed vs actual]
   TESTS: [claimed count vs actual count]
   SMOKE: [PASSED/FAILED per script]
   GAPS: [anything missing or broken]
   STATUS: AUDIT PASSED or AUDIT FAILED