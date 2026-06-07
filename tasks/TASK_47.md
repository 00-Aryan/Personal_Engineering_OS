# TASK_47: AGY + Codex Plugin Packaging

## Engineering Context

ProjectOS runs as a standalone tool. But developers spend most of
their time inside Codex or AGY sessions. If ProjectOS can be called
from within those tools as an MCP server, developers never need to
switch contexts.

TASK_18 already built the MCP server. This task packages it properly
as an installable plugin for both AGY and Codex, and creates the
.agents/ skill structure that makes ProjectOS a first-class citizen
in both environments.

## Pre-conditions
Read mcp_server/server.py from TASK_18 completely.
Read .agents/skills/ and .codex/skills/ for existing skill format.
Read AGENTS.md.

## Deliverables

### 1. .agents/skills/projectos-plan/SKILL.md

```markdown
---
name: projectos-plan
description: "Submit a feature idea to ProjectOS Planning Agent. Use when user says plan this feature, create tasks for, or break down this idea."
---

# ProjectOS Plan

Submit a feature description to ProjectOS Planning Agent.

1. Check if ProjectOS MCP server is connected via /mcp
2. If connected: call projectos_plan tool with the description
3. If not connected: run locally:
   uv run --no-sync projectos /plan "[description]"
4. Display the generated task breakdown
5. Ask: "Should I add these to backlog.md?"
```

### 2. .agents/skills/projectos-review/SKILL.md

```markdown
---
name: projectos-review
description: "Trigger ProjectOS code review on a file. Use when user says review this file, check this code, or analyze this."
---

# ProjectOS Review

Run ProjectOS code review on the specified file.

1. Identify the file path from context or ask user
2. Check if ProjectOS MCP server is connected
3. If connected: call projectos_review with file_path
4. If not connected:
   uv run --no-sync projectos review [file_path]
5. Display review results from reviews/ directory
6. Ask: "Should I fix the critical issues now?"
```

### 3. .agents/skills/projectos-status/SKILL.md

```markdown
---
name: projectos-status
description: "Check ProjectOS system status. Use when user asks about agent status, what is running, or system health."
---

# ProjectOS Status

Show current ProjectOS system status.

1. If MCP connected: call projectos_status tool
2. If not: uv run --no-sync projectos status
3. Display: agents, providers, queue, last activity
```

### 2. Package manifest for AGY plugin

.agents/plugin.yaml:
```yaml
name: projectos
version: "0.4.0"
description: "Personal Engineering OS — autonomous multi-agent system"
author: "Aryan Kumar"

skills:
  - .agents/skills/projectos-plan
  - .agents/skills/projectos-review
  - .agents/skills/projectos-status

mcp_servers:
  - name: projectos
    command: ["uv", "run", "--no-sync", "python", "-m", "mcp_server.server"]
    description: "ProjectOS MCP server exposing all agents as tools"

workflows:
  - .agents/workflows/run-task.md
  - .agents/workflows/audit.md
  - .agents/workflows/add-tasks.md
  - .agents/workflows/fix-and-continue.md
```

### 3. Codex plugin config

.codex/plugin.json:
```json
{
  "name": "projectos",
  "version": "0.4.0",
  "description": "ProjectOS — autonomous multi-agent engineering OS",
  "skills": [
    ".codex/skills/run-next-task",
    ".codex/skills/audit-result",
    ".codex/skills/fix-and-continue"
  ],
  "mcp": {
    "projectos": {
      "command": ["uv", "run", "--no-sync", "python", "-m", "mcp_server.server"]
    }
  }
}
```

### 4. scripts/package_plugin.py

Packages ProjectOS as a distributable plugin archive.

Steps:
1. Read .agents/plugin.yaml for metadata
2. Create dist/ directory
3. Bundle:
   - .agents/skills/
   - .agents/workflows/
   - mcp_server/
   - config/projectos.yaml.example
   - install.py
   - README.md
4. Write dist/projectos-plugin-v{version}.tar.gz
5. Write dist/projectos-plugin-v{version}-manifest.json:
   {name, version, files, install_command, mcp_tools}
6. Print: "Plugin packaged: dist/projectos-plugin-{version}.tar.gz"
7. Print install instructions for AGY and Codex.

### 5. Update README.md
Add section: "Use as AGY/Codex Plugin"

  ## Use as AGY/Codex Plugin
  
  ProjectOS integrates natively with AGY and Codex CLI.
  
  **AGY:**
```bash
  agy plugin install dist/projectos-plugin-v0.4.0.tar.gz
```
  Then in any AGY session: use $projectos-plan, $projectos-review
  
  **Codex:**
```bash
  codex plugin install dist/projectos-plugin-v0.4.0.tar.gz
```
  
  **MCP Server (any client):**
```bash
  uv run --no-sync python -m mcp_server.server
```

### 6. tests/test_plugin_packaging.py
- test_plugin_yaml_valid_schema
- test_codex_plugin_json_valid_schema
- test_all_skills_referenced_exist
- test_all_workflows_referenced_exist
- test_package_script_creates_dist_dir
- test_manifest_json_has_required_fields

## Constraints
- Plugin packaging must work without network access
- dist/ directory added to .gitignore
- Plugin must not bundle .env or API keys
- tar.gz must be < 5MB (skills are markdown, lightweight)

## Verification
python scripts/package_plugin.py (must complete without error)
Full test suite passes.
Write TASK_47_RESULT.md. Update tasks/README.md.
