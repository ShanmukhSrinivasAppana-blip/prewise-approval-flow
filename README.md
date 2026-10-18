# Prewise Request Approval Flow: Agentic AI Workflow Automation

[![Tests](https://img.shields.io/badge/Unit%20Tests-59%20Passed-success)](tests/)
[![Evaluation](https://img.shields.io/badge/Eval%20Accuracy-100%25%20(19%2F19)-blue)](eval/EVAL_REPORT.md)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![UI](https://img.shields.io/badge/UI-Streamlit-FF4B4B)](https://streamlit.io/)

A production-grade, modular, and hardened Agentic AI workflow automation system for enterprise request approvals.

---

## 🎯 Core Architectural Principle

> **"The AI suggests; a deterministic backend decides."**
> 
> AI agents can never write request status directly, can never choose who they act as, and can never approve or reject on their own. All state mutations pass through a single centralized, deterministic state machine.

---

## 🏗️ Stack Justification

| Technology | Selection | Engineering Justification |
| :--- | :--- | :--- |
| **Orchestration** | Plain Python | Zero bloated third-party abstractions (no LangChain / CrewAI). Complete transparency, explicit execution paths, and zero hidden prompt loops. |
| **Primary LLM** | Google Gemini (`google-genai` SDK) | Native JSON schema enforcement (`response_schema`), industry-leading price/performance, and robust structured reasoning via Gemini 2.5 Flash. |
| **Fallback LLMs** | Ollama & Built-in Mock | High-availability resilience: runs locally via Ollama or 100% offline via the canned Mock provider for CI/CD and air-gapped unit tests. |
| **Output Validation** | Pydantic v2 | Guarantees strict type safety, literal enum validation, and boundary enforcement (1-5 scores) to eliminate hallucinated fields. |
| **Database** | SQLite3 | ACID-compliant, zero-dependency, serverless relational database with atomic conditional updates for race-condition prevention. |
| **Web Presentation** | Streamlit | Rapid interactive prototyping with reactive state management, persona switching, and real-time audit trail rendering. |
| **Test Framework** | Python `unittest` | Built-in standard library testing with zero extra dependencies; runs fast, deterministic, reproducible test suites. |
| **Config & Secrets** | `python-dotenv` | Twelve-factor app compliance: secrets (`GEMINI_API_KEY`) and models are loaded strictly from `.env` and never committed. |

---

## 📌 Documented Assumptions

The following core business rules and architectural assumptions govern this implementation:
1. **Cancellation Boundaries:** A Creator may cancel a request in either `Draft` or `Submitted` status. Once a request reaches `Approved`, it **cannot** be cancelled.
2. **Terminal States:** `Approved`, `Rejected`, and `Cancelled` are strictly terminal statuses. No further transitions can originate from them.
3. **Ownership Enforced:** Only the specific Creator who created a request can `submit` or `cancel` it (`NOT_OWNER` error code otherwise).
4. **Draft Confidentiality:** Reviewers **cannot** see `Draft` requests (`NOT_VISIBLE` error code). Reviewers are only granted access once a request is formally `Submitted`.
5. **Mandatory Human-in-the-Loop:** Approvals and rejections can only be enacted by a human Reviewer with an explicit textual justification.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Git

### 2. Environment Setup
```powershell
# Clone the repository
git clone <repo-url>
cd "prewise project"

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy the `.env.example` file to `.env`:
```powershell
cp .env.example .env
```
To test offline without an API key, leave `LLM_PROVIDER=mock`:
```env
LLM_PROVIDER=mock
LLM_FALLBACK_PROVIDER=mock
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
DB_PATH=data/approval_system.db
ESCALATION_THRESHOLD_HOURS=24
```
To use live Google Gemini, provide your key:
```env
LLM_PROVIDER=gemini
LLM_FALLBACK_PROVIDER=mock
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

---

## 🧪 Running Tests & Verification

### 1. Unit Test Suite (59 Tests)
Run the complete automated test suite across all 5 test modules:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

### 2. Streamlit Web Application
Launch the interactive web UI:
```powershell
.\.venv\Scripts\streamlit.exe run app/ui.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser. Use the sidebar dropdown to switch between personas:
- **Alice (Creator):** Draft and submit requests.
- **Bob (Creator):** Experience separate creator workspace.
- **Rita (Reviewer):** View pending approvals and inspect AI suggestions.

### 3. Evaluation Harness (19 Synthetic Cases)
Run the 19-scenario synthetic evaluation benchmark:
```powershell
.\.venv\Scripts\python.exe -m eval.run_eval
```
Review the generated results in [eval/results.json](file:///c:/Users/shanm/OneDrive/Desktop/prewise%20project/eval/results.json) and [eval/EVAL_REPORT.md](file:///c:/Users/shanm/OneDrive/Desktop/prewise%20project/eval/EVAL_REPORT.md).

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
│   ├── MINI_PRD.md        # Product Requirements Document (2 pages)
│   ├── REFLECTION.md      # Latency/cost metrics, boundaries of trust, roadmap
│   ├── DEMO_SCRIPT.md     # 4-minute walkthrough demonstration script
│   └── STUDY_GUIDE.md     # File-by-file explanations and 15 interview defense Q&As
├── eval/
│   ├── cases.py           # 19 synthetic evaluation cases (happy, ambiguous, injections, edge cases)
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
└── README.md              # Project documentation and guide
```

---

## ⚠️ Known Limitations & Future Roadmap

1. **Authentication:** The Streamlit interface uses a sidebar persona switcher for demonstration convenience. In production, this must be replaced with OAuth2/OIDC JWT bearer tokens.
2. **Database Scale:** SQLite provides excellent single-node performance and ACID guarantees via file locks, but multi-region distributed deployments should migrate to PostgreSQL.
3. **Escalation Trigger:** The SLA escalation daemon currently operates via API/button trigger; in production, run it as a background cron job (e.g., Celery beat or AWS EventBridge).
