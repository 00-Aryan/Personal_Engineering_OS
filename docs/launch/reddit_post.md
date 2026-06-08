# r/MachineLearning Post Draft

Title: [Project] I built an autonomous multi-agent engineering OS that manages software projects using specialized LLM agents

Body:
Hi ML community,

I'm a final-year B.S. Data Science student at IIT Madras, and I've spent the last few weeks building ProjectOS: an open-source, background coordinator that orchestrates a roster of specialized agents (Planning, Writing, Testing, Reviewing, Documenting, and Architecture) to maintain repository health while you focus on other work.

Rather than just wrapping a single prompt, I wanted to address a core challenge with agentic systems: output reliability and quality control. Here is a technical breakdown of the architecture:

1. **LLM-as-a-Judge Evaluation & Quality Gates**: Every proposed modification (code, documentation, architecture records) is graded by a LLM-as-a-judge module before it touches files. If the quality score falls below the configurable gate threshold, the write is rejected and sent back to the agent for refinement.
2. **Semantic Routing & Codebase RAG**: We use semantic embeddings (local TF-IDF or Gemini) to classify incoming events and route them to the appropriate agent. Codebase context is dynamically retrieved from a local vector store before agent invocations.
3. **Regression Detection**: The system maintains rolling quality score baselines and fires alerts if quality scores drop compared to past baselines.
4. **Mocked vs. Real Provider Testing**: To keep cost zero during development, ProjectOS utilizes mock providers extensively across our 392 tests. To ensure reliability before launch, we implemented a real-api smoke verification script that performs live API calls to verify connectivity, completion matching, token budget enforcement, circuit breakers, and rate-limiting limits.

The project is fully open-source and runs locally in your terminal. I would love to get feedback on the agent collaboration and verification layer.

GitHub: https://github.com/00-Aryan/Personal_Engineering_OS
