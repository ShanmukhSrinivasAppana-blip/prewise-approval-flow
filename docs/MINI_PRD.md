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

### 5. Empirical Benchmark Validation & Success Metrics

In live empirical evaluations across 23 standardized benchmark scenarios evaluated against Google Gemini (`gemini-3.5-flash-lite`) and the deterministic state machine:
1. **AI Overall Accuracy:** **95.65% (22/23 cases passed)** across happy path, ambiguous input, invalid transition, role violation, injection, and boundary edge cases. Exactly 1 disagreement occurred (`HP-04`, where Gemini conservatively required travel dates and justification before creating a draft).
2. **Adversarial Containment:** **100.0% containment (6/6 cases)**. Zero unauthorized status mutations occurred across direct, indirect, paraphrased, and multi-lingual prompt injections.
3. **Adversarial Detection:** **100.0% detection (6/6 cases)** flagged with `injection_suspected: True` across hybrid regex and LLM semantic layers.
4. **Zero AI Overreach:** Exactly 0 unauthorized status changes were enacted directly by AI agents (100% adherence to deterministic state machine enforcements).
5. **System Latency & Cost:**
   - **Average Overall Latency:** `0.7132s` (1.1714s for Gemini LLM reasoning, 0.0006s for deterministic checks).
   - **Average Cost per Request:** `$0.000039 USD` per request ($0.000063 for Gemini calls, $0.000000 for deterministic checks).

---

### 6. Risks, Mitigations & Documented Architectural Weak Spots

| Risk / Weak Spot | Impact | Mitigation Strategy & Production Roadmap |
| :--- | :---: | :--- |
| **Regex Injection Bypassability** | Medium | **Empirical Reality:** Keyword regex (`"ignore rules"`, `"system prompt"`) only caught 3/6 attacks; paraphrased and multi-lingual attacks (`INJ-04`, `INJ-05`, `INJ-06`) bypassed it. **Mitigation:** The LLM semantic layer caught the remaining 3/6. More critically, **100% containment is guaranteed by physical architecture**: `ReviewAssistTools` contains zero mutation tools and cannot write database state. |
| **UI Persona Switcher Not Real Auth** | Medium | **Current State:** The Streamlit sidebar user selector is an interactive client-side simulation. **Production Roadmap:** Replace client persona selection with an API Gateway verifying signed OAuth2 / OIDC JWT bearer tokens (Okta, Azure AD), injecting immutable `User` context securely into the service layer. |
| **`NOT_FOUND` Checked Before Role** | Low | **Current State:** `RequestService` checks request existence before user role/ownership permissions, allowing request ID enumeration. **Production Roadmap:** Enforce tenant/owner query scoping in SQL (`SELECT ... WHERE id = ? AND owner_id = ?`) or normalize return codes to uniform `NOT_FOUND` to eliminate ID probing. |
| **LLM Provider Outage / Rate Limits (429)** | High | Multi-provider fallback (`gemini` -> `ollama` -> `mock`), exponential backoff retries, and graceful degradation to manual UI mode via `AI_UNAVAILABLE` error codes. |
| **Schema Hallucinations** | Medium | Strict Pydantic validators (`Literal` types for recommendation/priority, range checks `ge=1, le=5` for scores) reject malformed payloads automatically. |
| **State Inconsistency / Race Conditions** | High | Atomic conditional updates (`UPDATE requests SET status = ? WHERE id = ? AND status = ?`) detect concurrent changes and return `CONFLICT`. |
| **Conservative Travel Intake (`HP-04`)** | Low | LLM conservatively asked clarifying questions for conference travel rather than immediately creating a draft. Solved in production via fine-tuned few-shot prompt examples tailored to company travel policy. |

