# Engineering Reflection & Architectural Analysis

### 1. Real Latency and Cost Metrics
Based on the execution of the 19-scenario synthetic evaluation harness:
- **Offline Mock Provider:**
  - Average Latency: **~0.0006s per request**.
  - Approximate Token Cost: **$0.000011 per request** ($0.075 / 1M prompt tokens, $0.30 / 1M candidate tokens).
- **Gemini 2.5 Flash / Flash-Lite Expectations (Live Environment):**
  - Average End-to-End Latency: **~1.2s to 2.4s** per structured JSON invocation (including TLS handshake and reasoning).
  - Average Cost: Less than **$0.0004 per complete workflow execution** (Intake + Quality Check + Review Assist).
  - Rate Limit Budget: Free-tier limits of 15 Requests Per Minute (RPM) necessitate the built-in 2.0s sleep interval implemented in [eval/run_eval.py](file:///c:/Users/shanm/OneDrive/Desktop/prewise%20project/eval/run_eval.py).

---

### 2. Boundaries of Trust: Where the AI Must NOT Be Trusted
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

### 3. Engineering Improvements for Production Roadmap
1. **Role-Based Access Control (RBAC) with OAuth2 / OIDC:**
   - Replace synthetic identity selection with verified JWT tokens issued by Okta or Azure AD.
2. **Distributed Persistence:**
   - Migrate SQLite to PostgreSQL with row-level locking (`SELECT FOR UPDATE`) or optimistic concurrency control (`version` integer column) for multi-pod Kubernetes deployments.
3. **Dynamic Few-Shot Exemplars via RAG:**
   - Retrieve approved historical requests from a vector store to ground the Review-Assist agent in company-specific precedent.
4. **Asynchronous Webhooks for Escalations:**
   - Connect the SLA escalation engine to Slack / Microsoft Teams webhooks to alert reviewers in their existing collaboration hubs.
