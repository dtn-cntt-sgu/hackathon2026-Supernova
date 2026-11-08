---
name: speckit
description: >
  Specification-Driven Development (SDD) toolkit inspired by github/spec-kit.
  Use when designing, specifying, planning, or executing structured features
  from PRDs to implementation tasks. Commands: /speckit.specify, /speckit.clarify,
  /speckit.plan, /speckit.tasks, /speckit.implement.
argument-hint: "[specify|clarify|plan|tasks|implement]"
license: MIT
metadata:
  author: spec-kit
  version: "1.0.0"
---

# Spec-Kit (Specification-Driven Development)

Spec-Driven Development (SDD) inverts the traditional relationship between code and specifications: **Code serves specifications**. Specifications don't just guide implementation; they generate implementation and define truth.

## The SDD Lifecycle

```
Feature Intent ──> [/speckit.specify] ──> Structured PRD (.specify/specs/)
                         │
                         ▼
                   [/speckit.clarify] ──> Edge Cases & Questions Resolved
                         │
                         ▼
                   [/speckit.plan]    ──> Architectural & Tech Decisions (.specify/plans/)
                         │
                         ▼
                   [/speckit.tasks]   ──> Dependency-Ordered Execution Checklist (.specify/tasks/)
                         │
                         ▼
                   [/speckit.implement] ──> Verified Code & Regression Tests
```

---

## Commands & Workflows

### 1. `/speckit.specify`
Converts a user feature prompt into a complete, structured Specification / PRD stored in `.specify/specs/<feature-name>.md`.
- **User Scenarios & Core Value:** Who needs this and why.
- **Functional Requirements:** Inviolable business logic and system behavior.
- **Non-Functional Requirements:** Latency, throughput, security, accessibility.
- **Contract & Interfaces:** Input/output data schemas, API contracts, endpoints.
- **Acceptance Criteria:** Precise, testable conditions for acceptance.

### 2. `/speckit.clarify`
Validates the specification against ambiguities, hidden assumptions, and missing edge cases.
- Checks data boundaries, error states, and security implications.
- Prompts the user with clarifying multiple-choice or direct questions before technical planning.

### 3. `/speckit.plan`
Architects the technical solution before writing any implementation code. Stored in `.specify/plans/<feature-name>-plan.md`.
- **System Architecture & Data Flow:** Component relationships, sequence diagrams, callers/callees.
- **Technology & Library Rationale:** Document why specific tools/libraries were selected.
- **Database & State Migrations:** Schema changes, indexes, caching layers.
- **Blast Radius & Rollback Strategy:** What could break and how to revert safely.

### 4. `/speckit.tasks`
Breaks the architectural plan down into a fine-grained, dependency-ordered task checklist stored in `.specify/tasks/<feature-name>-tasks.md`.
- Sequential execution order with explicit dependencies (`[T1] -> [T2] -> [T3]`).
- Strict file ownership boundaries per task.
- Verification command for each task (unit test, build check, lint).

### 5. `/speckit.implement`
Executes tasks systematically one by one against the task checklist:
- Runs test-driven implementation (write or update test first, then implement).
- Verifies clean integration and zero regression after each step.
- Marks completed tasks in the task checklist.

---

## Core Principles

1. **Specifications as Source of Truth:** If code and spec diverge, either fix the spec first or reject the code change.
2. **Zero Assumptions:** Ambiguities are clarified during `/speckit.clarify`, never guessed during coding.
3. **Executable Acceptance:** Every requirement must have a corresponding verification step or automated test.
