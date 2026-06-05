# Agent Specifications

## Required Agent Roster

All five agents listed here are required. Phased delivery is acceptable.

| Agent | Trigger | Output |
|---|---|---|
| Planning Agent | New idea / sprint start | Backlog, tasks, constraints |
| Code Review Agent | Any code change | Review report, issues flagged |
| Architecture Agent | New feature / design decision | ADR, risk flags |
| Test Agent | Any code change | Tests written and run automatically |
| Documentation Agent | Any code change | Docs updated automatically |

## Planning Agent

The Planning Agent is triggered by a new idea or sprint start.

Its required outputs are:

- Backlog
- Tasks
- Constraints

## Code Review Agent

The Code Review Agent is triggered by any code change.

Its required outputs are:

- Review report
- Issues flagged

## Architecture Agent

The Architecture Agent is triggered by a new feature or design decision.

Its required outputs are:

- ADR
- Risk flags

## Test Agent

The Test Agent is triggered by any code change.

Its required outputs are:

- Tests written automatically
- Tests run automatically

## Documentation Agent

The Documentation Agent is triggered by any code change.

Its required output is:

- Documentation updated automatically

## Cross-Agent Requirement

A code change must auto-trigger:

- Tests
- Docs
- Backlog update

## Delivery Requirement

All five agents are required, but phased delivery is acceptable.

