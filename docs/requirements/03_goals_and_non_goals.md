# Goals And Non-Goals

## Goals

ProjectOS must provide a proactive autonomous multi-agent system that
handles the full software development life cycle for Aryan's projects.

The system must reduce context-switching across engineering roles.

The system must run continuously without Aryan.

The system must support autonomous supervision through the Clone
meta-agent.

The system must support all five required agents:

- Planning Agent
- Code Review Agent
- Architecture Agent
- Test Agent
- Documentation Agent

Phased delivery is acceptable.

## In Scope

The launch scope includes:

- Python projects
- Data science projects
- RAG projects
- LLM pipelines
- Some frontend work
- Aryan's personal projects only
- Single-machine deployment

## Explicitly Out Of Scope For Version 1

The following are not in scope for version 1:

- Multi-user support
- Web dashboard
- Self-modifying agents
- Enterprise features
- Non-Python projects at launch

## Budget Goals And Constraints

The first 3 to 4 months must use free models only.

The budget for the first 3 to 4 months is INR 0.

The architecture must allow paid APIs to be added as drop-in replacements
with zero refactoring.

Ollama must be available as an offline fallback.

## 30-Day Goal

The minimum 30-day success definition is:

- Clone working end-to-end
- Planning Agent working end-to-end
- Code Review Agent working end-to-end

The stretch 30-day success definition is:

- All five agents scaffolded
- Three agents fully functional

The 30-day must-haves are:

- `/model` switch working
- Daemon running in the background

