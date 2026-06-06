---
name: audit-result
description: "Audit the most recently completed task result. Use when user says audit, check last result, what did you build, or verify."
---

# Audit Last Result

1. Find the most recent TASK_XX_RESULT.md
2. Read it completely
3. Read all files it claims to have created
4. Run the test suite and compare count against claimed count
5. Check imports for all new modules
6. Flag any deviation between claimed and actual
7. Output: PASSED or FAILED with specific issues listed
