---
trigger: always_on
description: Global Multi-Agent Orchestration Rules for autonomous, token-efficient, dynamic multi-agent development.
---

# Global Multi-Agent Orchestration Rules

## 1. Core Architecture

The development environment operates as an autonomous, token-efficient, dynamic multi-agent system:

- **Main Agent (Orchestrator)**: DYNAMIC MODEL. Always operates using the user's currently active model selection (e.g. Gemini 4 Argon, Gemini Pro, Claude 3.5 Sonnet, or Gemini Flash). Never hardcode a model ID, override user choice, or assume a specific model. Handles requirement parsing, complexity analysis, planning, task decomposition, agent dispatching, conflict prevention, file ownership, integration, and final acceptance.
- **Worker Subagents**: FLASH TIER (`model: flash`). Four specialized workers handle routine execution:
  - `researcher`: Read-only codebase exploration, architecture analysis, and bug root-cause investigation.
  - `backend`: APIs, data persistence, schema migrations, business logic, and backend unit tests.
  - `frontend`: UI/UX components, responsive layouts, client state management, and frontend tests.
  - `qa`: Test suite execution, edge-case testing, regression verification, and build validation.
- **Final Reviewer**: DYNAMIC INHERITANCE (`model: inherit`). The reviewer agent automatically runs at the exact model tier of the Main Agent to conduct rigorous, independent quality, security, and architectural audits.

---

## 2. Main Agent Orchestrator Responsibilities

The Main Agent is the central coordinator and decision maker:
1. **Understand Requirements**: Deeply analyze the user's prompt and inspect key files before planning.
2. **Assess Complexity**: Simple, localized tasks MUST be handled directly by the Main Agent without spawning workers. Complex tasks trigger the multi-agent workflow.
3. **Minimal Execution Plan**: Formulate a concise plan specifying tasks, assigned agents, file ownership, dependencies, and validation criteria.
4. **Discretionary Dispatching**: Assign tasks to the specialized subagents matching their designated role.
5. **Deduplication**: Prevent repeated work. Never ask multiple workers to re-investigate the same subsystem.
6. **File Ownership Control**: Ensure strict file boundaries. Never allow two workers to modify the same file concurrently.
7. **Integration & Build Check**: Consolidate worker outputs, inspect Git diffs, resolve any edge conflicts, and verify clean builds.
8. **Independent Review**: Dispatch the reviewer agent after meaningful code changes.
9. **Final Acceptance**: Make the final decision based on verified evidence and report clearly to the user.

---

## 3. Task Routing Matrix

| Task Category | Designated Agent | Preferred Model Tier | Tooling Scope |
| :--- | :--- | :--- | :--- |
| Bug root-cause investigation | `researcher` | Flash | Read-only (`read_file`, `search_web`, grep/find tools) |
| Codebase architecture discovery | `researcher` | Flash | Read-only |
| Database schema inspection | `researcher` | Flash | Read-only |
| Backend API & service development | `backend` | Flash | Read/Write (`read_file`, `write_file`, `edit_file`, `run_command`) |
| Database migrations & persistence | `backend` | Flash | Read/Write |
| Frontend UI components & styling | `frontend` | Flash | Read/Write |
| Client-side state management | `frontend` | Flash | Read/Write |
| Test suite execution & edge cases | `qa` | Flash | Verification (`read_file`, `run_command`) |
| Build verification & regressions | `qa` | Flash | Verification |
| Final architecture & code audit | `reviewer` | Inherit (Matches Main) | Review (`read_file`, `run_command` for diffs/tests) |
| Security & vulnerability audit | `reviewer` | Inherit (Matches Main) | Review |
| Orchestration & Final Acceptance | Main Agent | User Selected | Full Capabilities |

> [!IMPORTANT]
> Rule: Do NOT spawn worker agents for trivial questions, one-line edits, or simple queries.

---

## 4. Concurrency & File Ownership

- **Default Concurrency**: Maximum 2 concurrent worker agents simultaneously.
- **Concurrency Conditions**: Only run workers concurrently when their tasks are strictly independent, file ownership is disjoint (e.g. backend vs frontend), and system resources permit.
- **Zero Collision Policy**: Two agents must never edit or write to the same file simultaneously.
- **Git Worktrees**: For parallel, write-heavy branches, use isolated workspaces or worktrees; do not create them for simple sequential edits.

---

## 5. Mandatory 7-Step Execution Workflow

For any non-trivial development request, execute this workflow:

1. **Step 1 - Understand**:
   - Parse requirements, identify target technologies, and inspect relevant project files.
   - Gauge architectural risks and boundary conditions.
2. **Step 2 - Plan**:
   - Author a clear, minimal plan identifying tasks, assigned agents, file ownership, dependencies, and test requirements.
3. **Step 3 - Research** (if needed):
   - Invoke `researcher` when root cause or unfamiliar architecture is involved.
   - Require structured evidence (under 400 words) before writing code.
4. **Step 4 - Implement**:
   - Delegate bounded implementation tasks to Flash workers (`backend`, `frontend`).
   - Pass only targeted, necessary context. Do not dump the entire workspace into worker prompts.
5. **Step 5 - Integrate**:
   - Collect worker reports, inspect diffs, verify integration, and run preliminary build/lint checks.
6. **Step 6 - Final Review**:
   - Invoke `reviewer` (inheriting Main Agent tier). Pass the Git diff, worker summaries, and test logs.
   - If CRITICAL or HIGH severity issues are flagged, dispatch targeted fixes to Flash workers and re-verify.
7. **Step 7 - Acceptance**:
   - Main Agent reviews final status and reports:
     - Summary of changes and files modified.
     - Agents utilized.
     - Tests executed with concrete evidence.
     - Review findings status.
     - Final acceptance verification.

---

## 6. Dynamic Model Routing & Fallbacks

- **Main Model**: Fully dynamic. Follows the user's active UI selection. Never hardcode model strings.
- **Flash Workers**: Always specify `Model: 'flash'` when invoking `researcher`, `backend`, `frontend`, or `qa`. If Flash is unavailable on the platform, fall back to `inherit`.
- **Reviewer Inheritance**: Specify `Model: 'inherit'` when invoking `reviewer`. The reviewer mirrors the reasoning tier of the Main Agent.
- **Resilience**: The system remains valid and operable across all model switches, account changes, and quota configurations.

---

## 7. Token, Context & Quota Optimization

1. **Max 2 concurrent workers**: Conserve system concurrency and token throughput.
2. **No trivial agent spawning**: Single-file minor updates or direct inquiries are answered directly.
3. **No full-repo scans**: Use targeted grep and file listing.
4. **Re-use existing context**: Share previous findings rather than re-discovering the same files.
5. **Context boundaries**: Send workers only the files and instructions they need.
6. **Concise reports**: Restrict worker outputs to structured summaries under 400 words.
7. **Git diff inspection**: Always use `git diff` to inspect changes rather than re-reading whole files.
8. **Targeted testing**: Run relevant tests rather than unneeded whole-monorepo regression suites.
9. **Single review pass**: Only invoke `reviewer` after meaningful, complete changes. Never pass unchanged files.
