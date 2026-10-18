"""Evaluation runner executing all 19 synthetic evaluation cases.

Outputs:
- eval/results.json: Detailed execution metrics and telemetry
- eval/EVAL_REPORT.md: Formatted markdown report with summary tables and failure analysis
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List

from app.audit import AuditLogger
from app.guardrails import sanitize_input, scan_for_injection
from app.notifications import NotificationManager
from app.orchestrator import Orchestrator
from app.rules import Role, Status
from app.service import ErrorCode, RequestService, User
from eval.cases import ALICE, BOB, EVAL_CASES, RITA, EvalCase

# Pricing model (per 1 million tokens in USD)
PRICE_INPUT_PER_1M = float(os.getenv("PRICE_INPUT_PER_1M", "0.075"))    # Gemini 2.5 Flash / equivalent
PRICE_OUTPUT_PER_1M = float(os.getenv("PRICE_OUTPUT_PER_1M", "0.30"))


def run_evaluation() -> Dict[str, Any]:
    """Execute the complete evaluation suite against the active Orchestrator."""
    provider = os.getenv("LLM_PROVIDER", "mock").lower().strip()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    # Rate limit pause for Gemini free tier (15 requests/minute = 4s gap safe margin)
    pause_s = 2.0 if (provider == "gemini" and api_key) else 0.05

    print(f"==================================================")
    print(f"[EVAL] Running Prewise Request Approval Evaluation")
    print(f"Provider: {provider} | Inter-call pause: {pause_s}s")
    print(f"Total Cases: {len(EVAL_CASES)}")
    print(f"==================================================")

    results: List[Dict[str, Any]] = []
    category_stats: Dict[str, Dict[str, int]] = {}

    for case in EVAL_CASES:
        category = case.category
        if category not in category_stats:
            category_stats[category] = {"total": 0, "passed": 0, "failed": 0}
        category_stats[category]["total"] += 1

        print(f"Running [{case.id}] ({case.category}): {case.description}...", end=" ", flush=True)

        service = RequestService(db_path=":memory:")
        orchestrator = Orchestrator(service=service)

        tokens_in = 0
        tokens_out = 0
        start_time = time.perf_counter()
        passed = False
        notes = ""

        try:
            flow = case.input_data.get("flow")

            if flow in ("intake_and_submit", "intake_only"):
                actor = case.input_data["actor"]
                text = case.input_data["text"]
                res = orchestrator.handle_intake(actor, text)
                passed, notes = case.checker(res)

                # Check tokens in audit log
                logs = orchestrator.audit.get_logs()
                if logs:
                    tokens_in = logs[0].get("tokens_in", 0)
                    tokens_out = logs[0].get("tokens_out", 0)

            elif flow == "direct_transition":
                actor = case.input_data["actor"]
                action = case.input_data["action"]
                setup_status = case.input_data["setup_status"]

                # Create draft as Alice
                created = service.create_request(ALICE, "Setup Request", "Description")["request"]
                req_id = created["id"]

                if setup_status == Status.SUBMITTED:
                    service.submit_request(ALICE, req_id)
                elif setup_status == Status.APPROVED:
                    service.submit_request(ALICE, req_id)
                    service.transition_request(RITA, req_id, "approve", "Setup approve")
                elif setup_status == Status.CANCELLED:
                    service.transition_request(ALICE, req_id, "cancel", "Setup cancel")

                res = service.transition_request(actor, req_id, action, reason="Eval direct transition")
                passed, notes = case.checker(res)

            elif flow == "create_violation":
                actor = case.input_data["actor"]
                title = case.input_data["title"]
                description = case.input_data["description"]
                res = service.create_request(actor, title, description)
                passed, notes = case.checker(res)

            elif flow == "injection_scan":
                actor = case.input_data["actor"]
                title = case.input_data["title"]
                description = case.input_data["description"]

                # Scan
                flagged, pattern = scan_for_injection(f"{title} {description}")

                # Create and submit
                created = service.create_request(actor, title, description)["request"]
                service.submit_request(actor, created["id"])

                # Review assist
                assist_res = orchestrator.assist_review(RITA, created["id"])

                # Check DB status
                db_check = service.get_request(RITA, created["id"])
                status_in_db = db_check["request"]["status"]

                passed, notes = case.checker({
                    "injection_detected": flagged or assist_res.get("recommendation", {}).get("injection_suspected", False),
                    "status_remains": status_in_db,
                    "assist_res": assist_res,
                })

            elif flow == "ownership_violation":
                owner = case.input_data["owner"]
                actor = case.input_data["actor"]
                action = case.input_data["action"]
                created = service.create_request(owner, "Alice Item", "Description")["request"]
                res = service.transition_request(actor, created["id"], action)
                passed, notes = case.checker(res)

            elif flow == "visibility_check":
                owner = case.input_data["owner"]
                viewer = case.input_data["viewer"]
                created = service.create_request(owner, "Secret Draft", "Description")["request"]
                res = service.get_request(viewer, created["id"])
                passed, notes = case.checker(res)

            elif flow == "delimiter_breakout":
                raw_text = case.input_data["text"]
                sanitized = sanitize_input(raw_text)
                passed, notes = case.checker({"sanitized": ("</request_data>" not in sanitized)})

            else:
                passed = False
                notes = f"Unknown flow '{flow}'"

        except Exception as e:
            passed = False
            notes = f"Exception during execution: {e}"

        latency_s = time.perf_counter() - start_time
        cost_usd = (tokens_in / 1_000_000 * PRICE_INPUT_PER_1M) + (tokens_out / 1_000_000 * PRICE_OUTPUT_PER_1M)

        if passed:
            category_stats[category]["passed"] += 1
            print("[PASS]")
        else:
            category_stats[category]["failed"] += 1
            print(f"[FAIL]: {notes}")

        results.append({
            "id": case.id,
            "category": case.category,
            "description": case.description,
            "passed": passed,
            "latency_s": round(latency_s, 4),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost_usd, 6),
            "notes": notes,
        })

        if pause_s > 0:
            time.sleep(pause_s)

    total_cases = len(results)
    total_passed = sum(1 for r in results if r["passed"])
    total_failed = total_cases - total_passed
    overall_accuracy = (total_passed / total_cases * 100.0) if total_cases > 0 else 0.0
    avg_latency = sum(r["latency_s"] for r in results) / total_cases if total_cases > 0 else 0.0
    avg_cost = sum(r["cost_usd"] for r in results) / total_cases if total_cases > 0 else 0.0

    eval_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "total_cases": total_cases,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "accuracy_percent": round(overall_accuracy, 2),
        "avg_latency_s": round(avg_latency, 4),
        "avg_cost_usd": round(avg_cost, 6),
        "category_stats": category_stats,
        "cases": results,
    }

    # Save results.json
    eval_dir = Path("eval")
    eval_dir.mkdir(parents=True, exist_ok=True)
    with open(eval_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(eval_payload, f, indent=2)

    # Generate Markdown Report
    generate_markdown_report(eval_payload, eval_dir / "EVAL_REPORT.md")

    print(f"\n==================================================")
    print(f"Summary: {total_passed}/{total_cases} Passed ({overall_accuracy:.1f}%)")
    print(f"Average Latency: {avg_latency:.4f}s | Avg Cost: ${avg_cost:.6f}")
    print(f"Results saved to eval/results.json and eval/EVAL_REPORT.md")
    print(f"==================================================")

    return eval_payload


def generate_markdown_report(data: Dict[str, Any], output_path: Path) -> None:
    """Produce structured EVAL_REPORT.md documenting test outcomes."""
    lines: List[str] = [
        "# Evaluation Report: Request Approval Flow",
        "",
        f"**Date:** `{data['timestamp']}`  ",
        f"**LLM Provider:** `{data['provider']}`  ",
        f"**Overall Accuracy:** `{data['accuracy_percent']}%` ({data['total_passed']}/{data['total_cases']})  ",
        f"**Average Latency:** `{data['avg_latency_s']}s`  ",
        f"**Average Cost per Request:** `${data['avg_cost_usd']:.6f}`  ",
        "",
        "---",
        "",
        "## 1. Category Accuracy Summary",
        "",
        "| Category | Total | Passed | Failed | Accuracy |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ]

    for cat, stats in data["category_stats"].items():
        acc = (stats["passed"] / stats["total"] * 100.0) if stats["total"] > 0 else 0.0
        lines.append(f"| `{cat}` | {stats['total']} | {stats['passed']} | {stats['failed']} | **{acc:.1f}%** |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Detailed Per-Case Results",
        "",
        "| ID | Category | Description | Status | Latency (s) | Tokens In | Tokens Out | Cost ($) | Notes |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    for c in data["cases"]:
        status_icon = "✅ PASS" if c["passed"] else "❌ FAIL"
        lines.append(
            f"| `{c['id']}` | `{c['category']}` | {c['description']} | {status_icon} | {c['latency_s']} | {c['tokens_in']} | {c['tokens_out']} | ${c['cost_usd']:.6f} | {c['notes']} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Failures and Analysis",
        "",
    ])

    failures = [c for c in data["cases"] if not c["passed"]]
    if not failures:
        lines.append("🎉 **Zero failures detected across all 19 synthetic evaluation cases!**")
        lines.append("")
        lines.append("All deterministic state machine constraints, role protections, least-privilege toolboxes, prompt-injection guardrails, and boundary validations performed strictly as specified.")
    else:
        lines.append(f"Identified {len(failures)} failing scenario(s):")
        lines.append("")
        for f in failures:
            lines.append(f"### Case `{f['id']}`: {f['description']}")
            lines.append(f"- **Category:** `{f['category']}`")
            lines.append(f"- **Failure Reason:** {f['notes']}")
            lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    run_evaluation()
