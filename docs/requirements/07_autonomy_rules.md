# Autonomy Rules

## Routine Fixes

Routine fixes are fully autonomous and must not interrupt Aryan.

## Important Decisions

Important decisions are handled by the Clone deciding or pinging Aryan.

The source also identifies architecture, breaking changes, and new
dependencies as important decision areas for escalation to Aryan.

## Blocked Tasks

A blocked task must never stop other tasks.

The Clone must queue reconnection between blocked tasks and parallel tasks.

If Task A needs permission, the Clone starts Task B immediately.

## Code Change Automation

A code change must auto-trigger:

- Tests
- Docs
- Backlog update

## Continuous Enforcement

ProjectOS must continuously enforce:

- Deliverables
- Constraints
- Standards

