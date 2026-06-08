# Good First Issue: Add support for a new project template

## Description
ProjectOS supports 4 project templates (ds_project, rag_pipeline, web_api, cli_tool). We want to add more.

## Task
Create a new template for flask_api:
1. Create templates/flask_api/template.yaml
2. Create templates/flask_api/AGENTS.md
3. Create templates/flask_api/.gitignore
4. Add routing examples for this project type
5. Add a test in tests/test_template_manager.py

## Resources
- Existing templates: templates/
- Template format: templates/README.md
- Tests to follow: tests/test_template_manager.py

## Acceptance Criteria
- Template yaml is valid
- Tests pass
- PR includes template and tests
