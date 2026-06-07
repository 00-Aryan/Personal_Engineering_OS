# TASK_52: Launch Announcement Preparation

## Engineering Context

Open source projects succeed or fail at launch based on one thing:
does the first impression make someone want to try it?

This task prepares all launch assets. Not writing blog posts for
their own sake — preparing the exact content needed to get the
first 10 real users.

Target platforms:
1. HackerNews Show HN (most technical, highest quality bar)
2. r/MachineLearning (ML-focused, appreciates rigor)
3. LinkedIn (professional network, Aryan's existing connections)

Each platform needs different content and framing.

## Pre-conditions
Read README.md, docs/FAQ.md, docs/RELEASE_NOTES_v0.5.0.md.
Read docs/phase4_quality_delta.md and docs/PRODUCTION_READINESS.md
for specific numbers to cite.

## Deliverables

### 1. docs/launch/hackernews_post.md

```markdown
# HackerNews Show HN Draft

Title: Show HN: ProjectOS – autonomous multi-agent system that
       engineers your code while you study (Python, open source)

Body:
I'm a final-year data science student at IIT Madras. I built this 
because I was trying to simultaneously handle coursework, ML projects,
and startup ideas — and kept context-switching between them.

ProjectOS is an autonomous system that runs your software projects
in the background. You give it a feature idea, it plans, writes,
reviews, tests, and documents — while you focus on studying.

Technical details:
- 7 specialized agents (planning, code writing, review, test, docs,
  architecture, clone supervisor)
- LLM-as-judge quality gates block low-quality outputs
- Codebase RAG: agents read your repo before acting
- Works with Gemini free tier (₹0/month to run)
- 381 tests, 100% production readiness score

What makes it different from Cursor/Copilot:
- Proactive (runs continuously, not on request)
- Multi-agent (specialized roles, not one model doing everything)
- Quality-gated (blocks bad output before it reaches files)
- Self-monitoring (traces every decision, alerts on degradation)

GitHub: [link]
Demo: [link to demo script]

Happy to answer questions about the architecture.
```

Rules for this draft:
- Honest about limitations (runs on mocked providers primarily)
- No hype words ("revolutionary", "game-changing")
- Specific numbers (381 tests, 7 agents, etc.)
- Personal story is genuine

### 2. docs/launch/reddit_post.md

```markdown
# r/MachineLearning Post Draft

Title: [Project] I built an autonomous multi-agent engineering OS
       that manages software projects using specialized LLM agents

Body:
[Technical focused version — emphasize:
- LLM-as-judge evaluation methodology
- Semantic routing with embeddings vs keyword matching
- Regression detection with rolling baselines
- The quality gate architecture
- Honest about mocked vs real provider testing]
```

### 3. docs/launch/linkedin_post.md

```markdown
# LinkedIn Post Draft

[Professional tone — emphasize:
- Built during final year at IIT Madras
- Problem it solves for students and developers
- Technical stack (Python, Gemini, multi-agent)
- Open source, free to use
- Link to GitHub]

Max 200 words. No jargon. Genuine story.
```

### 4. docs/launch/LAUNCH_CHECKLIST.md

```markdown
# Launch Checklist

## Before Posting (do these first)
- [ ] Real API smoke test passes (TASK_50)
- [ ] Clean install test passes (TASK_49)
- [ ] GitHub repo description updated
- [ ] README badge shows green CI
- [ ] At least 1 real user tested it (friend, classmate)

## Day of Launch
- [ ] Post HackerNews Show HN (best time: 9am EST Tuesday-Thursday)
- [ ] Post r/MachineLearning
- [ ] Post LinkedIn
- [ ] Monitor GitHub issues for first bug reports
- [ ] Respond to every comment within 2 hours

## Week After Launch
- [ ] Fix top 3 issues reported
- [ ] Update FAQ with questions people asked
- [ ] Add real usage examples to README
- [ ] Thank early contributors

## Success Metrics (first 2 weeks)
- GitHub stars: target 50+
- Issues opened: any (means people tried it)
- PRs opened: any (means people want to contribute)
```

### 5. docs/launch/FIRST_ISSUE.md

GitHub "good first issue" template — a real task that
a contributor could do without deep system knowledge:

```markdown
# Good First Issue: Add support for a new project template

## Description
ProjectOS supports 4 project templates (ds_project, rag_pipeline,
web_api, cli_tool). We want to add more.

## Task
Create a new template for [flask_api / pytorch_project / 
fastapi_microservice — pick one]:
1. Create templates/[name]/template.yaml
2. Create templates/[name]/AGENTS.md
3. Create templates/[name]/.gitignore
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
```

### 6. tests/test_launch_assets.py
- test_hackernews_post_exists
- test_reddit_post_exists
- test_linkedin_post_exists
- test_launch_checklist_exists
- test_first_issue_template_exists
- test_hackernews_post_under_500_words
- test_linkedin_post_under_200_words

## Constraints
- All posts must be honest — no invented metrics
- LinkedIn post must be under 200 words
- HackerNews post must mention it runs on free tier
- No launch until TASK_50 real API smoke passes

## Verification
Full test suite passes.
Write TASK_52_RESULT.md. Update tasks/README.md.
