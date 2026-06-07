# TASK_48: Developer Experience Documentation

## Engineering Context
To prepare ProjectOS for an open-source release, the documentation needs to be rewritten to focus on external developers. The README and other documents should describe ProjectOS as a finished developer tool, hiding internal build steps and development terminology.

## Deliverables

### 1. Rewrite README.md
Apply the following rules for the rewrite:
- No mention of "task queue", "TASK_XX files", "AGY", Claude
- No internal implementation details
- No mention of the build process (phases, tasks, etc.)
- Write as if this is a finished product someone else built
- Maximum 600 words in the main body
- Every section must add value — cut anything decorative

### 2. docs/DEMO_SCRIPT.md
A reproducible demo anyone can run.

### 3. docs/FAQ.md
Answer the 8 most likely questions from a new user.

### 4. .github/ISSUE_TEMPLATE/bug_report.md
Standard GitHub issue template for bug reports.

### 5. .github/ISSUE_TEMPLATE/feature_request.md
Standard GitHub issue template for feature requests.

### 6. .github/PULL_REQUEST_TEMPLATE.md
Standard PR template.

### 7. tests/test_documentation.py
- test_readme_under_800_lines
- test_readme_has_quick_start_section
- test_readme_has_agent_roster_section
- test_faq_has_eight_questions
- test_demo_script_exists
- test_issue_templates_exist
- test_pr_template_exists

## Verification
- Full test suite passes.
- Write TASK_48_RESULT.md. Update tasks/README.md.
