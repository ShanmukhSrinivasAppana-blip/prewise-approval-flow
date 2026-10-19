# Prewise Intern Study Guide & Interview Defense Manual

This comprehensive guide is designed to help you explain every architectural decision, file, business rule, and security invariant during your technical interviews.

---

## Part 1: File-by-File Explanations

### 1. `app/rules.py`
- **What it does:** Declares the canonical `Role` (`Creator`, `Reviewer`) and `Status` (`Draft`, `Submitted`, `Approved`, `Rejected`, `Cancelled`) enums, maximum field lengths, and the centralized `RULES` configuration dictionary.
- **Why it exists:** Centralizes the state machine definitions in one declarative location instead of scattering conditional logic across functions.
- **Rules Enforced:**
  - Creators can only `submit` or `cancel`.
  - Reviewers can only `approve` or `reject`.
  - Only `Submitted` requests can be Approved or Rejected.
  - Approved requests cannot be cancelled.
  - `Rejected` and `Cancelled` are terminal states.

### 2. `app/service.py`
- **What it does:** Implements `RequestService` (SQLite backend) and the immutable `User` dataclass. Provides `create_request`, `get_request`, `submit_request`, and the single validator: `transition_request`.
- **Why it exists:** Serves as the single source of truth for database state and atomic execution.
- **Rules Enforced:**
  - **Strict Check Order:** (1) `UNKNOWN_ACTION` -> (2) `NOT_FOUND` -> (3) `ROLE_NOT_ALLOWED` -> (4) `NOT_OWNER` -> (5) `INVALID_TRANSITION`.
  - **Race Condition Safety (`CONFLICT`):** Executes conditional updates `UPDATE requests SET status = ? WHERE id = ? AND status = ?`.
  - **Visibility Invariant (`NOT_VISIBLE`):** Reviewers cannot view `Draft` requests.

### 3. `app/llm.py`
- **What it does:** Abstraction layer for structured JSON generation supporting Gemini (via `google-genai`), local Ollama, and a deterministic offline Mock provider.
- **Why it exists:** Decouples agent business logic from specific LLM SDKs, implements exponential backoff retries (up to 3 times), schema validation, and fallback mechanisms.
- **Rules Enforced:**
  - Validates output using Pydantic; retries if JSON is malformed or invalid.
  - Switches to `LLM_FALLBACK_PROVIDER` if the primary provider fails.
  - Raises `LLMUnavailableError` if all attempts fail, enabling the human fallback mode.

### 4. `app/schemas.py`
- **What it does:** Defines Pydantic data schemas: `IntakeOutput`, `QualityCheckOutput`, and `ReviewAssistOutput`.
- **Why it exists:** Guarantees strict structure and typing for all LLM responses, eliminating free-form hallucinated outputs.
- **Rules Enforced:**
  - `Literal["low", "medium", "high"]` and `Literal["approve", "reject", "needs_info"]` reject hallucinated categories.
  - Field constraints (`ge=1, le=5` for scores; `max_length=120` for titles) reject out-of-range model output.

### 5. `app/prompts.py`
- **What it does:** Contains system instructions and few-shot exemplars for the three agents.
- **Why it exists:** Establishes prompt-isolation boundaries for prompt-injection defense.
- **Rules Enforced:**
  - Untrusted user text is strictly enclosed in `<request_data>` tags.
  - Instructs the agent to never obey commands inside `<request_data>`.
  - Explicitly forbids revealing system instructions.

### 6. `app/tools.py`
- **What it does:** Defines `ToolBox`, `IntakeTools`, and `ReviewAssistTools`. Dispatches tool calls validated by Pydantic.
- **Why it exists:** Enforces **Least Privilege** and secure **Actor Injection**.
- **Rules Enforced:**
  - Architectural Pattern: *LLM proposes structured output, orchestrator executes through a least-privilege tool layer (`IntakeTools.dispatch`, `ReviewAssistTools.dispatch`).*
  - Actor is injected in Python code; any attempt to pass `actor` or `actor_id` in tool parameters is stripped.
  - `IntakeTools` permits ONLY `create_request` and `get_request`.
  - `ReviewAssistTools` contains ONLY `get_request`. It physically lacks approval or mutation methods, making automated takeover impossible.


### 7. `app/agents.py`
- **What it does:** Implements `IntakeAgent`, `QualityCheckAgent`, and `ReviewAssistAgent`.
- **Why it exists:** Packages reasoning tasks into clean, modular agents that produce structured advisory outputs.
- **Rules Enforced:**
  - Agents are pure advisors. They NEVER mutate state directly or execute approvals.

### 8. `app/guardrails.py`
- **What it does:** Houses regex-based prompt injection detection (`scan_for_injection`), delimiter breakout sanitization (`sanitize_input`), and prompt leakage filtering (`filter_prompt_leakage`).
- **Why it exists:** Provides pre-LLM and post-LLM defensive shields against adversarial manipulation.
- **Rules Enforced:**
  - Flags phrases like *"ignore rules"*, *"approve this"*, *"system prompt"*, and *"you are now"*.
  - Strips `</request_data>` closing tags to prevent boundary escaping.
  - Redacts responses echoing internal system prompt signatures.

### 9. `app/audit.py`
- **What it does:** Manages the `agent_audit_log` SQLite table recording every single agent call, latency, token count, and security event.
- **Why it exists:** Provides complete enterprise auditability and compliance observability.
- **Rules Enforced:**
  - Immutable historical record of all automated reasoning and human decisions.

### 10. `app/notifications.py`
- **What it does:** Dispatches console alerts and persists user notifications in SQLite.
- **Why it exists:** Keeps Creators and Reviewers informed of state changes in real time.
- **Rules Enforced:**
  - Broadcasts alerts when drafts are created, submitted, approved, rejected, or escalated.

### 11. `app/orchestrator.py`
- **What it does:** Central workflow coordinator (`handle_intake`, `check_quality`, `submit`, `assist_review`, `human_decision`, `cancel`, and `check_auto_escalation`).
- **Why it exists:** Glues together agents, guardrails, audit logging, notifications, and the deterministic service.
- **Rules Enforced:**
  - Creates the draft only when `ready_to_create: True`.
  - Intercepts `LLMUnavailableError` and returns `AI_UNAVAILABLE` so humans can proceed manually.
  - Human checkpoint: `human_decision` enforces Reviewer identity and requires a text justification.

### 12. `app/ui.py`
- **What it does:** Streamlit web interface with persona switching (Alice, Bob, Rita).
- **Why it exists:** Provides an intuitive, visual presentation layer for user evaluation and interactive demonstrations.
- **Rules Enforced:**
  - Reviewers cannot see Drafts.
  - Clear red warning banners for detected prompt injections.
  - Requires non-empty reason before approving or rejecting.

---

## Part 2: 15 Likely Interview Questions & Model Answers

### Q1: What is the core architectural principle of this system?
**Answer:** *"The AI suggests; a deterministic backend decides. Large language models provide advisory reasoning, summarization, and draft extraction, but zero state transitions or database writes can be enacted directly by an AI model. All transitions must pass through a centralized deterministic state machine."*

### Q2: Why did you choose plain Python orchestration over LangChain or CrewAI?
**Answer:** *"For a security-critical enterprise approval flow, simplicity, auditability, and control are paramount. Frameworks like LangChain add heavy abstractions, hidden prompt chains, and unpredictable execution loops. By writing plain Python, every function call, tool invocation, token count, and fallback path is explicit, easily unit-tested, and fully transparent."*

### Q3: How do you prevent an AI agent from approving a request on its own?
**Answer:** *"Through defense-in-depth across three layers: First, `ReviewAssistTools` contains ONLY `get_request`—it physically has no transition or approval tools. Second, the Review-Assist agent is strictly advisory. Third, the backend validator `transition_request` strictly checks that the authenticated actor possesses `Role.REVIEWER` and is called exclusively through the human-in-the-loop checkpoint (`human_decision`)."*

### Q4: How do you prevent an attacker from spoofing another user’s identity in tool calls?
**Answer:** *"Actor injection. The authenticated `User` object is a frozen dataclass instantiated on the server and injected directly into the toolbox constructor. In `ToolBox.dispatch()`, any parameters matching `actor`, `actor_id`, or `role` supplied in the argument payload are stripped before execution."*

### Q5: What is the validation order in `transition_request`, and why does order matter?
**Answer:** *"The order is: (1) Unknown action, (2) Request not found, (3) Role check, (4) Ownership check, (5) Allowed source status. Order matters because evaluating permissions before checking existence could leak information about whether a private record ID exists."*

### Q6: How do you protect against race conditions when two approvers click simultaneously?
**Answer:** *"We use atomic conditional SQL updates: `UPDATE requests SET status = ? WHERE id = ? AND status = ?`. If two concurrent requests attempt to transition the same record, SQLite executes them sequentially; the first succeeds, and the second updates 0 rows, prompting our backend to return an explicit `CONFLICT` error."*

### Q7: Why are Reviewers prohibited from seeing Draft requests?
**Answer:** *"To protect employee privacy and prevent premature evaluations. Drafts are private working spaces where Creators can brainstorm and run advisory quality checks before formal submission. Enforcing this in `get_request` and `list_requests` ensures Reviewers only see finalized submissions."*

### Q8: How does your prompt-injection defense work?
**Answer:** *"We employ a multi-layered defense: (1) A case-insensitive, whitespace-tolerant regex scanner checks untrusted text for phrases like 'ignore rules' or 'approve this'. (2) User input is delimited within `<request_data>` tags, and closing tags are stripped to prevent breakout attacks. (3) If flagged, `injection_suspected` is locked to True, a prominent warning is shown to the reviewer, and the request status remains strictly unchanged."*

### Q9: What happens if the Gemini API goes down or hits a rate limit?
**Answer:** *"The LLM client retries up to 3 times with exponential backoff. If failures persist, it automatically attempts the configured `LLM_FALLBACK_PROVIDER`. If all providers fail, it raises `LLMUnavailableError`. The orchestrator catches this and returns `AI_UNAVAILABLE`, allowing users to manually fill out or review requests without system downtime."*

### Q10: How do you prevent the LLM from hallucinating invalid fields or scores?
**Answer:** *"We use Pydantic schemas with strict validation. Scores are bounded with `ge=1, le=5`, and categorical outputs like priority and recommendation use `Literal['low', 'medium', 'high']` and `Literal['approve', 'reject', 'needs_info']`. Any hallucinated value that violates the schema fails validation and triggers an automatic retry."*

### Q11: Why is an Approved request prohibited from being cancelled?
**Answer:** *"In enterprise workflows, an approval represents a legally or financially binding authorization (e.g., funds committed or purchase orders issued). Allowing a Creator to unilaterally cancel an approved commitment introduces financial reconciliation errors. Any post-approval revocation requires a separate formal reversal flow."*

### Q12: Why is the SQLite connection configured with `check_same_thread=False` and a `threading.Lock`?
**Answer:** *"Streamlit runs user sessions across multiple background threads. SQLite connections by default restrict access to the creating thread. Using `check_same_thread=False` paired with a Python `threading.Lock()` provides thread safety, preventing database corruption during concurrent interactions."*

### Q13: What is the purpose of the Escalation Daemon?
**Answer:** *"To enforce enterprise SLAs. The function `check_auto_escalation(threshold_hours=24.0)` queries all `Submitted` requests, measures their pending duration using `req['updated_at']` (which records the exact timestamp of submission), and automatically triggers high-priority escalation notifications to reviewers and logs an audit event if pending time exceeds the SLA threshold."*

### Q14: How does your test suite guarantee system reliability?
**Answer:** *"We maintain 63 comprehensive unit tests across five test suites covering 100% of the deterministic business rules, state transitions, least-privilege toolboxes, LLM retries, fallback paths, and guardrail defenses. Additionally, an evaluation harness tests 26 standardized benchmark scenarios against the real orchestrator, including benign false-positive testing."*


### Q15: If this system were deployed to production with 10,000 users, what would you upgrade first?
**Answer:** *"First, replace SQLite with PostgreSQL using connection pooling and row-level locking. Second, replace synthetic user switching with OAuth2/OIDC JWT authentication. Third, run agent reasoning tasks asynchronously using Celery or AWS SQS to prevent HTTP timeouts during LLM latency spikes."*
