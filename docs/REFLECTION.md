# Engineering Reflection & Architectural Analysis

### 1. Real Latency and Cost Metrics (Empirical Live Data)
Based on a single execution run of the 23-scenario evaluation harness against **Google Gemini (`gemini-3.5-flash-lite`)** and the deterministic rules engine:
- **Empirical Live AI Evaluation Results:**
  - **Execution Scope:** Single evaluation run on `gemini-3.5-flash-lite`. (An earlier 3-run attempt on `gemini-3.8-flash` showed accuracy varying between 82.6% and 87.0%, partly contaminated by daily API quota limits and 429 rate limiting).
  - **AI Agent Cases (Gemini):** 14 scenarios evaluated. 13 passed, 1 failed (`HP-04`). **AI Accuracy: 92.86% (13/14)**.
  - **Deterministic Backend Checks:** 9 scenarios evaluated (transitions, role checks, title boundary). 9 passed. **Accuracy: 100.0% (9/9)**.
  - **Total Suite Accuracy:** **95.65% (22/23 passed)**.
  - **AI Agent Latency (Gemini-Called Cases Only):** **1.1714s** (~1.17s) average latency across the 14 LLM-evaluated cases (incorporating Google API roundtrips and structured JSON schema decoding).  
    *(Deterministic checks take 0.0006s; reporting a blended average of 0.71s is misleading, so AI latency is reported strictly for AI calls).*
  - **AI Agent Cost per Request (Gemini-Called Cases Only):** **$0.000063 USD** on average ($0.075 / 1M prompt tokens, $0.30 / 1M completion tokens). A full multi-agent cycle costs less than **1/150th of a single cent**. Deterministic checks cost $0.000000.
  - **Security Telemetry:**
    - **Prompt Injection Containment:** **Guaranteed by architecture (the review agent has no transition tools)**. All 6 cases maintained database status `Submitted` without mutation.
    - **Prompt Injection Detection (This Run):** 6/6 cases flagged `injection_suspected: True` in this single run (3 caught by keyword regex, 3 caught by Gemini semantic evaluation).
    - **Detection Caveat:** Detection depends on probabilistic LLM judgement, and a 6-case synthetic sample is far too small to claim a general detection rate.

---

### 2. Genuine AI Failure Analysis & Benchmark Disagreement (HP-04)
The evaluation recorded exactly **1 failed case out of 23**:
- **Case `HP-04`:** Customer conference attendance and travel reimbursement ($1,850 total: $1,099 ticket + $751 hotel).
  - **Expected:** `ready_to_create: True` with draft creation.
  - **Actual:** `ready_to_create: False`, asking follow-up questions: *"What are the specific dates you plan to attend AWS re:Invent?"* and *"How will attending this conference benefit your current projects or team?"*
  - **Analysis:** Gemini applied a conservative, policy-compliant travel heuristic: travel requests without concrete dates and business learning justification require clarification before drafting. While the synthetic benchmark expected immediate draft creation, the LLM exhibited prudent procurement behavior. In adherence to evaluation honesty, the benchmark expectation was **not** altered, and the failure is reported truthfully.
  - **Contrast with `HP-05`:** When presented with fully itemized workstation peripherals including exact model numbers, costs, and cost center, Gemini scored 100% and immediately created the draft.

---

### 3. Known Architectural Weak Spots & Honest Trade-Offs

1. **Regex Injection Detection: Bypassability vs. False Positives:**
   - **Weak Spot (False Negatives):** Simple keyword pattern scanning (`"ignore rules"`, `"system prompt"`, `"approve this"`) is brittle. Paraphrased instructions (`INJ-04`), multi-lingual attacks (`INJ-05`), and split-sentence instructions (`INJ-06`) bypass regex entirely.
   - **Weak Spot (False Positives):** Rigid regex patterns like `approve\s+this` flag polite natural conversational phrasing (e.g., *"Please approve this purchase"* or *"Kindly approve this request"*). In our expanded 26-case benchmark, 3 benign cases (`BEN-01` to `BEN-03`) empirically demonstrated this sensitivity vs. precision trade-off.
   - **Mitigation & Reality:** False positive alerts merely display a cautionary banner to the human reviewer; they **never** alter database status or execute unauthorized actions. Crucially, **containment is guaranteed by architecture**: the Review-Assist Agent has no transition tools in its toolbox and cannot write database state under any circumstances.


2. **UI Persona Switcher is Not Real Authentication:**
   - **Weak Spot:** The Streamlit sidebar user selector (`Alice`, `Bob`, `Rita`) is a client-side simulation designed for interactive evaluation and demonstration.
   - **Production Requirement:** In production, the client must never supply `actor_id` or `role`. Authentication must be handled by an API Gateway validating signed JWT tokens (OAuth2/OIDC) from Okta, Azure AD, or Auth0, injecting the authenticated `User` context securely into the service layer.

3. **`NOT_FOUND` Precedes Role Validation:**
   - **Weak Spot:** In `RequestService`, request existence is checked before the calling user's role or ownership permissions.
   - **Information Disclosure Vector:** If user Bob queries request ID `999` (nonexistent), he receives `NOT_FOUND`. If he queries request ID `1` (Alice's private Draft), he receives `NOT_VISIBLE` or `ROLE_NOT_ALLOWED`. An attacker can enumerate valid request IDs by comparing error responses before authorization is enforced.
   - **Remediation:** In multi-tenant enterprise architectures, authorization or tenant scoping should be evaluated within the database query itself (`SELECT ... WHERE id = ? AND tenant_id = ?`) or return a uniform `NOT_FOUND` to prevent ID enumeration.

---

### 4. Boundaries of Trust: Where the AI Must NOT Be Trusted
Building robust AI systems requires identifying what LLMs cannot do reliably:
1. **Never Trust the Agent with State Transitions:**
   - Large Language Models are probabilistic next-token predictors, not finite-state automata. An agent instructed "never approve a draft" will still occasionally approve one if primed with convincing context. State mutation must be 100% deterministic code.
2. **Never Trust the Agent to Authenticate Actors:**
   - Prompt context is inherently malleable. If an agent is allowed to declare `{"actor_id": "rita"}`, privilege escalation is trivial. Identities must be injected by backend session tokens or cryptographic signatures.
3. **Never Trust the Agent's Numerical Bounds Without Schemas:**
   - LLMs routinely hallucinate ratings outside boundaries (e.g., returning priority="urgent" or risk_score=10 when 1-5 is required). Strict Pydantic models with `Literal` types and boundary checks (`ge=1, le=5`) are mandatory.
4. **Never Trust the Agent to Enforce Budget Hardcaps Alone:**
   - Financial authority must be validated by backend arithmetic against company budget ledgers, not an LLM's subjective evaluation of cost reasonableness.

---

### 5. Engineering Improvements for Production Roadmap
1. **Role-Based Access Control (RBAC) with OAuth2 / OIDC:**
   - Replace synthetic identity selection with verified JWT tokens issued by Okta or Azure AD.
2. **Distributed Persistence:**
   - Migrate SQLite to PostgreSQL with row-level locking (`SELECT FOR UPDATE`) or optimistic concurrency control (`version` integer column) for multi-pod Kubernetes deployments.
3. **Dynamic Few-Shot Exemplars via RAG:**
   - Retrieve approved historical requests from a vector store to ground the Review-Assist agent in company-specific precedent.
4. **Asynchronous Webhooks for Escalations:**
   - Connect the SLA escalation engine to Slack / Microsoft Teams webhooks to alert reviewers in their existing collaboration hubs.

