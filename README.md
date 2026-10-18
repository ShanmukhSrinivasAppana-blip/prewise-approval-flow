# Prewise Request Approval Flow: Agentic AI Workflow Automation

[![Tests](https://img.shields.io/badge/Unit%20Tests-59%20Passed-success)](tests/)
[![Evaluation](https://img.shields.io/badge/Eval%20Accuracy-95.65%25%20(22%2F23)-blue)](eval/EVAL_REPORT.md)
[![Execution Quality](https://img.shields.io/badge/Valid%20Runs-100%25%20(23%2F23)-brightgreen)](eval/EVAL_REPORT.md)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![UI](https://img.shields.io/badge/UI-Streamlit-FF4B4B)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Demo video:** `<add link>`

A production-grade, modular, and hardened Agentic AI workflow automation system for enterprise request approvals.

---

## ⚡ Quick Start

```powershell
# 1. Clone & enter project folder
git clone <repo-url>
cd "prewise project"

# 2. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env to add your GEMINI_API_KEY (or keep LLM_PROVIDER=mock for 100% offline testing)

# 5. Run the full unit test suite (59 tests)
python -m unittest discover -s tests -p "test_*.py" -v

# 6. Launch the interactive Streamlit UI
streamlit run app/ui.py

# 7. Run the standardized evaluation benchmark (23 cases)
python -m eval.run_eval --resume
```

---

## 🎯 Core Architectural Principle

> **"The AI suggests; a deterministic backend decides."**
> 
> AI agents can never write request status directly, can never choose who they act as, and can never approve or reject on their own. All state mutations pass through a single centralized, deterministic state machine.

---

## 📊 Live Evaluation Benchmark Results

The evaluation harness was executed in a single run against **Google Gemini (`gemini-3.5-flash-lite`)** and the deterministic rules engine across 23 standardized test cases:
*(Note: An earlier 3-run attempt on `gemini-3.8-flash` showed accuracy varying between 82.6% and 87.0%, partly contaminated by daily API quota limits).*

| Metric | Result | Details |
| :--- | :---: | :--- |
| **Execution Quality** | **100.0% (23/23)** | 23 valid real executions, **0** infrastructure failures in this run |
| **Total Suite Accuracy** | **95.65% (22/23)** | 22 passed, 1 genuine AI failure (`HP-04`) |
| **AI Agent Latency (Gemini Cases)** | **1.1714s (~1.17s)** | Reported strictly for the 14 Gemini calls (blended suite average including deterministic checks is 0.71s) |
| **AI Agent Cost per Request** | **$0.000063 USD** | Reported strictly for Gemini calls ($0.075 / 1M input, $0.30 / 1M output; deterministic checks cost $0) |
| **Prompt Injection Containment** | **Guaranteed by Architecture** | **The review agent has no transition tools**; all 6 cases strictly preserved status `Submitted` |
| **Prompt Injection Detection (This Run)** | **6/6 Flagged** | 3 caught by regex pattern scanning, 3 caught by Gemini semantic evaluation |

> [!WARNING]
> **Detection Sample Size Caveat:** While all 6 prompt injections were flagged in this run, detection depends on probabilistic LLM judgement. A 6-case synthetic sample is far too small to claim a general detection rate. Containment, however, is deterministic and mathematically guaranteed by tool isolation.

### Component Execution Breakdown

*(Note: The deterministic backend is Python business logic, not an AI model).*

| Component | Technology | Cases Evaluated | Passed | Accuracy (%) | Avg Latency | Avg Cost ($) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **AI Agents** | `gemini-3.5-flash-lite` | 14 | 13 | **92.9%** | **1.1714s** | **$0.000063** |
| **Deterministic Backend** | Python `rules_engine` | 9 | 9 | **100.0%** | **0.0006s** | **$0.000000** |

### Genuine AI Failure Analysis (`HP-04`)
- **Case `HP-04` (Customer conference attendance):** The synthetic benchmark expected immediate draft creation (`ready_to_create: True`) based on itemized costs ($1,099 ticket + $751 hotel). Gemini conservatively judged that travel reimbursement requests require specific travel dates and learning objectives before draft creation, setting `ready_to_create: False` and asking follow-up questions.
- **Evaluation Honesty:** The benchmark expectation was preserved as-is. In contrast, **`HP-05`** (complete workstation equipment request with cost center) passed with 100% accuracy.

---

## 🏗️ Stack Justification

| Technology | Selection | Engineering Justification |
| :--- | :--- | :--- |
| **Orchestration** | Plain Python | Zero bloated third-party abstractions (no LangChain / CrewAI). Complete transparency, explicit execution paths, and zero hidden prompt loops. |
| **Primary LLM** | Google Gemini (`google-genai` SDK) | Native JSON schema enforcement (`response_schema`), industry-leading price/performance, and robust structured reasoning via Gemini Flash. |
| **Fallback LLMs** | Ollama & Built-in Mock | High-availability resilience: runs locally via Ollama or 100% offline via the canned Mock provider for CI/CD and air-gapped unit tests. |
| **Output Validation** | Pydantic v2 | Guarantees strict type safety, literal enum validation, and boundary enforcement (1-5 scores) to eliminate hallucinated fields. |
| **Database** | SQLite3 | ACID-compliant, zero-dependency, serverless relational database with atomic conditional updates for race-condition prevention. |
| **Web Presentation** | Streamlit | Rapid interactive prototyping with reactive state management, persona switching, and real-time audit trail rendering. |
| **Test Framework** | Python `unittest` | Built-in standard library testing with zero extra dependencies; runs fast, deterministic, reproducible test suites (59/59 passing). |
| **Config & Secrets** | `python-dotenv` | Twelve-factor app compliance: secrets (`GEMINI_API_KEY`) and models are loaded strictly from `.env` and never committed. |

---

## 📌 Documented Assumptions

1. **Cancellation Boundaries:** A Creator may cancel a request in either `Draft` or `Submitted` status. Once a request reaches `Approved`, it **cannot** be cancelled.
2. **Terminal States:** `Approved`, `Rejected`, and `Cancelled` are strictly terminal statuses. No further transitions can originate from them.
3. **Ownership Enforced:** Only the specific Creator who created a request can `submit` or `cancel` it (`NOT_OWNER` error code otherwise).
4. **Draft Confidentiality:** Reviewers **cannot** see `Draft` requests (`NOT_VISIBLE` error code). Reviewers are only granted access once a request is formally `Submitted`.
5. **Mandatory Human-in-the-Loop:** Approvals and rejections can only be enacted by a human Reviewer with an explicit textual justification.

---

## 🛡️ Multi-Layer Guardrails & Security

1. **Least-Privilege Toolboxes:**
   - `ReviewAssistTools` contains ONLY `get_request`. It physically lacks any mutation or approval methods. Even if an LLM is hijacked via prompt injection, it cannot approve requests.
2. **Actor Injection:**
   - The authenticated `User` object is injected in backend Python code. Any parameters matching `actor`, `actor_id`, or `role` passed by an LLM are automatically stripped.
3. **Regex Prompt Injection Detection:**
   - Detects adversarial patterns (*"ignore rules"*, *"approve this"*, *"system prompt"*, *"override checks"*).
   - Automatically forces `injection_suspected: True` and renders a prominent red warning banner for the human reviewer.
4. **Delimiter Sanitization:**
   - All untrusted input is enclosed within `<request_data>` tags.
   - Any attempted closing tag `</request_data>` is stripped to prevent boundary breakout.
5. **Output Leakage Filtering:**
   - Scans model responses for sensitive internal system instructions and redacts them if detected.

---

## ⚠️ Known Architectural Weak Spots & Honest Limitations

1. **Regex Injection Detection is Bypassable:**
   - **Weak Spot:** Static keyword scanning only caught 3 of 6 injection attacks (`INJ-01`, `INJ-02`, `INJ-03`). Paraphrased instructions (`INJ-04`), multi-lingual attacks (`INJ-05`), and split-sentence attacks (`INJ-06`) bypass regex pattern filters.
   - **Mitigation:** The secondary LLM semantic evaluation caught the remaining 3 attacks. Most importantly, **100% containment is guaranteed by physical architecture**: the Review-Assist Agent has no mutation tools and cannot alter database status.
2. **UI Persona Switcher is Not Real Authentication:**
   - **Weak Spot:** The Streamlit sidebar user selector (`Alice`, `Bob`, `Rita`) is a client-side simulation designed for interactive evaluation and demonstration.
   - **Production Requirement:** In production, identity must be validated at the API boundary via signed OAuth2 / OIDC JWT bearer tokens (Okta, Azure AD), securely injecting authenticated `User` context.
3. **`NOT_FOUND` Precedes Role Validation:**
   - **Weak Spot:** In `RequestService`, request existence is checked before the calling user's role or ownership permissions.
   - **Information Disclosure Vector:** A caller querying nonexistent ID `999` receives `NOT_FOUND`, but querying Alice's private draft `1` receives `NOT_VISIBLE`. This allows an unauthorized user to probe whether specific request IDs exist.
   - **Production Requirement:** Enforce authorization within the database query itself (`WHERE id = ? AND owner_id = ?`) or return a uniform `NOT_FOUND` to prevent ID enumeration.
4. **Database Scale:** SQLite provides excellent single-node performance and ACID guarantees via file locks, but multi-region distributed deployments should migrate to PostgreSQL with row-level locks.
5. **Escalation Daemon:** The SLA escalation daemon currently operates via API/button trigger; in production, run it as a background cron job (e.g., Celery beat or AWS EventBridge).

---

## 📂 Repository Structure

```text
├── app/
│   ├── rules.py           # State machine enums, RULES dictionary, validation limits
│   ├── service.py         # RequestService (SQLite), User dataclass, atomic transitions
│   ├── llm.py             # LLM client: Gemini, Ollama, Mock with retry & fallback
│   ├── schemas.py         # Pydantic schemas for structured agent outputs
│   ├── prompts.py         # System prompts with few-shot examples and safety delimiters
│   ├── tools.py           # Least-privilege toolboxes and actor injection
│   ├── agents.py          # Intake, Quality-Check, and Review-Assist agents
│   ├── guardrails.py      # Regex injection scanner, sanitizer, leakage filter
│   ├── audit.py           # Agent audit logging subsystem (agent_audit_log table)
│   ├── notifications.py   # Notification manager (notifications table + console)
│   ├── orchestrator.py    # Central coordinator, human checkpoint, auto-escalation
│   └── ui.py              # Streamlit interactive multi-persona web application
├── docs/
│   ├── architecture.md    # Mermaid architecture flowchart and state diagram
│   ├── MINI_PRD.md        # Product Requirements Document (PRD)
│   ├── REFLECTION.md      # Latency/cost metrics, boundaries of trust, roadmap
│   ├── DEMO_SCRIPT.md     # Walkthrough demonstration script
│   └── STUDY_GUIDE.md     # File-by-file explanations and 15 interview defense Q&As
├── eval/
│   ├── cases.py           # 23 synthetic evaluation cases (happy, ambiguous, injections, edge cases)
│   ├── run_eval.py        # Evaluation runner with token cost and latency telemetry
│   ├── results.json       # Raw evaluation metrics output
│   └── EVAL_REPORT.md     # Formatted markdown evaluation report
├── tests/
│   ├── test_service.py    # 26 unit tests for backend state machine and rules
│   ├── test_llm.py        # 5 unit tests for LLM retry, schema, and fallback
│   ├── test_tools.py      # 7 unit tests for least-privilege toolboxes
│   ├── test_agents.py     # 8 unit tests for schemas, prompts, and agents
│   ├── test_orchestrator.py # 8 unit tests for orchestrator, checkpoints, SLA
│   └── test_guardrails.py # 5 unit tests for injection detection and sanitization
├── requirements.txt       # Project dependencies
├── .env.example           # Configuration template
├── .gitignore             # Secrets, cache, and database exclusions
├── LICENSE                # MIT License
├── SUBMISSION.md          # Submission checklist and artifact index
└── README.md              # Project documentation and guide
```
