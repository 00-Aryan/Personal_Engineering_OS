# HackerNews Show HN Draft

Title: Show HN: ProjectOS – autonomous multi-agent system that engineers your code while you study (Python, open source)

Body:
I'm a final-year data science student at IIT Madras. I built this because I was trying to simultaneously handle coursework, ML projects, and startup ideas — and kept context-switching between them.

ProjectOS is an autonomous system that runs your software projects in the background. You give it a feature idea, it plans, writes, reviews, tests, and documents — while you focus on studying.

Technical details:
- 7 specialized agents (planning, code writing, review, test, docs, architecture, clone supervisor)
- LLM-as-judge quality gates block low-quality outputs
- Codebase RAG: agents read your repo before acting
- Works with Gemini free tier (₹0/month to run)
- 392 tests, 100% production readiness score

What makes it different from Cursor/Copilot:
- Proactive (runs continuously, not on request)
- Multi-agent (specialized roles, not one model doing everything)
- Quality-gated (blocks bad output before it reaches files)
- Self-monitoring (traces every decision, alerts on degradation)

GitHub: https://github.com/00-Aryan/Personal_Engineering_OS
Demo: Run python install.py to start

Happy to answer questions about the architecture.
