# Submission Deliverables: Prewise Request Approval Flow

**Candidate Assignment:** Agentic AI Workflow Automation for the Request Approval Flow  
**Core Architectural Principle:** *"The AI suggests; a deterministic backend decides."*  
**Date:** October 18, 2026  

---

## 🔗 External Links

- **GitHub Repository URL:** `<add link>` (e.g., `https://github.com/your-username/prewise-approval-flow`)
- **Walkthrough Demo Video:** `<add link>` (e.g., Loom / YouTube unlisted link)

---

## 📦 Required Deliverables Index

| Deliverable | File Path | Description |
| :--- | :--- | :--- |
| **Quick Start & README** | [`README.md`](README.md) | Project overview, quick start, live benchmark summary, documented assumptions, and architecture principles. |
| **Architecture Specification** | [`docs/architecture.md`](docs/architecture.md) | End-to-end topology flowchart, request state transition diagram, security boundaries, and invariant enforcement. |
| **Architecture Flowchart (SVG)** | [`docs/architecture_flowchart.svg`](docs/architecture_flowchart.svg) | Standalone vector graphic export of the complete multi-agent orchestrator architecture. |
| **State Machine Diagram (SVG)** | [`docs/state_lifecycle.svg`](docs/state_lifecycle.svg) | Standalone vector graphic export of the deterministic finite state lifecycle. |
| **Mini PRD (Product Requirements)** | [`docs/MINI_PRD.md`](docs/MINI_PRD.md) | Problem statement, user personas (Alice, Bob, Rita), agent scopes, automated vs. human decision matrix, and success metrics. |
| **Evaluation Report** | [`eval/EVAL_REPORT.md`](eval/EVAL_REPORT.md) | 100% script-generated evaluation benchmark report across 23 standardized cases with provider and model telemetry. |
| **Raw Evaluation Telemetry** | [`eval/results.json`](eval/results.json) | Machine-readable benchmark results, per-case latency, token counts, and cost metrics. |
| **Engineering Reflection Note** | [`docs/REFLECTION.md`](docs/REFLECTION.md) | Empirical latency and cost analysis, HP-04 travel heuristic analysis, 3 documented weak spots, boundaries of trust, and production roadmap. |
| **Walkthrough Demo Script** | [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | 4-minute step-by-step interview demonstration script covering happy path, ambiguous input, injection defense, and human review. |
| **Comprehensive Study Guide** | [`docs/STUDY_GUIDE.md`](docs/STUDY_GUIDE.md) | Beginner-friendly file-by-file explanations and 15 rigorous technical interview defense questions with full answers. |
| **MIT License** | [`LICENSE`](LICENSE) | Standard permissive open-source license. |

---

## 💻 Core Application Source Code

| Module | File Path | Architectural Role |
| :--- | :--- | :--- |
| **State Machine & Rules** | [`app/rules.py`](app/rules.py) | `Role` and `Status` enums, immutable `RULES` transition table, title and description length constraints. |
| **Request Service** | [`app/service.py`](app/service.py) | ACID-compliant SQLite data layer with atomic conditional updates (`UPDATE ... WHERE status = expected`). |
| **Multi-Provider LLM Client** | [`app/llm.py`](app/llm.py) | Resilient client supporting Google Gemini (`gemini-3.5-flash-lite`), local Ollama, and offline Mock with exponential backoff on 429. |
| **Structured Output Schemas** | [`app/schemas.py`](app/schemas.py) | Pydantic v2 schemas (`IntakeOutput`, `QualityCheckOutput`, `ReviewAssistOutput`) enforcing strict type boundaries and score limits (1-5). |
| **System Prompts** | [`app/prompts.py`](app/prompts.py) | System instructions with few-shot exemplars, delimiter containment (`<request_data>`), and strict safety guardrails. |
| **Least-Privilege Toolboxes** | [`app/tools.py`](app/tools.py) | Toolboxes enforcing least privilege; `ReviewAssistTools` contains ONLY `get_request` and physically cannot mutate state. Injects frozen `User`. |
| **Specialized AI Agents** | [`app/agents.py`](app/agents.py) | `IntakeAgent`, `QualityCheckAgent`, and `ReviewAssistAgent` with structured schema generation. |
| **Guardrails & Security** | [`app/guardrails.py`](app/guardrails.py) | Regex prompt injection detector, breakout tag sanitizer (`</request_data>`), and sensitive system prompt leakage filter. |
| **Audit Subsystem** | [`app/audit.py`](app/audit.py) | Append-only `agent_audit_log` capturing every AI invocation, prompt tokens, completion tokens, latency, and status. |
| **Notification Subsystem** | [`app/notifications.py`](app/notifications.py) | Persistent in-app notifications and real-time alerts. |
| **Central Orchestrator** | [`app/orchestrator.py`](app/orchestrator.py) | Coordinates agent pipelines, enforces mandatory human checkpoints, handles fallback degradation, and runs SLA escalation checks. |
| **Streamlit Web UI** | [`app/ui.py`](app/ui.py) | Interactive multi-persona application (Alice/Bob as Creators, Rita as Reviewer) with live audit feeds and visual alert banners. |

---

## 🧪 Automated Testing & Evaluation

| Test Suite | File Path | Coverage Summary |
| :--- | :--- | :--- |
| **Service & Rules Tests** | [`tests/test_service.py`](tests/test_service.py) | 26 unit tests covering state transitions, role authorizations, ownership checks, draft confidentiality, and title bounds. |
| **LLM Client Tests** | [`tests/test_llm.py`](tests/test_llm.py) | 5 unit tests covering structured schema responses, retry backoffs, and fallback to mock. |
| **Toolbox Security Tests** | [`tests/test_tools.py`](tests/test_tools.py) | 7 unit tests verifying least-privilege tool isolation and actor injection prevention. |
| **Agent & Schema Tests** | [`tests/test_agents.py`](tests/test_agents.py) | 8 unit tests validating prompt construction, schema conformity, and agent execution. |
| **Orchestrator Tests** | [`tests/test_orchestrator.py`](tests/test_orchestrator.py) | 8 unit tests covering pipeline execution, human-in-the-loop checkpoints, and SLA escalations. |
| **Guardrail Tests** | [`tests/test_guardrails.py`](tests/test_guardrails.py) | 5 unit tests testing regex injection detection, tag sanitization, and output leakage filters. |
| **Total Automated Tests** | **59 / 59 Passed** | 100% test pass rate across standard library `unittest` runner. |
| **Standardized Evaluation** | [`eval/cases.py`](eval/cases.py) | 23 standardized benchmark scenarios (happy path, ambiguous input, invalid transition, role violation, prompt injection, edge cases). |
| **Evaluation Harness** | [`eval/run_eval.py`](eval/run_eval.py) | Evaluation runner recording per-case latency, token usage, cost, and authentic provider attribution. |

---

## 📊 Evaluation Summary at a Glance

- **Execution Quality:** **23 / 23 Valid Runs (100.0%)** | 0 Infrastructure Failures in this single run.
- **Total Suite Accuracy:** **95.65% (22 / 23 passed)**
  - AI Agent cases (`gemini-3.5-flash-lite`): 13 / 14 passed (92.86%)
  - Deterministic checks (`rules_engine`): 9 / 9 passed (100.0%)
- **Prompt Injection Containment:** **Guaranteed by architecture (the review agent has no transition tools)**; 6 / 6 cases preserved status `Submitted`.
- **Prompt Injection Detection (This Run):** 6 / 6 flagged (`injection_suspected: True`; 3 regex, 3 LLM only). *Note: Detection depends on probabilistic LLM judgement, and a 6-case sample is too small to claim a general detection rate.*
- **AI Agent Latency (Gemini Cases):** **1.1714s (~1.17s)** per request (blended suite average with deterministic checks is 0.71s).
- **AI Agent Cost per Request:** **$0.000063 USD** per Gemini call (deterministic checks consume 0 tokens / $0.00).
- **Single Failure Documented:** Case `HP-04` (conference travel reimbursement: Gemini conservatively requested travel dates and learning justification before creating draft; benchmark expectation kept for evaluation honesty).

