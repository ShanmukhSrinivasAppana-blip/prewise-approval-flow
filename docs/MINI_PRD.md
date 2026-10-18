# Product Requirements Document (Mini-PRD)
## Agentic AI Workflow Automation for Request Approval Flow

---

### 1. Executive Summary & Problem Statement
Enterprise approval workflows (procurement, hardware upgrades, travel authorizations) are frequently plagued by two opposing failure modes:
1. **Manual Friction:** Creators submit incomplete or ambiguous requests, causing prolonged back-and-forth email chains with reviewers. Reviewers suffer cognitive overload evaluating routine requests without standardized context.
2. **Autonomous AI Risk:** Unchecked AI agents allowed to make decisions autonomously introduce critical compliance vulnerabilities—including prompt injection exploits, hallucinations, unauthorized budget approvals, and privilege escalation.

**Solution:** Prewise implements a hybrid human-in-the-loop paradigm: **"The AI suggests; a deterministic backend decides."** Intelligent agents assist creators in drafting high-quality requests and provide reviewers with risk-weighted executive recommendations, while a hardened, rule-based state machine deterministically governs state transitions and access boundaries.

---

### 2. User Personas

| Persona | Role | Core Jobs-to-be-Done | Key Pain Points |
| :--- | :--- | :--- | :--- |
| **Creator** (e.g., Alice, Bob) | Creator | • Rapidly draft requests using natural language.<br>• Receive immediate quality feedback.<br>• Track request lifecycle and submit/cancel. | Unclear policy requirements, slow submission processes, lack of visibility into review criteria. |
| **Reviewer** (e.g., Rita) | Reviewer | • Review incoming queue of submitted requests.<br>• View standardized AI risk assessments and summaries.<br>• Approve or reject requests with required justifications. | High volume of poorly formatted requests, hidden compliance risks, fear of automated bypasses. |
| **System Daemon** | System | • Monitor request SLAs.<br>• Automatically escalate overdue requests (> 24 hours).<br>• Maintain tamper-evident audit logging. | Stale requests trapped in queue without owner accountability. |

---

### 3. Agent Responsibilities

1. **Intake Agent:**
   - Parses unstructured natural language input from the Creator.
   - Extracts a concise title (max 120 chars) and detailed description (max 5000 chars).
   - Flags missing fields and poses targeted follow-up questions when information is incomplete.
   - Sets `ready_to_create: True` only when business intent and scope are well-defined.
2. **Quality-Check Agent (Advisory):**
   - Assesses draft requests for clarity (1-5) and completeness (1-5).
   - Scans for policy ambiguities and offers actionable improvement suggestions.
   - Provides risk advisories; the Creator retains full autonomy to accept or ignore.
3. **Review-Assist Agent (Advisory):**
   - Synthesizes an executive summary for human approvers.
   - Evaluates operational and financial risk (1-5) and assigns priority (`low`, `medium`, `high`).
   - Generates an advisory recommendation (`approve`, `reject`, `needs_info`) with reasoning.
   - Flags adversarial patterns (`injection_suspected: True`).

---

### 4. Automated vs. Human Decision Matrix

| Workflow Action | Automation Level | Actor Responsible | Enforcement Mechanism |
| :--- | :---: | :---: | :--- |
| **Draft Information Extraction** | Automated | Intake Agent | Pydantic validation schema (`IntakeOutput`) |
| **Draft Record Creation** | Orchestrated | Orchestrator Engine | `RequestService.create_request` (Creator role only) |
| **Quality Evaluation** | Automated | Quality-Check Agent | Pydantic validation schema (`QualityCheckOutput`) |
| **Suggestion Acceptance** | Manual Choice | Creator | User click in Streamlit UI (Accept / Ignore) |
| **Request Submission** | Human Action | Creator | `transition_request(action='submit')` (Owner only) |
| **Risk & Priority Assessment** | Automated | Review-Assist Agent | Pydantic validation schema (`ReviewAssistOutput`) |
| **Adversarial Injection Detection** | Automated | Guardrail Engine | Regex pattern matcher + delimiter sanitization |
| **Approval / Rejection Decision** | **Strictly Human** | **Reviewer** | `transition_request` requires Reviewer identity + text justification |
| **SLA Escalation Notification** | Automated | Escalation Daemon | SQLite time-delta calculation (> 24 hours) |

---

### 5. Success Metrics

1. **Process Velocity:** 60% reduction in average time-to-decision for standard corporate requests.
2. **First-Time Completeness Rate:** Over 85% of requests created via the Intake Agent contain all mandatory business fields.
3. **Adversarial Protection:** 100% interception of direct and indirect prompt-injection attempts before reaching decision-makers.
4. **Zero AI Overreach:** 0 unauthorized status changes enacted directly by an AI agent (100% adherence to the deterministic state machine).
5. **System Availability & Latency:** Sub-second deterministic backend response; under 2.5s end-to-end latency for structured LLM reasoning.

---

### 6. Risks and Mitigations

| Risk | Impact | Mitigation Strategy |
| :--- | :---: | :--- |
| **Prompt Injection Attack** | Critical | Dual-pass regex scanning (at intake and pre-review), input sanitization stripping `</request_data>`, and physical omission of mutation tools from `ReviewAssistTools`. |
| **LLM Provider Outage / 429** | High | Multi-provider fallback (`gemini` -> `ollama` -> `mock`), exponential backoff retries, and graceful degradation to manual UI mode via `AI_UNAVAILABLE` error codes. |
| **Schema Hallucinations** | Medium | Strict Pydantic validators (`Literal` types for recommendation/priority, range checks `ge=1, le=5` for scores) reject malformed payloads automatically. |
| **State Inconsistency / Race Conditions** | High | Atomic conditional updates (`UPDATE requests SET status = ? WHERE id = ? AND status = ?`) detect concurrent changes and return `CONFLICT`. |
