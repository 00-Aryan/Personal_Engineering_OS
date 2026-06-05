# Project Context

## Project

ProjectOS is Aryan Kumar's Personal Engineering OS, defined in June 2026.

## Vision

ProjectOS is an autonomous multi-agent system for handling the full
software development life cycle for Aryan's projects without requiring
Aryan to context-switch between engineering roles.

## Current User

The only current user is Aryan Kumar.

## Core Need

Aryan needs a proactive system that runs continuously without him because
current AI tools are reactive and only act once when asked.

## Launch Scope

ProjectOS launches for Aryan's personal projects on a single machine.

The launch project types are Python projects, including data science,
RAG, LLM pipelines, and some frontend work.

## Required Agents

ProjectOS requires:

- Clone meta-agent
- Planning Agent
- Code Review Agent
- Architecture Agent
- Test Agent
- Documentation Agent

The five delivery agents are Planning, Code Review, Architecture, Test,
and Documentation. The Clone is specified separately as the supervisor
meta-agent.

## Clone Summary

The Clone observes all other agents continuously, makes autonomous
decisions for small and routine matters, escalates important decisions to
Aryan, starts another task when one task is blocked, and plans
reconnection between blocked and parallel tasks.

## Model Architecture

Swapping a model for any single agent must require changing one config
value only.

All model calls must go through a single ModelProvider interface.

No agent may hardcode a model or API format.

Launch providers are OpenRouter free tier and Ollama local fallback.

## Interaction Model

The primary interface is CLI.

ProjectOS must also run as a background daemon while Aryan studies.

Key commands are:

- `/model`
- `/status`
- `/approve`
- `/backlog`
- `/review`

## Version 1 Exclusions

Version 1 excludes:

- Multi-user support
- Web dashboard
- Self-modifying agents
- Enterprise features
- Non-Python projects at launch

