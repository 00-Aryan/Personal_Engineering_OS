# ProjectOS FAQ

This document answers the most common questions about using and configuring ProjectOS.

### 1. Does it work without an API key?
Yes. ProjectOS features a built-in offline fallback mode (`TFIDFEmbedder` for codebase retrieval/indexing and semantic routing) that operates locally without needing any API keys. However, advanced orchestration features, quality judging, and agent generation capabilities require model provider keys configured in your `.env` file.

### 2. How much does it cost to run?
When using the recommended cloud-based model providers, costs depend on the activity in your repository. For routine development, the daily cost is minimal (often less than a few cents), and the system offers built-in token budget management and daily spending caps to prevent runaway expenses.

### 3. Can it modify my files without asking?
No. ProjectOS operates on a review-first safety protocol. Proposed code writes, architectural ADR modifications, and backlog changes are buffered, and important updates can be configured to prompt for human approval before they are merged or committed.

### 4. What languages does it support?
The orchestrator and agent templates are designed primarily for Python-first environments. However, the vector store, documentation tools, and change monitoring systems can index and analyze projects written in any standard programming language.

### 5. How is this different from GitHub Copilot?
GitHub Copilot is an inline code completion tool. ProjectOS is a repository-level coordinator that manages multiple distinct agent personas (Review, Testing, Architecture, Documentation, Planning) to run background reviews, verify quality gates, and keep documentation synchronized.

### 6. Can I use it with an existing project?
Yes. ProjectOS is designed to be highly compatible with existing codebases. Simply initialize it in your project's root folder, register your directory configuration, and it will begin monitoring and reviewing your files.

### 7. Does it work offline?
Yes, ProjectOS can run fully offline. In offline mode, it relies on local TF-IDF embeddings for context retrieval and semantic classification, and can be integrated with local inference providers (such as Ollama) to coordinate model actions locally.

### 8. Is my code sent to the cloud?
Only if you configure cloud-based model providers (like Gemini or OpenRouter). If you choose to configure a local provider like Ollama, all data stays on your local machine and no code or context is transmitted externally.
