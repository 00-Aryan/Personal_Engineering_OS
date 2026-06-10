# Ollama Local Fallback Setup Guide

This guide details how to install and configure Ollama to serve as a local fallback for ProjectOS when cloud APIs (like Gemini or OpenRouter) are unavailable or token limits are exceeded.

## 1. Installation on Ubuntu/Linux

To install Ollama on Ubuntu or any modern Linux distribution, run the official installation script:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Starting the Service
Once installed, the installer automatically configures Ollama as a systemd service. You can control it using:

```bash
# Check if service is running
systemctl status ollama

# Start the service
sudo systemctl start ollama

# Stop the service
sudo systemctl stop ollama
```

If you prefer to run it manually in a terminal without systemd:
```bash
ollama serve
```

---

## 2. Hardware Expectations (Running on a Laptop)

Running LLMs locally requires computing resources (CPU, RAM, and GPU):

- **With GPU (NVIDIA/AMD/Apple Silicon)**: Ollama will automatically offload model layers to the GPU. You can expect high token-generation speeds (20-60+ tokens/second).
- **Without GPU (CPU Only)**: Ollama runs in CPU-only mode.
  - **1.3B/1.5B parameter models** (e.g., Llama 3.2:1b, DeepSeek-R1:1.5b) run smoothly on modern laptop CPUs with minimal latency (10-25 tokens/second).
  - **3B/8B parameter models** will run slower (3-8 tokens/second) and consume significant battery and CPU power, making the fan spin.
  - Make sure you have at least 8 GB of RAM for small models, and 16 GB+ for 8B models.

---

## 3. Recommended Local Models

ProjectOS is pre-configured in `config/projectos.yaml` to prefer the following models:

| Model | Size | Hardware Target | Purpose / Best For |
| :--- | :--- | :--- | :--- |
| **`llama3.2:1b`** | ~1.3 GB | Light laptops / CPU-only | Quick tasks, code writing, docs |
| **`llama3.2:3b`** | ~2.0 GB | Standard laptops / GPU | Balanced tasks, planning, review |
| **`deepseek-r1:1.5b`** | ~1.3 GB | CPU / standard laptop | Focused reasoning, planning |
| **`llama3:8b`** / **`qwen2.5-coder:7b`** | ~4.7 GB | Dedicated GPU / 16GB RAM | Coding tasks, complex planning |

---

## 4. How to Make ProjectOS Use Ollama Only

By default, ProjectOS assigns agents to Gemini or OpenRouter and uses local Ollama as a fallback. If you want to operate completely offline or force ProjectOS to use local Ollama for all agents, you can configure this via the `/model` CLI command or by editing configuration files.

### Option A: Using CLI Configuration

To set all agents to use local Ollama:
```bash
projectos config set agents.clone ollama-local
projectos config set agents.planning ollama-local
projectos config set agents.code_writing ollama-local
projectos config set agents.code_review ollama-local
projectos config set agents.architecture ollama-local
projectos config set agents.test ollama-local
projectos config set agents.docs ollama-local
```

### Option B: Manually Editing `config/projectos.yaml`

Change the `agents` block in your `config/projectos.yaml` to map each agent to `ollama-local`:

```yaml
agents:
  clone:        ollama-local
  planning:     ollama-local
  code_writing: ollama-local
  code_review:  ollama-local
  architecture: ollama-local
  test:         ollama-local
  docs:         ollama-local
```
